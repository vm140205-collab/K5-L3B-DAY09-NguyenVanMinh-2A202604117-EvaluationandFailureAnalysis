"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item
from lab9.graders import GRADERS


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []

    # 1. no NaN/inf may reach a threshold comparison (nan < min is False: a naive gate passes it)
    for mid, val in (pr.get("metrics") or {}).items():
        if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
            problems.append(f"metric {mid} is {val!r}")

    rows = pr.get("rows") or []
    manifest = pr.get("manifest") or {}
    items, seeds = manifest.get("items"), manifest.get("seeds") or []
    # 2. the report must hold exactly one row per (item, seed)
    if isinstance(items, int) and len(rows) != items * len(seeds):
        problems.append(f"{len(rows)} row(s) for {items} item(s) x {len(seeds)} seed(s) = {items * len(seeds)}")
    pairs = [(r.get("item_id"), r.get("seed")) for r in rows]
    dup = sorted({p for p in pairs if pairs.count(p) > 1}, key=str)
    problems += [f"duplicate row {i}@{s}" for i, s in dup]
    # 3. same (item, seed) set as the baseline: no cherry-picked seeds, no dropped items
    base_pairs = {(r.get("item_id"), r.get("seed")) for r in base.get("rows") or []}
    missing, extra = sorted(base_pairs - set(pairs), key=str), sorted(set(pairs) - base_pairs, key=str)
    if missing:
        problems.append(f"{len(missing)} (item, seed) pair(s) in the baseline are missing, e.g. {missing[0][0]}@{missing[0][1]}")
    if extra:
        problems.append(f"{len(extra)} (item, seed) pair(s) not in the baseline, e.g. {extra[0][0]}@{extra[0][1]}")
    # 4. a crashed grader silently scores as "missing" and drops out of the mean
    if pr.get("evaluator_failures"):
        problems.append(f"{len(pr['evaluator_failures'])} evaluator failure(s): {pr['evaluator_failures'][0]}")
    graded = [m["id"] for m in spec.get("metrics", []) if m["id"] in GRADERS]
    silent = sorted({f"{r.get('item_id')}@{r.get('seed')}:{m}" for r in rows for m in graded
                     if m in r and r[m] is None})
    problems += [f"grader returned no value for {x}" for x in silent[:5]]
    if len(silent) > 5:
        problems.append(f"... and {len(silent) - 5} more silent grader value(s)")
    # 5. slice tags must be the same as the baseline's: relabelling an item hides its regression
    def tags(report: dict) -> dict:
        out: dict[tuple, tuple] = {}
        for r in report.get("rows") or []:
            key = (r.get("item_id"), r.get("seed"))
            out[key] = tuple(sorted(r.get("slices") or []))
        return out
    pt, bt = tags(pr), tags(base)
    changed = sorted((k for k in set(pt) & set(bt) if pt[k] != bt[k]), key=str)
    problems += [f"slice tags changed for {i}@{s}: {bt[(i, s)]} -> {pt[(i, s)]}" for i, s in changed[:5]]
    # 6. ratchet: on the same eval-set version a spec may only get stricter
    if base_spec is not None and spec.get("eval_set_version") == base_spec.get("eval_set_version"):
        problems += _ratchet(spec, base_spec)
    return problems


def _ratchet(spec: dict, base_spec: dict) -> list[str]:
    problems: list[str] = []
    old = {m["id"]: m for m in base_spec.get("metrics", [])}
    new = {m["id"]: m for m in spec.get("metrics", [])}
    for mid, bm in old.items():
        m = new.get(mid)
        if m is None:
            problems.append(f"metric {mid} disappeared from the spec")
            continue
        bth, th = bm.get("threshold") or {}, m.get("threshold") or {}
        if "max" in bth and (th.get("max") is None or th["max"] > bth["max"]):
            problems.append(f"metric {mid}: max raised {bth['max']} -> {th.get('max')}")
        if "min" in bth and (th.get("min") is None or th["min"] < bth["min"]):
            problems.append(f"metric {mid}: min lowered {bth['min']} -> {th.get('min')}")
        if bth.get("no_significant_drop") and not th.get("no_significant_drop"):
            problems.append(f"metric {mid}: no_significant_drop removed")
        if bm.get("blocking") and not m.get("blocking"):
            problems.append(f"metric {mid}: no longer blocking")
    key = lambda s: (s.get("name"), s.get("metric"))
    old_s = {key(s): s for s in base_spec.get("slices") or []}
    new_s = {key(s): s for s in spec.get("slices") or []}
    for k, bs in old_s.items():
        s = new_s.get(k)
        if s is None:
            problems.append(f"slice {k[0]}/{k[1]} disappeared from the spec")
            continue
        if "min" in bs and (s.get("min") is None or s["min"] < bs["min"]):
            problems.append(f"slice {k[0]}/{k[1]}: min lowered {bs['min']} -> {s.get('min')}")
        if bs.get("no_significant_drop") and not s.get("no_significant_drop"):
            problems.append(f"slice {k[0]}/{k[1]}: no_significant_drop removed")
        if bs.get("blocking") and not s.get("blocking"):
            problems.append(f"slice {k[0]}/{k[1]}: no longer blocking")
    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for s in spec.get("slices") or []:
        name, metric = s["name"], s["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        val = round(sum(a.values()) / len(a), 4) if a else None
        th = {k: v for k, v in s.items() if k not in ("name", "metric")}
        verdict, note = "ok", ""
        if not a:
            verdict = "missing"
        elif "min" in s and val < s["min"]:
            verdict = "fail"
        if s.get("no_significant_drop") and a and b:
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000),
                                               rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}] ({len(keys)} items)"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and s.get("blocking"):
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if s.get("blocking") else "warn")
        lines.append(f"  {sid:<32} {val!s:<8} {json.dumps(th):<40} {note:<30} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
