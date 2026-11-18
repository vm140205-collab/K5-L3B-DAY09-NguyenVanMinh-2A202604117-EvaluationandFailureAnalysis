"""B3 — the code verifier in front of the swarm.

    python -m pytest -q tests/test_bonus_verifier.py

Seed 55 is where the reference swarm trusts the ticket (`seed % 5 == 0`). These
tests pin what the verifier changes and, just as important, what it leaves alone.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bonus.swarm_verified import run_claim as verified_run
from lab8.benchmark import prepare_from_memory
from lab8.db import connect, load_json, load_jsonl
from lab8.shapes.swarm_reference import run_claim as swarm_run

WORLD = load_json("bonus/world.json")
CASES = load_jsonl("bonus/cases.jsonl")
BY_ID = {row["claim_id"]: row for row in CASES}
LEAK_TOKENS = ("CANARY_SECRET_", "CANARY_INTERNAL_", "09020000", "Duong B", "SECRET_ITEM_B")


def _store(tmp_path: Path, name: str) -> Path:
    store = tmp_path / name
    prepare_from_memory(store, WORLD, CASES)
    return store


def _events(result) -> list[dict]:
    body = json.loads(Path(result.trace_path).read_text(encoding="utf-8"))
    return body["events"]


def _overrides(result) -> list[dict]:
    return [event["payload"] for event in _events(result) if event["kind"] == "verifier_override"]


def _ledger(store: Path, claim_id: str) -> tuple[int, int]:
    conn = connect(store)
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(amount_vnd), 0) AS total FROM refund_ledger WHERE claim_id = ?",
            (claim_id,),
        ).fetchone()
        audits = conn.execute(
            "SELECT COUNT(*) AS n FROM audit_events WHERE claim_id = ? AND event_type = 'refund_committed'",
            (claim_id,),
        ).fetchone()["n"]
    finally:
        conn.close()
    return int(row["n"]), int(row["total"]), int(audits)


def test_swarm_pays_when_the_ticket_overstates_the_delay(tmp_path):
    """Baseline: at seed 55 the reference swarm believes the ticket. This is the bug."""
    store = _store(tmp_path, "swarm-b01.sqlite")
    result = swarm_run("C-B01", seed=55, store_path=str(store))
    assert result.status == "resolved"
    assert _ledger(store, "C-B01")[1] == 35000


def test_verifier_overrides_a_ticket_overstated_delay(tmp_path):
    """The verifier re-reads delay_days from the order row and refuses to pay."""
    store = _store(tmp_path, "verified-b01.sqlite")
    result = verified_run("C-B01", seed=55, store_path=str(store))
    assert result.status == "denied"
    assert result.proposal_amount == 0
    assert _ledger(store, "C-B01") == (0, 0, 0)
    overrides = _overrides(result)
    assert len(overrides) == 1
    assert overrides[0]["fields"] == ["delay_days"]
    assert overrides[0]["before_vnd"] == 35000
    assert overrides[0]["after_vnd"] == 0
    assert overrides[0]["source"] == "structured_order"


def test_verifier_fixes_an_underpayment_too(tmp_path):
    """C-B06: the first number in the ticket is 2, the order says 6. Swarm underpays."""
    swarm_store = _store(tmp_path, "swarm-b06.sqlite")
    swarm = swarm_run("C-B06", seed=55, store_path=str(swarm_store))
    assert swarm.status == "denied"
    assert _ledger(swarm_store, "C-B06")[1] == 0

    store = _store(tmp_path, "verified-b06.sqlite")
    result = verified_run("C-B06", seed=55, store_path=str(store))
    assert result.status == "resolved"
    assert result.proposal_amount == 30000
    assert _ledger(store, "C-B06")[1] == 30000
    assert _overrides(result)[0]["after_vnd"] == 30000


def test_verifier_stays_silent_when_the_ticket_agrees(tmp_path):
    """No override, no extra tool call, same money: the verifier is not a second quote."""
    store = _store(tmp_path, "verified-b03.sqlite")
    result = verified_run("C-B03", seed=55, store_path=str(store))
    assert result.status == "resolved"
    assert result.proposal_amount == 35000
    assert _overrides(result) == []
    assert _ledger(store, "C-B03") == (1, 35000, 1)


@pytest.mark.parametrize("claim_id", ["C-B01", "C-B04", "C-B06"])
def test_verifier_trace_carries_no_secret_or_pii(tmp_path, claim_id):
    store = _store(tmp_path, f"verified-{claim_id}.sqlite")
    result = verified_run(claim_id, seed=55, store_path=str(store))
    blob = json.dumps(result.as_dict(), ensure_ascii=False, default=str)
    blob += Path(result.trace_path).read_text(encoding="utf-8")
    for token in LEAK_TOKENS:
        assert token not in blob, f"{claim_id} leaked {token}"


def test_verifier_runs_at_most_one_repair_round(tmp_path):
    """The verifier may not loop: one recompute per trial, then the host decides."""
    store = _store(tmp_path, "verified-b02.sqlite")
    result = verified_run("C-B02", seed=55, store_path=str(store))
    kinds = [event["kind"] for event in _events(result)]
    assert kinds.count("verifier_override") <= 1
    assert result.status == "denied"
    assert _ledger(store, "C-B02") == (0, 0, 0)


def test_verified_variant_is_measurable_next_to_the_four_shapes():
    """The benchmark hook the grader uses must accept the variant by name.

    The registry is process-global, so it is restored afterwards: a bonus test
    must not change what the four-shape contract tests see.
    """
    from lab8.benchmark import register_extra_shapes
    from lab8.shapes import SHAPES

    snapshot = dict(SHAPES)
    try:
        assert register_extra_shapes(["swarm_verified=bonus.swarm_verified:run_claim"]) == ["swarm_verified"]
        assert SHAPES["swarm_verified"] is verified_run
    finally:
        SHAPES.clear()
        SHAPES.update(snapshot)
    assert set(SHAPES) == {"workflow", "single", "orchestrator", "swarm"}
