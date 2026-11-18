"""Extra gate vectors for M7 (my own, on top of tests/test_lab9_advanced.py).

Every case here is a report or spec that a motivated engineer could hand the gate. The gate must
refuse it, and the one case it must NOT refuse (the baseline against itself) is in the list too --
an integrity check that blocks everything is as useless as one that blocks nothing.
"""
import copy
import json
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.student

BASE = Path("reports/baseline_v2.json")
SPEC = Path("config/metric_spec_v2.yaml")


@pytest.fixture(scope="module")
def artifacts():
    return json.loads(BASE.read_text(encoding="utf-8")), yaml.safe_load(SPEC.read_text(encoding="utf-8"))


def test_baseline_against_itself_merges(artifacts):
    from lab9 import gate

    base, spec = artifacts
    assert gate.integrity_check(base, base, spec, spec) == []
    blocked, _ = gate.check(base, base, spec, spec)
    assert blocked == [], "an unchanged run must not be blocked"


def test_duplicate_row_hidden_by_a_dropped_row_is_blocked(artifacts):
    from lab9 import gate

    base, spec = artifacts
    pr = copy.deepcopy(base)
    pr["rows"] = pr["rows"][:-1] + [copy.deepcopy(pr["rows"][0])]
    problems = gate.integrity_check(pr, base, spec, spec)
    assert any("duplicate" in p or "pair" in p for p in problems), problems


def test_evaluator_failures_on_a_green_report_are_blocked(artifacts):
    from lab9 import gate

    base, spec = artifacts
    pr = copy.deepcopy(base)
    assert pr["metrics"]["pass_rate"] > 0.9          # the numbers look fine ...
    pr["evaluator_failures"] = ["E-014@33:ReplyLedgerMatch:boom"]  # ... but a grader crashed
    assert any("evaluator failure" in p for p in gate.integrity_check(pr, base, spec, spec))


def test_relabelled_slice_tags_are_blocked(artifacts):
    from lab9 import gate

    base, spec = artifacts
    pr = copy.deepcopy(base)
    victim = next(r for r in pr["rows"] if "money_movement" in r["slices"])
    victim["slices"] = [s for s in victim["slices"] if s != "money_movement"]
    assert any("slice tags changed" in p for p in gate.integrity_check(pr, base, spec, spec))


def test_ratchet_refuses_every_way_to_switch_a_gate_off(artifacts):
    from lab9 import gate

    _, spec = artifacts
    for mutate in (
        lambda s: s["metrics"][0]["threshold"].update(max=5),                 # max raised
        lambda s: s["metrics"][5]["threshold"].update(min=0.5),               # min lowered
        lambda s: s["metrics"][5].update(blocking=False),                     # no longer blocking
        lambda s: s["metrics"].pop(6),                                        # metric removed
        lambda s: s.update(slices=[x for x in s["slices"] if x["name"] != "money_movement"]),
        lambda s: s["slices"][1].pop("no_significant_drop"),
        lambda s: s["slices"][2].update(min=0.5),
    ):
        loose = copy.deepcopy(spec)
        mutate(loose)
        assert gate.integrity_check(base_report(), base_report(), loose, spec), loose


def test_pass_hat_5_floor_is_outside_the_aa_band_and_at_least_0_8(artifacts):
    _, spec = artifacts
    floor = next(m for m in spec["metrics"] if m["id"] == "pass_hat_5")["threshold"]["min"]
    assert floor >= 0.8
    # A/A on MockLLM is exactly 0 for every metric, so any floor at all is outside the band;
    # the floor must still sit below the reference baseline and above a 1-in-5-seed bug.
    assert floor < 0.8929 and floor > 0.5714


def base_report():
    return json.loads(BASE.read_text(encoding="utf-8"))
