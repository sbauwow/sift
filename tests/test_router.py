from __future__ import annotations

import random
from dataclasses import dataclass

from sift.harness import EvaluationResult, HarnessRun, TaskSpec
from sift.router import Ladder, Policy, Router, Rung, TierStats, region_of


@dataclass
class FakeProvider:
    name: str
    model: str = "fake"


class FakeRunner:
    """Deterministic stand-in for Harness: local passes only 'easy' tasks."""

    COSTS = {"local": 0.0, "cloud": 0.02}

    def run_task(self, task: TaskSpec, provider) -> HarnessRun:
        passed = provider.name == "cloud" or "easy" in task.tags
        return HarnessRun(
            task_id=task.id,
            provider=provider.name,
            model=provider.model,
            response="ok" if passed else "no",
            evaluation=EvaluationResult(
                task_id=task.id,
                passed=passed,
                exit_code=0 if passed else 1,
                stdout="",
                stderr="",
            ),
            cost_usd=self.COSTS[provider.name],
        )


def _ladder() -> Ladder:
    return Ladder(
        [
            Rung("local", FakeProvider("local"), is_local=True),
            Rung("cloud", FakeProvider("cloud")),
        ]
    )


def test_region_of_uses_sorted_tags():
    task = TaskSpec(id="t", prompt="p", check_command="true", tags=("b", "a"))
    assert region_of(task) == "a,b"
    assert region_of(TaskSpec(id="t", prompt="p", check_command="true")) == "_untagged"


def test_tier_stats_posterior_moves_with_evidence():
    s = TierStats()
    assert abs(s.mean() - 0.5) < 1e-9
    for _ in range(10):
        s.observe(True)
    assert s.mean() > 0.8


def test_hard_task_fails_up_to_cloud():
    hard = TaskSpec(id="h", prompt="p", check_command="true", tags=("hard",))
    router = Router(_ladder(), FakeRunner(), rng=random.Random(0))
    # Force entry at the bottom so we exercise the climb.
    router.policy.stats_for("hard", "local").passes = 5  # optimistic -> enter local
    result = router.route(hard)
    assert result.rungs_tried == ("local", "cloud")
    assert result.final_rung == "cloud"
    assert result.passed is True
    assert result.served_local is False
    assert result.cost_usd == FakeRunner.COSTS["cloud"]


def test_easy_task_can_be_served_local():
    easy = TaskSpec(id="e", prompt="p", check_command="true", tags=("easy",))
    router = Router(_ladder(), FakeRunner(), rng=random.Random(0))
    router.policy.stats_for("easy", "local").passes = 20  # warm -> enter local
    result = router.route(easy)
    assert result.rungs_tried == ("local",)
    assert result.served_local is True
    assert result.cost_usd == 0.0


def test_policy_entry_shifts_toward_local_with_evidence():
    """The learning mechanism: passes in a region pull entry down to local."""
    ladder = _ladder()
    rng = random.Random(0)

    cold = Policy(bar=0.5)
    cold_local = sum(cold.entry_index("easy", ladder, rng) == 0 for _ in range(200))

    warm = Policy(bar=0.5)
    for _ in range(30):
        warm.observe("easy", "local", True)
    warm_local = sum(warm.entry_index("easy", ladder, rng) == 0 for _ in range(200))

    # Cold explores (enters local ~half the time); warm exploits (nearly always).
    assert warm_local > cold_local
    assert warm_local >= 190


def test_experiment_loop_converges_to_local_for_easy_majority():
    from sift.experiment import run_learning_experiment

    tasks = [
        TaskSpec(id=f"e{i}", prompt="p", check_command="true", tags=("easy",))
        for i in range(16)
    ] + [
        TaskSpec(id=f"h{i}", prompt="p", check_command="true", tags=("hard",))
        for i in range(4)
    ]
    router = Router(_ladder(), FakeRunner(), policy=Policy(), rng=random.Random(1))
    series = run_learning_experiment(tasks, router, rounds=12)

    assert len(series) == 12
    last = series[-1]
    # Everything clears the oracle (at cloud if nowhere cheaper); warm state
    # routes the easy majority (16/20) to the local tier at near-1 rung.
    assert last.pass_rate == 1.0
    assert last.local_served_frac >= 0.75
    assert last.avg_rungs <= 1.15
    # Hard tasks (4/20) are the only cloud spend: 4 * $0.02 / 20 = $0.004.
    assert last.avg_cost_usd <= 0.005


def test_empty_ladder_rejected():
    import pytest

    with pytest.raises(ValueError):
        Ladder([])
