"""The Claw Agent: a heartbeat daemon that sharpens sift's policy over time.

A Claw Agent is proactively autonomous, heartbeat-driven (wakes on a timer, not
a prompt), and persistent with context. This wraps the learning ``Router`` in
exactly that loop:

* **Heartbeat** — ``run()`` ticks on ``interval_s``; each ``tick()`` runs a
  budget-capped *proactive exploration* round (route a sample of the task pool),
  which is where the "who pays for exploration?" answer lives: it happens off the
  user's critical path so the policy is already sharp when real traffic arrives.
* **Persistent with context** — learned policy state is checkpointed to disk
  after every heartbeat and reloaded on startup, so an interrupted agent resumes
  where it left off. (Swap ``state_path`` JSON for Supabase later.)
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sift.harness import TaskSpec
from sift.router import RouteResult, Router
from sift.state import JsonStateStore, StateStore


@dataclass(frozen=True)
class HeartbeatReport:
    tick: int
    probed: int
    avg_cost_usd: float
    pass_rate: float
    local_served_frac: float
    avg_rungs: float


class HeartbeatAgent:
    def __init__(
        self,
        router: Router,
        task_pool: list[TaskSpec],
        *,
        state_path: str | Path | None = None,
        state_store: StateStore | None = None,
        probe_size: int = 8,
        interval_s: float = 30.0,
        sleep_fn: Callable[[float], None] = time.sleep,
    ):
        if state_store is None:
            if state_path is None:
                raise ValueError("provide state_store or state_path")
            state_store = JsonStateStore(state_path)
        self.router = router
        self.task_pool = list(task_pool)
        self.store = state_store
        self.probe_size = probe_size
        self.interval_s = interval_s
        self._sleep = sleep_fn
        self.tick_count = 0
        self.load_state()  # recover from a prior (possibly interrupted) run

    # -- the heartbeat -------------------------------------------------------

    def tick(self) -> HeartbeatReport:
        """One heartbeat: proactively probe the task pool, then checkpoint."""
        k = min(self.probe_size, len(self.task_pool))
        sample = self.router.rng.sample(self.task_pool, k) if k else []
        results = [self.router.route(task) for task in sample]
        self.tick_count += 1
        self.save_state()
        return self._report(results)

    def run(self, max_ticks: int | None = None) -> list[HeartbeatReport]:
        """Loop forever (or ``max_ticks`` times), sleeping ``interval_s`` between wakes."""
        reports: list[HeartbeatReport] = []
        while True:
            reports.append(self.tick())
            if max_ticks is not None and len(reports) >= max_ticks:
                break
            self._sleep(self.interval_s)
        return reports

    # -- persistence ---------------------------------------------------------

    def save_state(self) -> None:
        records = [
            {"region": region, "tier": tier, "passes": s.passes, "fails": s.fails}
            for (region, tier), s in self.router.policy.stats.items()
        ]
        try:
            self.store.save({"tick": self.tick_count, "stats": records})
        except Exception as exc:  # noqa: BLE001 — a flaky store must not kill the heartbeat
            print(f"[state] checkpoint failed ({type(exc).__name__}: {exc}) — continuing")

    def load_state(self) -> None:
        try:
            data = self.store.load()
        except Exception as exc:  # noqa: BLE001 — resume fresh rather than crash on startup
            print(f"[state] load failed ({type(exc).__name__}: {exc}) — starting fresh")
            return
        if not data:
            return
        self.tick_count = int(data.get("tick", 0))
        for record in data.get("stats", []):
            stats = self.router.policy.stats_for(record["region"], record["tier"])
            stats.passes = int(record["passes"])
            stats.fails = int(record["fails"])

    # -- helpers -------------------------------------------------------------

    def _report(self, results: list[RouteResult]) -> HeartbeatReport:
        n = len(results)
        if n == 0:
            return HeartbeatReport(self.tick_count, 0, 0.0, 0.0, 0.0, 0.0)
        return HeartbeatReport(
            tick=self.tick_count,
            probed=n,
            avg_cost_usd=sum(r.cost_usd for r in results) / n,
            pass_rate=sum(r.passed for r in results) / n,
            local_served_frac=sum(r.served_local for r in results) / n,
            avg_rungs=sum(len(r.rungs_tried) for r in results) / n,
        )
