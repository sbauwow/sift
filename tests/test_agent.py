from __future__ import annotations

import random
from dataclasses import dataclass

from sift.agent import HeartbeatAgent
from sift.harness import EvaluationResult, HarnessRun, TaskSpec
from sift.router import Ladder, Policy, Router, Rung


@dataclass
class StubProvider:
    name: str
    model: str = "stub"


class StubRunner:
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


def _router(seed: int = 0) -> Router:
    ladder = Ladder([
        Rung("local", StubProvider("local"), is_local=True),
        Rung("cloud", StubProvider("cloud")),
    ])
    return Router(ladder, StubRunner(), policy=Policy(), rng=random.Random(seed))


def _tasks() -> list[TaskSpec]:
    return [
        TaskSpec(id=f"e{i}", prompt="p", check_command="true", tags=("easy",))
        for i in range(8)
    ] + [
        TaskSpec(id=f"h{i}", prompt="p", check_command="true", tags=("hard",))
        for i in range(2)
    ]


class RecordingSleep:
    def __init__(self):
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def test_tick_probes_and_checkpoints(tmp_path):
    state = tmp_path / "state.json"
    agent = HeartbeatAgent(_router(), _tasks(), state_path=state, probe_size=6)
    report = agent.tick()
    assert report.tick == 1
    assert report.probed == 6
    assert state.exists()  # checkpoint written


def test_run_sleeps_between_ticks_not_after_last(tmp_path):
    sleep = RecordingSleep()
    agent = HeartbeatAgent(
        _router(), _tasks(), state_path=tmp_path / "s.json",
        probe_size=4, interval_s=15.0, sleep_fn=sleep,
    )
    reports = agent.run(max_ticks=3)
    assert [r.tick for r in reports] == [1, 2, 3]
    assert sleep.calls == [15.0, 15.0]  # slept twice, not after the final tick


def test_state_persists_and_recovers_across_restart(tmp_path):
    state = tmp_path / "state.json"
    agent = HeartbeatAgent(
        _router(seed=1), _tasks(), state_path=state, probe_size=10,
        sleep_fn=lambda _: None,
    )
    agent.run(max_ticks=5)
    saved_tick = agent.tick_count
    trained = dict(agent.router.policy.stats)
    assert saved_tick == 5

    # A fresh agent on the same state file resumes — recovers from interruption.
    resumed = HeartbeatAgent(
        _router(seed=2), _tasks(), state_path=state, probe_size=10,
        sleep_fn=lambda _: None,
    )
    assert resumed.tick_count == 5
    assert resumed.router.policy.stats == trained


def test_heartbeat_sharpens_policy_toward_local(tmp_path):
    agent = HeartbeatAgent(
        _router(seed=3), _tasks(), state_path=tmp_path / "s.json", probe_size=10,
        sleep_fn=lambda _: None,
    )
    reports = agent.run(max_ticks=15)
    # By the end, the easy majority (8/10) rides the local tier without prompting.
    assert reports[-1].local_served_frac >= 0.7
    assert reports[-1].pass_rate == 1.0
