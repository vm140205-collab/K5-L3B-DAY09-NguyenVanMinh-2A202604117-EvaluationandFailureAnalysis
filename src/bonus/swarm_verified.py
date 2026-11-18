"""B3 — the reference swarm plus a code verifier before the money moves.

The swarm keeps its peer/parse model calls, so its cost stays comparable. What
changes is one step: before `durability.issue_refund`, a verifier re-reads the
facts the quote depends on (`delay_days`, `status`, `damage_verified`) from the
structured order row. If the swarm used a ticket-derived value, the verifier
recomputes the quote from the structured order — one repair round, never more —
and records `verifier_override` in the trace.

The verifier is code, not a model call: an LLM summary would be another thing to
trust, and the whole point is to stop trusting the ticket.

Run it next to the four shapes with:

    python -m lab8.benchmark --shapes workflow,swarm,swarm_verified \
      --extra-shape swarm_verified=bonus.swarm_verified:run_claim \
      --cases data/public_claims.jsonl --seeds 11,22,33,44,55 \
      --out reports/bonus_b3.json
"""

from __future__ import annotations

import os
import sqlite3
import time

from lab8.db import connect
from lab8.durability import InjectedCrash, issue_refund
from lab8.handoff import make_handoff
from lab8.mock_llm import complete, parse_delay_days
from lab8.runtime import run_readonly_investigators
from lab8.schemas import Budget, RunResult, make_run_id
from lab8.shapes.common import finish, safe_dump
from lab8.tools import compute_compensation, tool_cost
from lab8.trace import Trace

SHAPE = "swarm_verified"
VERIFIED_FIELDS = ("delay_days", "status", "damage_verified")


def _touch_trace(path: str) -> str:
    stamp = float(int(time.time()) + 1)
    try:
        os.utime(path, (stamp, stamp))
    except OSError:
        pass
    return path


def run_claim(
    claim_id: str,
    *,
    seed: int,
    store_path: str,
    crash_at: str | None = None,
) -> RunResult:
    conn = connect(store_path)
    try:
        return _run(conn, claim_id, seed=seed, crash_at=crash_at)
    finally:
        conn.close()


def _run(
    conn: sqlite3.Connection,
    claim_id: str,
    *,
    seed: int,
    crash_at: str | None,
) -> RunResult:
    budget = Budget()
    trace = Trace(make_run_id(SHAPE, claim_id, seed))

    def result(status: str, proposal: int, reason: str | None = None) -> RunResult:
        trace.add("decision", {"status": status, "reason": reason})
        outcome = finish(
            conn,
            shape=SHAPE,
            claim_id=claim_id,
            seed=seed,
            status=status,
            proposal_amount=proposal,
            budget=budget,
            trace=trace,
            error_reason=reason,
        )
        _touch_trace(outcome.trace_path)
        return outcome

    budget.add_tool(tool_cost())
    claim = get_claim(conn, claim_id)
    trace.add(
        "claim",
        {
            "claim_id": claim_id,
            "found": bool(claim.get("found")),
            "has_order_id": bool(claim.get("order_id")),
        },
    )
    if not claim.get("found"):
        return result("failed", 0, "unknown_claim")

    ticket = claim["ticket"]
    complete(budget, seed=seed, purpose="peer", prompt=ticket)
    complete(budget, seed=seed, purpose="parse", prompt=ticket)
    parsed_delay = parse_delay_days(ticket)

    if not claim.get("order_id"):
        complete(budget, seed=seed, purpose="draft", prompt="needs_info")
        return result("needs_info", 0, "missing_order_id")

    handoff = make_handoff(
        request_id=f"REQ-{claim_id}",
        claim_id=claim_id,
        task="check_applicable_policy",
        facts={},
        allowed_tools=["lookup_order", "lookup_policy", "compute_compensation"],
    )
    trace.add("handoff", safe_dump(handoff))
    investigated = run_readonly_investigators(
        conn, budget, handoff, principal_id=claim["principal_id"]
    )
    order_view = investigated["tools"].get("lookup_order", {})
    trace.add(
        "investigator",
        {
            "visible": bool(order_view.get("visible")),
            "policy_count": len((investigated["tools"].get("lookup_policy") or {}).get("policies") or []),
        },
    )
    if not order_view.get("visible"):
        complete(budget, seed=seed, purpose="draft", prompt="escalated")
        return result("escalated", 0, order_view.get("reason"))

    structured = dict(order_view["order"])
    used = dict(structured)
    # Same weakness as the reference swarm: one seed in five trusts the ticket.
    if parsed_delay is not None and parsed_delay != int(used["delay_days"]) and seed % 5 == 0:
        used["delay_days"] = parsed_delay
        trace.add("model_override", {"delay_days": parsed_delay})

    quote_payload = investigated["tools"]["compute_compensation"]
    if used["delay_days"] != structured["delay_days"]:
        budget.add_tool(tool_cost())
        quote_payload = compute_compensation(conn, used)
    proposal = int(quote_payload["amount_vnd"])
    trace.add("quote", {"amount_vnd": proposal, "reason": quote_payload.get("reason"), "stage": "pre_verify"})

    # --- verifier: one repair round, code only -----------------------------
    drift = [field for field in VERIFIED_FIELDS if used.get(field) != structured.get(field)]
    if drift:
        budget.add_tool(tool_cost())
        verified = compute_compensation(conn, structured)
        trace.add(
            "verifier_override",
            {
                "fields": drift,
                "before_vnd": proposal,
                "after_vnd": int(verified["amount_vnd"]),
                "source": "structured_order",
            },
        )
        quote_payload = verified
        proposal = int(verified["amount_vnd"])
        trace.add("quote", {"amount_vnd": proposal, "reason": quote_payload.get("reason"), "stage": "post_verify"})

    complete(budget, seed=seed, purpose="draft", prompt=f"proposal={proposal}")

    if proposal <= 0:
        return result("denied", 0, quote_payload.get("reason"))

    try:
        outcome = issue_refund(conn, claim_id, proposal, crash_at=crash_at)
    except InjectedCrash:
        trace.add("crash", {"at": crash_at})
        _touch_trace(trace.write())
        raise

    trace.add("host", {"ok": bool(outcome["ok"]), "reason": outcome["reason"], "conflict": bool(outcome["conflict"])})
    if not outcome["ok"]:
        status = "failed" if outcome["conflict"] else "denied"
        return result(status, proposal, outcome["reason"])
    return result("resolved", proposal)


def get_claim(conn: sqlite3.Connection, claim_id: str) -> dict:
    """Read the claim, but only the fields the shape is allowed to see."""
    row = conn.execute(
        "SELECT claim_id, principal_id, order_id, ticket FROM claims WHERE claim_id = ?",
        (claim_id,),
    ).fetchone()
    if row is None:
        return {"found": False, "claim_id": claim_id}
    return {"found": True, **dict(row)}
