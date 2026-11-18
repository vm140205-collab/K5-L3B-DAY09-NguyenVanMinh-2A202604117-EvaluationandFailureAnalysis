"""B7 — audit the three candidate `summarize` builds with metamorphic relations.

    python -m pytest -q tests/test_bonus_grader_audit.py

Each test states the relation, then the *measured* outcome per build. The
outcomes are not guesses: they come from `python -m bonus.grader_audit_report`,
which writes `reports/bonus_grader_audit.json`. A build that deviates is
asserted to deviate by the exact amount, so a silent change in the grader turns
this file red instead of quietly passing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from bonus.grader_audit_report import (
    BUILDS,
    FIXTURES,
    relation_delay,
    relation_duplicate,
    relation_identity,
    relation_infra,
    relation_pass5_under_duplication,
    run,
)
from lab8.compensation import quote

BUILD_NAMES = sorted(BUILDS)


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _stats(build: str, trials: list[dict[str, Any]]) -> dict[str, Any]:
    report = BUILDS[build].summarize(trials)
    return report[sorted(report)[0]]


# ---------------------------------------------------------------- R1, business


def test_r1_delay_relation_flips_the_decision():
    """2 days is under min_delay_days=3, 3 days is not: 0 VND vs the shipping fee."""
    fixture = _fixture("metamorphic_claim_delay.json")
    below = quote(fixture["a"]["order"], fixture["policies"], as_of=fixture["as_of"])
    at = quote(fixture["b"]["order"], fixture["policies"], as_of=fixture["as_of"])
    assert fixture["a"]["order"]["delay_days"] == 2
    assert fixture["b"]["order"]["delay_days"] == 3
    assert below.amount_vnd == 0
    assert at.amount_vnd == fixture["b"]["order"]["shipping_fee_vnd"] == 35000
    assert relation_delay()["holds"] is True


# ------------------------------------------------------- R2, infra_error rows

INFRA_HOLDS = {"a": True, "b": True, "c": False}


@pytest.mark.parametrize("build", BUILD_NAMES)
def test_r2_infra_rows_do_not_move_the_pass_rate(build):
    """Adding infra_error trials must not change any rate: they are not shape decisions."""
    fixture = _fixture("metamorphic_infra.json")
    before = _stats(build, fixture["a"])
    after = _stats(build, fixture["b"])
    if INFRA_HOLDS[build]:
        assert after["pass_rate"] == before["pass_rate"]
        assert after["graded_trials"] == before["graded_trials"] == 12
        assert after["successes"] == before["successes"]
        assert after["mean_steps"] == before["mean_steps"]
    else:
        # The deviating build grades the 4 infra rows as failures.
        assert before["pass_rate"] == pytest.approx(0.75)
        assert after["pass_rate"] == pytest.approx(0.5625)
        assert after["graded_trials"] == 16
        assert after["successes"] == before["successes"] == 9


# --------------------------------------------------- R3, duplicated trial list

DUPLICATE_HOLDS = {"a": False, "b": True, "c": True}


@pytest.mark.parametrize("build", BUILD_NAMES)
def test_r3_duplicating_the_list_keeps_rates_and_doubles_totals(build):
    fixture = _fixture("metamorphic_duplicate.json")
    before = _stats(build, fixture["a"])
    after = _stats(build, fixture["b"])
    assert after["pass_rate"] == before["pass_rate"]
    assert after["seed_pass_rates"] == before["seed_pass_rates"]
    assert after["mean_steps"] == before["mean_steps"]
    assert after["trials"] == 2 * before["trials"]
    assert after["successes"] == 2 * before["successes"]
    if DUPLICATE_HOLDS[build]:
        assert after["cost_per_success_vnd"] == pytest.approx(before["cost_per_success_vnd"])
        assert after["total_simulated_cost_vnd"] == pytest.approx(2 * before["total_simulated_cost_vnd"])
    else:
        # The deviating build adds the first row's cost per claim a second time,
        # so its totals do not double and its cost per success moves under a
        # transformation that only duplicates rows.
        assert before["cost_per_success_vnd"] == pytest.approx(31.5)
        assert after["cost_per_success_vnd"] == pytest.approx(26.27777777777778)
        assert before["total_simulated_cost_vnd"] == pytest.approx(283.5)
        assert after["total_simulated_cost_vnd"] == pytest.approx(473.0)
        assert after["total_simulated_cost_vnd"] != pytest.approx(2 * before["total_simulated_cost_vnd"])


def test_r3b_pass5_is_not_invariant_under_duplication():
    """The README lists pass_5 among the invariant rates. It is not, for any build.

    pass_5 requires exactly one row per seed, so duplicating the list breaks its
    precondition. The relation is over-strong as written; the defect is in the
    relation, not in a build, and this test pins that down instead of blaming one.
    """
    fixture = _fixture("metamorphic_duplicate.json")
    for build in BUILD_NAMES:
        before = _stats(build, fixture["a"])
        after = _stats(build, fixture["b"])
        assert before["pass_5"] == pytest.approx(2 / 3)
        assert after["pass_5"] == 0.0
    assert all(row["holds"] is False for row in relation_pass5_under_duplication()["builds"])


# --------------------------------------------- R4 (ours), single-trial identity

IDENTITY_HOLDS = {"a": False, "b": True, "c": True}


@pytest.mark.parametrize("build", BUILD_NAMES)
def test_r4_single_trial_reports_its_own_cost(build):
    """A list with one graded trial has nothing to double-count against.

    R2 and R3 both scale the whole list, so a metric that quietly adds cost stays
    invisible to them. This relation is the one that catches it.
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
    stats = _stats(build, [trial])
    assert stats["mean_steps"] == 3
    if IDENTITY_HOLDS[build]:
        assert stats["total_simulated_cost_vnd"] == pytest.approx(12.0)
        assert stats["cost_per_success_vnd"] == pytest.approx(12.0)
    else:
        assert stats["total_simulated_cost_vnd"] == pytest.approx(24.0)
        assert stats["cost_per_success_vnd"] == pytest.approx(24.0)


# ------------------------------------------------------------------- verdict


def test_exactly_one_build_is_consistent_with_every_relation():
    """The audit's conclusion, computed from the relations rather than asserted by hand."""
    report = run()
    assert report["consistent_builds"] == ["b"]
    assert report["verdict"]["b"]["consistent"] is True
    assert report["verdict"]["a"]["consistent"] is False
    assert report["verdict"]["c"]["consistent"] is False
    # Each build is named by the behaviour that gives it away, not by its letter.
    assert report["verdict"]["a"]["checks"]["single_trial_reports_its_own_cost"] is False
    assert report["verdict"]["c"]["checks"]["infra_errors_do_not_move_pass_rate"] is False


def test_report_file_matches_a_fresh_run():
    """reports/bonus_grader_audit.json is generated, never edited by hand."""
    path = Path("reports") / "bonus_grader_audit.json"
    assert path.is_file(), "run: python -m bonus.grader_audit_report"
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    fresh = run()
    assert on_disk["consistent_builds"] == fresh["consistent_builds"]
    assert on_disk["verdict"] == fresh["verdict"]
