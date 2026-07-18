"""The recursive-delta loop: run the suite over rounds, watch the router learn.

Produces the headline curves for the Recursive Intelligence track — average
cost per task falling and local-served fraction rising as the policy sharpens,
run over run, off a single persistent ``Router`` (its ``Policy`` accumulates).
"""

from __future__ import annotations

from dataclasses import dataclass

from sift.harness import TaskSpec
from sift.router import RouteResult, Router


@dataclass(frozen=True)
class RoundMetrics:
    round: int
    tasks: int
    avg_cost_usd: float
    pass_rate: float
    local_served_frac: float
    avg_rungs: float

    def as_row(self) -> str:
        return (
            f"round {self.round:>2}  "
            f"cost/task ${self.avg_cost_usd:.5f}  "
            f"pass {self.pass_rate:6.1%}  "
            f"local {self.local_served_frac:6.1%}  "
            f"rungs {self.avg_rungs:.2f}"
        )


def _summarize(round_index: int, results: list[RouteResult]) -> RoundMetrics:
    n = len(results)
    if n == 0:
        return RoundMetrics(round_index, 0, 0.0, 0.0, 0.0, 0.0)
    return RoundMetrics(
        round=round_index,
        tasks=n,
        avg_cost_usd=sum(r.cost_usd for r in results) / n,
        pass_rate=sum(r.passed for r in results) / n,
        local_served_frac=sum(r.served_local for r in results) / n,
        avg_rungs=sum(len(r.rungs_tried) for r in results) / n,
    )


def run_learning_experiment(
    tasks: list[TaskSpec],
    router: Router,
    *,
    rounds: int,
    shuffle: bool = True,
) -> list[RoundMetrics]:
    """Route every task each round; return per-round metrics as the delta series.

    The same ``router`` (and its ``Policy``) is reused across rounds, so learning
    compounds: round 0 over-provisions/explores, later rounds route right.
    """
    series: list[RoundMetrics] = []
    order = list(tasks)
    for round_index in range(rounds):
        if shuffle:
            router.rng.shuffle(order)
        results = [router.route(task) for task in order]
        series.append(_summarize(round_index, results))
    return series


@dataclass(frozen=True)
class StreamPoint:
    step: int
    cum_avg_cost_usd: float
    cum_local_served_frac: float
    cum_avg_rungs: float


def run_cold_stream(
    tasks: list[TaskSpec],
    router: Router,
    *,
    steps: int,
) -> list[StreamPoint]:
    """Route a shuffled, repeating stream of tasks from a *cold* policy.

    Returns cumulative metrics after each decision — the smooth learning curve
    for the demo. Early steps explore (cost high, local low); as the policy
    warms, cumulative cost bends down and local-served share bends up. Robust
    to region granularity, unlike the per-round view.
    """
    points: list[StreamPoint] = []
    cost_sum = 0.0
    local_sum = 0
    rungs_sum = 0
    for step in range(1, steps + 1):
        task = router.rng.choice(tasks)
        result = router.route(task)
        cost_sum += result.cost_usd
        local_sum += int(result.served_local)
        rungs_sum += len(result.rungs_tried)
        points.append(
            StreamPoint(
                step=step,
                cum_avg_cost_usd=cost_sum / step,
                cum_local_served_frac=local_sum / step,
                cum_avg_rungs=rungs_sum / step,
            )
        )
    return points
