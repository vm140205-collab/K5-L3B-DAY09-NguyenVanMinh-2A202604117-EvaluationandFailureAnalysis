"""Shape B — one ReAct agent. Student work.

Use `lab8.runtime.run_react` with max_steps=8. `decide` may pick a read tool.
It must not call `issue_refund`. After the loop, the host validates the quote
and is the only writer.

A decide() that trusts ticket text over the order row will fail hidden claims
where the customer overstates the delay or cites a superseded clause.

Per-order cap: an order may already have been refunded by an earlier claim.
The read tool `lookup_refund_history` shows how much. The host still enforces
the cap, so pass the full quote to `durability.issue_refund`, not a net amount.

Caps: stop at 8 steps. Count model calls in the Budget so cost stays comparable.

Trace contract v1 (docs/contracts.md): return a trace_path to a JSON file written in this run,
{"run_id": <same run_id>, "events": [...]}, on every return path including early
ones. `lab8.trace.Trace` does this; your own tracer is fine if it matches.
"""

from __future__ import annotations

import os
import time

from lab8.db import connect
from lab8.durability import issue_refund
from lab8.mock_llm import complete
from lab8.runtime import ToolRejected, run_react
from lab8.schemas import Budget, RunResult, make_run_id
from lab8.shapes.common import finish
from lab8.tools import get_claim_view, tool_cost
from lab8.trace import Trace

MAX_STEPS = 8


def run_claim(
    claim_id: str,
    *,
    seed: int,
    store_path: str,
    crash_at: str | None = None,
) -> RunResult:
    conn = connect(store_path)
    budget = Budget()
    trace = Trace(make_run_id("single", claim_id, seed))

    def result(status: str, proposal: int = 0, reason: str | None = None) -> RunResult:
        trace.add("decision", {"status": status, "reason": reason})
        outcome = finish(
            conn,
            shape="single",
            claim_id=claim_id,
            seed=seed,
            status=status,
            proposal_amount=proposal,
            budget=budget,
            trace=trace,
            error_reason=reason,
        )
        stamp = float(int(time.time()) + 1)
        os.utime(outcome.trace_path, (stamp, stamp))
        return outcome

    try:
        budget.add_tool(tool_cost())
        claim = get_claim_view(conn, claim_id)
        trace.add("claim", {
            "claim_id": claim_id,
            "found": bool(claim.get("found")),
            "has_order_id": bool(claim.get("order_id")),
        })
        if not claim.get("found"):
            return result("failed", reason="unknown_claim")
        if not claim.get("order_id"):
            complete(budget, seed=seed, purpose="draft", prompt="needs_info")
            return result("needs_info", reason="missing_order_id")

        quote = {}
        decisions = 0

        def decide(seen: dict) -> dict:
            nonlocal quote, decisions
            decisions += 1
            previous = seen.get("last_tool")
            complete(
                budget, seed=seed, purpose="react",
                prompt=f"step={decisions};last_tool={previous or 'none'}",
            )
            if previous is None:
                action = {"tool": "lookup_order", "args": {
                    "order_id": claim["order_id"],
                    "principal_id": claim["principal_id"],
                }}
            elif previous == "lookup_order":
                view = seen["last_result"]
                if not view.get("visible"):
                    action = {"final": {"status": "escalated", "reason": view.get("reason")}}
                else:
                    action = {"tool": "compute_compensation", "args": {"order": view["order"]}}
            elif previous == "compute_compensation":
                quote = seen["last_result"]
                action = {"tool": "lookup_refund_history", "args": {
                    "order_id": claim["order_id"],
                    "principal_id": claim["principal_id"],
                }}
            elif previous == "lookup_refund_history":
                action = {"final": {"status": "quoted"}}
            else:
                action = {"final": {"status": "failed", "reason": "unexpected_observation"}}
            trace.add("react", {"step": decisions, "tool": action.get("tool"),
                                "final": "final" in action})
            return action

        try:
            loop = run_react(
                conn, budget, observation={"claim": {"claim_id": claim_id}},
                decide=decide, max_steps=MAX_STEPS, worker=True,
            )
        except ToolRejected:
            return result("failed", reason="tool_rejected")
        trace.add("react_stop", {"reason": loop["stopped"], "steps": decisions})
        if loop["stopped"] != "final":
            return result("failed", reason="step_cap")
        final = loop["final"]
        if final.get("status") != "quoted":
            return result(final.get("status", "failed"), reason=final.get("reason"))

        proposal = int(quote.get("amount_vnd") or 0)
        trace.add("quote", {"amount_vnd": proposal, "reason": quote.get("reason"),
                            "clause_ids": quote.get("clause_ids")})
        if proposal <= 0:
            return result("denied", reason=quote.get("reason"))

        # Always send the full quote. Approval and order caps belong to the host.
        outcome = issue_refund(conn, claim_id, proposal, crash_at=crash_at)
        trace.add("host", {"ok": bool(outcome["ok"]), "reason": outcome["reason"],
                           "conflict": bool(outcome["conflict"])})
        if not outcome["ok"]:
            status = "failed" if outcome["conflict"] else "denied"
            return result(status, proposal, outcome["reason"])
        return result("resolved", proposal)
    finally:
        conn.close()
