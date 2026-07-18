"""The learning router: entry-hop tier selection + oracle-gated fail-up.

sift routes each task to the cheapest rung of a cost/capability-ordered ladder
that clears the executable oracle, and *learns* — per feature region — which
rung to enter at, so cost falls and local-served share rises over runs.

This module is deliberately minimal and swappable:

* ``region_of`` is the feature function. For the MVP it keys on task tags; the
  design target is a local-model hidden-state embedding. Swap this one function.
* ``Policy`` holds per ``(region, tier)`` Beta posteriors over oracle-pass and
  selects an entry rung by Thompson sampling (explores when cold, exploits when
  warm). The design target is an expected-cost-minimizing entry over a monotone
  difficulty threshold; the Thompson rule is the shippable stand-in.
* ``Router`` drives entry + fail-up against any runner exposing
  ``run_task(task, provider) -> HarnessRun`` (``Harness`` satisfies it).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Protocol

from sift.harness import HarnessRun, Provider, TaskSpec


class Runner(Protocol):
    """Anything that can execute one task on one provider. ``Harness`` fits."""

    def run_task(self, task: TaskSpec, provider: Provider) -> HarnessRun: ...


@dataclass(frozen=True)
class Rung:
    """One rung of the routing ladder."""

    name: str
    provider: Provider
    is_local: bool = False


@dataclass
class Ladder:
    """Cost/capability-ordered rungs, cheapest first."""

    rungs: list[Rung]

    def __post_init__(self) -> None:
        if not self.rungs:
            raise ValueError("Ladder needs at least one rung")

    def __len__(self) -> int:
        return len(self.rungs)


def region_of(task: TaskSpec) -> str:
    """Feature region for a task.

    MVP: the task's tag set. This is the single swap point for hidden-state
    features — replace with an embedding bucket without touching the policy.
    """
    return ",".join(sorted(task.tags)) or "_untagged"


@dataclass
class TierStats:
    """Beta(1+passes, 1+fails) posterior over oracle-pass for a (region, tier)."""

    passes: int = 0
    fails: int = 0

    def sample(self, rng: random.Random) -> float:
        return rng.betavariate(1 + self.passes, 1 + self.fails)

    def mean(self) -> float:
        return (1 + self.passes) / (2 + self.passes + self.fails)

    def observe(self, passed: bool) -> None:
        if passed:
            self.passes += 1
        else:
            self.fails += 1


@dataclass
class Policy:
    """Per-region, per-tier pass posteriors + Thompson entry selection."""

    bar: float = 0.5
    stats: dict[tuple[str, str], TierStats] = field(default_factory=dict)

    def stats_for(self, region: str, tier: str) -> TierStats:
        return self.stats.setdefault((region, tier), TierStats())

    def entry_index(self, region: str, ladder: Ladder, rng: random.Random) -> int:
        """Lowest rung whose *sampled* pass-prob clears the bar (else the top).

        Cold: posteriors are wide, so samples scatter and low rungs get probed
        (exploration). Warm: posteriors tighten, so entry converges to the
        cheapest rung that reliably passes (exploitation) — no epsilon to tune.
        """
        for index, rung in enumerate(ladder.rungs):
            if self.stats_for(region, rung.name).sample(rng) >= self.bar:
                return index
        return len(ladder) - 1

    def observe(self, region: str, tier: str, passed: bool) -> None:
        self.stats_for(region, tier).observe(passed)


@dataclass(frozen=True)
class RouteResult:
    task_id: str
    region: str
    rungs_tried: tuple[str, ...]
    final_rung: str | None
    passed: bool
    cost_usd: float
    served_local: bool
    runs: tuple[HarnessRun, ...]


class Router:
    def __init__(
        self,
        ladder: Ladder,
        runner: Runner,
        *,
        policy: Policy | None = None,
        rng: random.Random | None = None,
    ):
        self.ladder = ladder
        self.runner = runner
        self.policy = policy or Policy()
        self.rng = rng or random.Random()

    def route(self, task: TaskSpec) -> RouteResult:
        """Enter at the policy's chosen rung, fail up until the oracle passes."""
        region = region_of(task)
        start = self.policy.entry_index(region, self.ladder, self.rng)

        tried: list[str] = []
        runs: list[HarnessRun] = []
        total_cost = 0.0
        passed = False
        final: str | None = None
        served_local = False

        for rung in self.ladder.rungs[start:]:
            run = self.runner.run_task(task, rung.provider)
            runs.append(run)
            tried.append(rung.name)
            total_cost += run.cost_usd
            self.policy.observe(region, rung.name, run.evaluation.passed)
            if run.evaluation.passed:
                passed = True
                final = rung.name
                served_local = rung.is_local
                break

        return RouteResult(
            task_id=task.id,
            region=region,
            rungs_tried=tuple(tried),
            final_rung=final,
            passed=passed,
            cost_usd=total_cost,
            served_local=served_local,
            runs=tuple(runs),
        )
