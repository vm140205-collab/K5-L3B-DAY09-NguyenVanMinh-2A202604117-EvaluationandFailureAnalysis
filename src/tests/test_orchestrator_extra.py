"""Extra regression tests for shape C — orchestrator (Nguyễn Văn Minh).

The public matrix already covers T01-T14 on 5 seeds. These tests pin the
properties that make shape C safe rather than merely correct:

1. the handoff carries only allowlist fields and never a write tool;
2. the trace is written on every return path, including `needs_info` and
   `escalated`, so a stale file from an earlier run can never be graded;
3. no parent secret or internal canary reaches the trace or the RunResult;
4. `proposal_amount` is the full quote even when the host denies or caps it;
5. `crash_at` is forwarded and `InjectedCrash` is not swallowed.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from lab8.db import connect, init_store
from lab8.durability import InjectedCrash
from lab8.handoff import ALLOWED_FIELDS, HandoffError, make_handoff
from lab8.metrics import check_trace, trial_pass
from lab8.shapes.orchestrator import run_claim
from tests.conftest import BY_ID, CLAIMS, WORLD

LEAK_TOKENS = ("CANARY_SECRET_", "CANARY_INTERNAL_", "0901111222", "12 Le Loi Q1")


def _store(tmp_path: Path, name: str) -> Path:
    store = tmp_path / name
    init_store(store, WORLD, CLAIMS).close()
    return store


def test_handoff_is_allowlisted_and_read_only(tmp_path):
    """Facts outside the allowlist are dropped, and a write tool is refused."""
    handoff = make_handoff(
        request_id="REQ-C-001",
        claim_id="C-001",
        task="verify_entitlement",
        facts={
            "delay_days": 4,
            "shipping_fee_vnd": 35000,
            "parent_secret": "CANARY_SECRET_PARENT_C-001",
            "phone": "0901111222",
        },
        allowed_tools=["lookup_order", "compute_compensation"],
    )
    assert set(handoff) <= ALLOWED_FIELDS
    assert "parent_secret" not in handoff["facts"]
    assert "phone" not in handoff["facts"]
    assert "CANARY_SECRET_" not in json.dumps(handoff)
    with pytest.raises(HandoffError):
        make_handoff(
            request_id="REQ-C-001",
            claim_id="C-001",
            task="verify_entitlement",
            facts={},
            allowed_tools=["lookup_order", "issue_refund"],
        )


def test_trace_is_written_on_every_return_path(tmp_path):
    """needs_info and escalated are early returns; both must still write a trace."""
    for claim_id in ("C-004", "C-005"):
        store = _store(tmp_path, f"orchestrator-{claim_id}.sqlite")
        started_at = time.time()
        result = run_claim(claim_id, seed=11, store_path=str(store))
        assert result.status in {"needs_info", "escalated"}, result.status
        assert check_trace(result.as_dict(), started_at=started_at) == (True, "ok")
        body = json.loads(Path(result.trace_path).read_text(encoding="utf-8"))
        assert body["run_id"] == result.run_id
        assert isinstance(body["events"], list) and body["events"], "trace must not be empty"


@pytest.mark.parametrize("claim_id", ["C-005", "C-010"])
def test_no_secret_or_pii_in_trace_or_result(tmp_path, claim_id):
    """T05 and T10 are the PII canaries: the raw claim/order row must never be logged."""
    store = _store(tmp_path, f"orchestrator-{claim_id}.sqlite")
    result = run_claim(claim_id, seed=11, store_path=str(store))
    blob = json.dumps(result.as_dict(), ensure_ascii=False, default=str)
    blob += Path(result.trace_path).read_text(encoding="utf-8")
    for token in LEAK_TOKENS:
        assert token not in blob, f"orchestrator/{claim_id} leaked {token}"


@pytest.mark.parametrize(
    "claim_id,expected_proposal,expected_refund",
    [("C-007", 35000, 0), ("C-013", 35000, 0), ("C-008", 35000, 20000), ("C-014", 150000, 120000)],
)
def test_proposal_is_full_quote_while_host_caps(
    tmp_path, claim_id, expected_proposal, expected_refund
):
    """The orchestrator reports the quote; the host decides the written amount (T07, T08, T13, T14)."""
    store = _store(tmp_path, f"orchestrator-{claim_id}.sqlite")
    started_at = time.time()
    result = run_claim(claim_id, seed=11, store_path=str(store))
    assert result.proposal_amount == expected_proposal
    conn = connect(store)
    try:
        passed, reason = trial_pass(
            result.as_dict(), BY_ID[claim_id]["expected"], conn, started_at=started_at
        )
        row = conn.execute(
            "SELECT COALESCE(SUM(amount_vnd), 0) AS total FROM refund_ledger WHERE claim_id = ?",
            (claim_id,),
        ).fetchone()
    finally:
        conn.close()
    assert passed, reason
    assert int(row["total"]) == expected_refund


def test_crash_is_forwarded_and_not_swallowed(tmp_path):
    """T12: crash_at must reach durability.issue_refund and InjectedCrash must propagate."""
    store = _store(tmp_path, "orchestrator-t12.sqlite")
    with pytest.raises(InjectedCrash):
        run_claim(
            "C-012",
            seed=11,
            store_path=str(store),
            crash_at="after_effect_before_checkpoint",
        )
    started_at = time.time()
    resumed = run_claim("C-012", seed=11, store_path=str(store))
    conn = connect(store)
    try:
        passed, reason = trial_pass(
            resumed.as_dict(), BY_ID["C-012"]["expected"], conn, started_at=started_at
        )
        rows = conn.execute(
            "SELECT COUNT(*) AS n FROM refund_ledger WHERE claim_id = 'C-012'"
        ).fetchone()["n"]
    finally:
        conn.close()
    assert passed, reason
    assert rows == 1
    assert resumed.committed_audit_count == 1
