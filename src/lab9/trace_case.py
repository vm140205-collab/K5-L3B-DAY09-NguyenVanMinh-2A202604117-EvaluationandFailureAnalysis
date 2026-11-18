"""Trace -> decision: lay one trial's reply, tool calls and ledger side by side.

    python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11

Find the FIRST wrong step, then turn that trial into a regression case
(docs/trace_case.md). Runs the shape on a fresh temp store, never the team DB.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from lab8.console import utf8_stdio
from lab8.db import load_json, load_jsonl
from lab9 import variants
from lab9.eval import WORLD, make_task


def investigate(shape: str, claim_id: str, seed: int, bugs: str | None = None) -> dict:
    """bugs="a,b": run one single-bug shape so each taxonomy row has a reproducible trace
    (python -m lab9.trace_case --bugs stale_clause --claim C-006 --seed 11)."""
    variants.register()
    if bugs:
        from lab8.shapes import SHAPES
        from lab9.variant_agent import make_shape

        switch = frozenset(b.strip() for b in bugs.split(",") if b.strip())
        shape = f"trace:{'+'.join(sorted(switch))}"
        SHAPES[shape] = make_shape(shape, switch)
    claims = load_jsonl(Path("data/public_claims.jsonl"))
    labels = {c["claim_id"]: c["expected"] for c in claims}
    with tempfile.TemporaryDirectory(prefix="lab9-case-", ignore_cleanup_errors=True) as tmp:
        trial = make_task(shape, load_json(WORLD), claims, labels, Path(tmp))({"claim_id": claim_id, "seed": seed})
    return {"trial": trial, "label": labels[claim_id]}


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.trace_case")
    ap.add_argument("--shape", help="a registered shape, or omit it and pass --bugs")
    ap.add_argument("--bugs", help="comma-separated failure switches; runs shape trace:<bugs>")
    ap.add_argument("--claim", required=True)
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args(argv)
    if not args.shape and not args.bugs:
        ap.error("pass --shape, or --bugs to run one bug switch at a time")
    shape = args.shape or f"trace:{args.bugs}"
    case = investigate(shape, args.claim, args.seed, args.bugs)
    t, label = case["trial"], case["label"]
    print(f"== {shape} {args.claim}@{args.seed}  lab8 grader: {'PASS' if t['lab8_pass'] else 'FAIL'} ({t['lab8_reason']})")
    print("-- trace (step, kind, payload)")
    for i, e in enumerate(t["events"], 1):
        print(f"  {i:>2} {e.get('kind', '?'):<18} {json.dumps(e.get('payload'), ensure_ascii=False)[:110]}")
    print("-- ledger vs label")
    for k in ("refund_vnd", "refund_count"):
        mark = "" if t["snapshot"].get(k) == label.get(k) else "   <-- differs"
        print(f"  {k:<14} ledger={t['snapshot'].get(k)!s:<8} label={label.get(k)}{mark}")
    print(f"  status         result={t['result'].get('status')!s:<8} label={label.get('status')}")
    print(f"  unexpected ledger rows: {t['unexpected_rows']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
