#!/usr/bin/env python3
"""Runnable recursive-delta demo — no GPU, no API keys.

Builds a two-rung ladder (local + cloud) with a deterministic stub runner where
the local tier passes only 'easy' tasks, streams a cold policy over the archetype
tags, and prints the cumulative learning curve: cost/task falls, local-served
share rises as the router learns which regions the local tier can clear.

    uv run python scripts/run_demo.py
"""

from __future__ import annotations

import random
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sift.experiment import run_learning_experiment
from sift.harness import EvaluationResult, HarnessRun, TaskSpec
from sift.router import Ladder, Policy, Router, Rung


@dataclass
class StubProvider:
    name: str
    model: str = "stub"


class StubRunner:
    """Local passes 'easy' tasks for free; cloud passes everything at a price."""

    COSTS = {"local": 0.0, "cloud": 0.02}

    def run_task(self, task: TaskSpec, provider) -> HarnessRun:
        passed = provider.name == "cloud" or "easy" in task.tags
        return HarnessRun(
            task_id=task.id,
            provider=provider.name,
            model=provider.model,
            response="ok" if passed else "no",
            evaluation=EvaluationResult(task.id, passed, 0 if passed else 1, "", ""),
            cost_usd=self.COSTS[provider.name],
        )


def _demo_tasks() -> list[TaskSpec]:
    tags = [("easy", "regex"), ("easy", "docstring"), ("easy", "rename"),
            ("hard", "refactor"), ("hard", "algorithms")]
    return [
        TaskSpec(id=f"{t[0]}-{t[1]}-{i}", prompt="p", check_command="true", tags=t)
        for t in tags
        for i in range(4)
    ]


def main() -> None:
    ladder = Ladder([
        Rung("local", StubProvider("local"), is_local=True),
        Rung("cloud", StubProvider("cloud")),
    ])
    tasks = _demo_tasks()
    cloud_cost = StubRunner.COSTS["cloud"]  # always-cloud baseline: every task pays this

    router = Router(ladder, StubRunner(), policy=Policy(bar=0.5), rng=random.Random(7))
    series = run_learning_experiment(tasks, router, rounds=10)

    print("sift — recursive-delta demo (stub ladder: local $0 / cloud $%.2f)\n" % cloud_cost)
    print(f"{'round':>6} {'cost/task':>11} {'vs cloud':>9} {'local':>7} {'rungs':>7}")
    for m in series:
        savings = 1 - (m.avg_cost_usd / cloud_cost) if cloud_cost else 0.0
        print(f"{m.round:>6} {m.avg_cost_usd:>10.5f}$ {savings:>8.0%} "
              f"{m.local_served_frac:>6.0%} {m.avg_rungs:>7.2f}")

    warm = series[-1]
    warm_savings = 1 - (warm.avg_cost_usd / cloud_cost)
    print(
        f"\nbaseline always-cloud: ${cloud_cost:.5f}/task, 0% local\n"
        f"sift warm:             ${warm.avg_cost_usd:.5f}/task, "
        f"{warm.local_served_frac:.0%} local  "
        f"→  {warm_savings:.0%} cheaper, pass-rate {warm.pass_rate:.0%}\n"
        "\n(Stub converges fast — 5 tiny regions. On the real archetype suite with\n"
        " diverse regions + real tier prices, the cold→warm ramp is pronounced.)"
    )


if __name__ == "__main__":
    main()
