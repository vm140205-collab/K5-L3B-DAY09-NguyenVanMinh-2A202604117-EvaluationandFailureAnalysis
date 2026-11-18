"""M3/M4 regression tests for the trace cases in docs/trace_case.md.

Each test runs one trial on a fresh store (no team DB, no shared state), so it is a real
end-to-end assertion: the shape runs, the ledger is written, the graders score it.
"""
import pytest

pytestmark = pytest.mark.student

from lab9 import graders, trace_case  # noqa: E402


def first_wrong_kind(trial, kinds=("model_override",)):
    for i, event in enumerate(trial["events"], 1):
        if event.get("kind") in kinds:
            return i, event.get("kind"), event.get("payload")
    return None, None, None


def test_fm03_model_override_is_the_first_wrong_step():
    bad = trace_case.investigate("trace:ticket_trust", "C-002", 11, bugs="ticket_trust")["trial"]
    good = trace_case.investigate("fixed", "C-002", 11)["trial"]

    # the buggy run rewrote the DB fact, the fixed run did not
    step, kind, payload = first_wrong_kind(bad)
    assert (step, kind) == (3, "model_override"), "FM-03 first shows up at event 3, not later"
    assert payload["delay_days"] == 5 and bad["snapshot"]["refund_vnd"] == 20000
    assert first_wrong_kind(good)[0] is None
    assert good["snapshot"]["refund_vnd"] == 0


def test_fm03_db_fact_grader_separates_bug_from_fix():
    from pydantic_evals.evaluators import EvaluatorContext

    def ctx(trial):
        return EvaluatorContext(name="t", inputs={}, metadata=None,
                                expected_output={"refund_vnd": 0, "approval_ok": True},
                                output=trial, duration=0.0, _span_tree=None, attributes={}, metrics={})

    bad = trace_case.investigate("trace:ticket_trust", "C-002", 11, bugs="ticket_trust")["trial"]
    good = trace_case.investigate("fixed", "C-002", 11)["trial"]
    assert graders.DbFactKept().evaluate(ctx(bad)).value is False
    assert graders.RefundAmountCorrect().evaluate(ctx(bad)).value is False
    assert graders.DbFactKept().evaluate(ctx(good)).value is True


def test_fm08_reply_amount_must_match_the_ledger():
    from pydantic_evals.evaluators import EvaluatorContext

    def ctx(trial, label):
        return EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=label,
                                output=trial, duration=0.0, _span_tree=None, attributes={}, metrics={})

    label = {"refund_vnd": 20000, "approval_ok": True}
    bad = trace_case.investigate("trace:misreport", "C-008", 11, bugs="misreport")["trial"]
    good = trace_case.investigate("fixed", "C-008", 11)["trial"]

    assert graders.ReplyLedgerMatch().evaluate(ctx(bad, label)).value is False
    assert graders.ReplyLedgerMatch().evaluate(ctx(good, label)).value is True
    # this is the reason the metric exists: Lab 8's own grader passes a lying reply
    assert graders.TrialPass().evaluate(ctx(bad, label)).value is True


def test_fm02_missing_policy_denied_audit_is_flagged():
    """The host must leave a policy_denied row when it refuses a quote > 0; a shape that says
    "denied" on its own leaves none, and only this grader explains why pass_rate went red."""
    from pydantic_evals.evaluators import EvaluatorContext

    label = {"refund_vnd": 0, "proposal_amount": 35000, "policy_denied": True, "approval_ok": True}

    def ctx(trial):
        return EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=label,
                                output=trial, duration=0.0, _span_tree=None, attributes={}, metrics={})

    trial = trace_case.investigate("trace:pre_deducted", "C-013", 11, bugs="pre_deducted,ignore_denied")["trial"]
    assert trial["snapshot"]["refund_vnd"] == 0                    # the money looks fine ...
    assert graders.RefundAmountCorrect().evaluate(ctx(trial)).value is True
    assert graders.PolicyDeniedRecorded().evaluate(ctx(trial)).value is False   # ... the audit does not
