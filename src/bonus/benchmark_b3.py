"""B3 — measure swarm vs swarm_verified vs workflow on the same claims and seeds.

Run from `src/`:

    python -m bonus.benchmark_b3

Writes `reports/bonus_b3.json`. Every number in the bonus report comes from this
file; nothing is copied from a terminal.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lab8.benchmark import register_extra_shapes, run_benchmark
from lab8.db import load_json, load_jsonl

SEEDS = [11, 22, 33, 44, 55]
SHAPES = ["workflow", "swarm", "swarm_verified"]
OUT = Path("reports") / "bonus_b3.json"
TRACES = Path("traces")


def _interventions(report: dict[str, Any]) -> dict[str, Any]:
    """Count verifier_override events straight out of the traces of this run."""
    overridden = []
    total = 0
    for trial in report["trials"]:
        if trial["shape"] != "swarm_verified":
            continue
        total += 1
        path = TRACES / f"{trial['run_id']}.json"
        if not path.is_file():
            continue
        body = json.loads(path.read_text(encoding="utf-8"))
        for event in body.get("events", []):
            if event.get("kind") == "verifier_override":
                overridden.append(
                    {
                        "claim_id": trial["claim_id"],
                        "seed": trial["seed"],
                        "passed": trial["passed"],
                        **event["payload"],
                    }
                )
                break
    return {"trials": total, "interventions": len(overridden), "detail": overridden}


def _suite(name: str, world_path: str, cases_path: str) -> dict[str, Any]:
    report = run_benchmark(
        world=load_json(world_path),
        claims=load_jsonl(cases_path),
        shapes=SHAPES,
        seeds=SEEDS,
    )
    return {
        "suite": name,
        "cases": cases_path,
        "seeds": SEEDS,
        "by_shape": {
            shape: {
                key: stats[key]
                for key in (
                    "pass_rate",
                    "pass_5",
                    "seed_min",
                    "seed_max",
                    "seed_variance",
                    "cost_per_success_vnd",
                    "total_simulated_cost_vnd",
                    "mean_steps",
                    "mean_model_calls",
                    "mean_tool_calls",
                    "reasons",
                )
            }
            for shape, stats in report["by_shape"].items()
        },
        "verifier": _interventions(report),
        "trials": report["trials"],
    }


def main() -> None:
    register_extra_shapes(["swarm_verified=bonus.swarm_verified:run_claim"])
    report = {
        "topic": "B3",
        "command": "python -m bonus.benchmark_b3",
        "controlled_variables": {
            "model_backend": "MockLLM",
            "seeds": SEEDS,
            "pricing": "config/pricing.yaml",
            "latency": "unavailable",
            "isolation": "fresh_sqlite_per_trial",
            "changed_variable": "verifier step before issue_refund (on/off)",
        },
        "suites": [
            _suite("public", "data/public_world_state.json", "data/public_claims.jsonl"),
            _suite("adversarial", "bonus/world.json", "bonus/cases.jsonl"),
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    header = f"{'suite':<12} {'shape':<16} {'pass':>7} {'pass^5':>7} {'var':>10} {'cost/success':>13} {'steps':>7}"
    print(header)
    print("-" * len(header))
    for suite in report["suites"]:
        for shape, stats in suite["by_shape"].items():
            cost = "-" if stats["cost_per_success_vnd"] is None else f"{stats['cost_per_success_vnd']:.2f}"
            print(
                f"{suite['suite']:<12} {shape:<16} {stats['pass_rate']:>7.3f} {stats['pass_5']:>7.3f} "
                f"{stats['seed_variance']:>10.6f} {cost:>13} {stats['mean_steps']:>7.2f}"
            )
        verifier = suite["verifier"]
        print(f"{'':<12} verifier can thiệp {verifier['interventions']}/{verifier['trials']} trial")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
