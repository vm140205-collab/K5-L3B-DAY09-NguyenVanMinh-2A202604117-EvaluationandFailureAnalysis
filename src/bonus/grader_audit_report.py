"""B7 — audit the three candidate `summarize` builds with metamorphic relations.

Run from `src/`:

    python -m bonus.grader_audit_report

Writes `reports/bonus_grader_audit.json`. Nothing here is hand-written: every
number in the report comes from this run, and the tests in
`tests/test_bonus_grader_audit.py` assert the same relations.

Three relations come from `grader_audit/README.md`; the fourth is ours (R4), and
it exists because none of the first three can see a systematic cost inflation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from grader_audit import grader_a, grader_b, grader_c
from lab8.compensation import quote

BUILDS: dict[str, Any] = {"a": grader_a, "b": grader_b, "c": grader_c}
FIXTURES = Path("grader_audit") / "fixtures"
OUT = Path("reports") / "bonus_grader_audit.json"

# Rates that the repo's own summarize() definition makes invariant under
# duplication. pass_5 is excluded on purpose: it requires one row per seed, so
# duplicating a list breaks its precondition for every build, including the
# correct one. That is a defect in the relation, not in a build, and the report
# says so instead of blaming a build.
INVARIANT_RATES = ("pass_rate", "seed_pass_rates", "mean_steps", "mean_model_calls", "mean_tool_calls")
DOUBLED_TOTALS = ("trials", "graded_trials", "successes", "total_simulated_cost_vnd")


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _flat(report: dict[str, Any], shape: str, key: str) -> Any:
    return report[shape][key]


def relation_delay() -> dict[str, Any]:
    """R1: 2 days is below min_delay_days, 3 days is not. The decision must flip."""
    fixture = _load("metamorphic_claim_delay.json")
    policies = fixture["policies"]
    as_of = fixture["as_of"]
    a = quote(fixture["a"]["order"], policies, as_of=as_of)
    b = quote(fixture["b"]["order"], policies, as_of=as_of)
    return {
        "relation": "delay_days_2_vs_3",
        "goes_through": "lab8.compensation.quote",
        "a": {"delay_days": fixture["a"]["order"]["delay_days"], "amount_vnd": a.amount_vnd, "reason": a.reason},
        "b": {"delay_days": fixture["b"]["order"]["delay_days"], "amount_vnd": b.amount_vnd, "reason": b.reason},
        "holds": a.amount_vnd == 0 and b.amount_vnd == fixture["b"]["order"]["shipping_fee_vnd"],
    }


def relation_infra() -> dict[str, Any]:
    """R2: adding infra_error rows must not move any rate."""
    fixture = _load("metamorphic_infra.json")
    rows = []
    for name, build in BUILDS.items():
        before = build.summarize(fixture["a"])
        after = build.summarize(fixture["b"])
        shape = sorted(before)[0]
        moved = {
            key: {"a": _flat(before, shape, key), "b": _flat(after, shape, key)}
            for key in ("pass_rate", "seed_pass_rates", "cost_per_success_vnd", "mean_steps")
            if _flat(before, shape, key) != _flat(after, shape, key)
        }
        rows.append(
            {
                "build": name,
                "shape": shape,
                "graded_trials": {"a": _flat(before, shape, "graded_trials"), "b": _flat(after, shape, "graded_trials")},
                "moved": moved,
                "holds": not moved,
            }
        )
    return {"relation": "infra_errors_do_not_move_pass_rate", "builds": rows}


def relation_duplicate() -> dict[str, Any]:
    """R3: duplicating the list keeps rates and doubles totals."""
    fixture = _load("metamorphic_duplicate.json")
    rows = []
    for name, build in BUILDS.items():
        before = build.summarize(fixture["a"])
        after = build.summarize(fixture["b"])
        shape = sorted(before)[0]
        moved = {
            key: {"a": _flat(before, shape, key), "b": _flat(after, shape, key)}
            for key in INVARIANT_RATES + ("cost_per_success_vnd",)
            if _flat(before, shape, key) != _flat(after, shape, key)
        }
        totals = {
            key: {"a": _flat(before, shape, key), "b": _flat(after, shape, key)}
            for key in DOUBLED_TOTALS
        }
        totals_ok = all(
            (pair["b"] == 2 * pair["a"]) if isinstance(pair["a"], (int, float)) else pair["a"] == pair["b"]
            for pair in totals.values()
        )
        rows.append({"build": name, "shape": shape, "moved": moved, "totals": totals, "holds": not moved and totals_ok})
    return {"relation": "duplicated_list_keeps_rates_doubles_totals", "builds": rows}


def relation_pass5_under_duplication() -> dict[str, Any]:
    """R3b: the README claims pass_5 is invariant. Measure it instead of assuming."""
    fixture = _load("metamorphic_duplicate.json")
    rows = []
    for name, build in BUILDS.items():
        before = build.summarize(fixture["a"])
        after = build.summarize(fixture["b"])
        shape = sorted(before)[0]
        rows.append(
            {
                "build": name,
                "pass_5": {"a": _flat(before, shape, "pass_5"), "b": _flat(after, shape, "pass_5")},
                "holds": _flat(before, shape, "pass_5") == _flat(after, shape, "pass_5"),
            }
        )
    return {"relation": "pass_5_invariant_under_duplication (README claim)", "builds": rows}


def relation_identity() -> dict[str, Any]:
    """R4 (ours): one graded trial must report that trial's own numbers.

    A metric that adds cost it was not given is invisible to R2 and R3 — both
    scale the whole list — but it cannot survive a list with exactly one trial,
    because there is nothing to double-count against.
    """
    trial = {
        "shape": "workflow",
        "claim_id": "C-01",
        "seed": 11,
        "passed": True,
        "cost_estimate": 12.0,
        "steps": 3,
        "model_calls": 1,
        "tool_calls": 2,
        "reason": "ok",
        "infra_error": False,
    }
    rows = []
    for name, build in BUILDS.items():
        stats = build.summarize([trial])["workflow"]
        rows.append(
            {
                "build": name,
                "cost_per_success_vnd": stats["cost_per_success_vnd"],
                "total_simulated_cost_vnd": stats["total_simulated_cost_vnd"],
                "mean_steps": stats["mean_steps"],
                "holds": (
                    stats["cost_per_success_vnd"] == trial["cost_estimate"]
                    and stats["total_simulated_cost_vnd"] == trial["cost_estimate"]
                    and stats["mean_steps"] == trial["steps"]
                ),
            }
        )
    return {"relation": "single_trial_reports_its_own_cost", "builds": rows}


def run() -> dict[str, Any]:
    relations = [
        relation_delay(),
        relation_infra(),
        relation_duplicate(),
        relation_pass5_under_duplication(),
        relation_identity(),
    ]
    # A build is consistent when it satisfies every relation that is actually
    # true of the reference definition. R1 is build-independent; R3b is false
    # for all builds, so it cannot discriminate and is reported separately.
    verdict: dict[str, Any] = {}
    for name in BUILDS:
        checks = {}
        for rel in relations:
            if "builds" not in rel:
                continue
            if rel["relation"].startswith("pass_5_invariant"):
                continue
            checks[rel["relation"]] = next(b["holds"] for b in rel["builds"] if b["build"] == name)
        verdict[name] = {"checks": checks, "consistent": all(checks.values())}
    report = {
        "topic": "B7",
        "command": "python -m bonus.grader_audit_report",
        "relations": relations,
        "verdict": verdict,
        "consistent_builds": sorted(name for name, row in verdict.items() if row["consistent"]),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def main() -> None:
    report = run()
    print("build | R2 infra | R3 duplicate | R3b pass^5 | R4 identity | consistent")
    for name, row in report["verdict"].items():
        rel = {r["relation"]: r for r in report["relations"] if "builds" in r}
        infra = next(b["holds"] for b in rel["infra_errors_do_not_move_pass_rate"]["builds"] if b["build"] == name)
        dup = next(b["holds"] for b in rel["duplicated_list_keeps_rates_doubles_totals"]["builds"] if b["build"] == name)
        p5 = next(b["holds"] for b in rel["pass_5_invariant_under_duplication (README claim)"]["builds"] if b["build"] == name)
        ident = next(b["holds"] for b in rel["single_trial_reports_its_own_cost"]["builds"] if b["build"] == name)
        print(f"  {name}  |   {infra!s:5} |    {dup!s:5}      |   {p5!s:5}   |   {ident!s:5}    | {row['consistent']}")
    print()
    for rel in report["relations"]:
        if "builds" not in rel:
            print(f"{rel['relation']}: a={rel['a']} b={rel['b']} -> holds={rel['holds']}")
            continue
        print(rel["relation"])
        for row in rel["builds"]:
            extra = row.get("moved") or {}
            detail = " ".join(f"{k}:{_fmt(v['a'])}->{_fmt(v['b'])}" for k, v in extra.items()) or "không đổi"
            print(f"   [{row['build']}] holds={row['holds']} | {detail}")
    print(f"\nconsistent builds: {report['consistent_builds']}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
