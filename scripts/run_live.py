#!/usr/bin/env python3
"""End-to-end live run: route the real task suite through the learning router.

    ANTHROPIC_API_KEY=... SIFT_LOCAL_ENDPOINT=http://gpu:8000/v1/chat/completions \
        uv run python scripts/run_live.py

Wires the real ladder (local Nemotron on vLLM + configured Claude tiers),
optional HiddenLayer scanning, and the OpenShell sandbox (SIFT_SANDBOX=openshell),
then runs the suite over SIFT_ROUNDS rounds and prints the recursive delta.

Unconfigured rungs (no API key) are dropped, so it runs local-only if that's all
that's up — hard tasks simply fail at the local tier, which the numbers show.
"""

from __future__ import annotations

import os
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sift.config import default_ladder
from sift.experiment import run_learning_experiment
from sift.harness import Harness, load_tasks
from sift.router import Ladder, Router
from sift.sandbox import build_sandbox_from_env

TASKS_PATH = os.environ.get("SIFT_TASKS", "tasks/dev_help_archetypes.json")


def _configured(ladder: Ladder) -> Ladder:
    keep = [r for r in ladder.rungs if r.is_local or getattr(r.provider, "api_key", None)]
    return Ladder(keep)


def _scanner():
    try:
        from sift.security import HiddenLayerClient

        return HiddenLayerClient.from_env().scan
    except Exception as exc:  # noqa: BLE001
        print(f"[hiddenlayer] not configured ({type(exc).__name__}) — scanning disabled")
        return None


def main() -> int:
    ladder = _configured(default_ladder())
    print("sift — live run")
    print("ladder:", " -> ".join(f"{r.name}{'*' if r.is_local else ''}" for r in ladder.rungs))
    print("       (* = local GPU tier; unconfigured Claude rungs dropped)\n")

    sandbox = build_sandbox_from_env()
    print(f"oracle sandbox: {type(sandbox).__name__}")
    scanner = _scanner()

    harness = Harness("./_sift_live", security_scanner=scanner, sandbox=sandbox)
    router = Router(ladder, harness, rng=random.Random(0))

    tasks = [t for t in load_tasks(TASKS_PATH) if t.split == "train"]
    if not tasks:
        print(f"no train-split tasks in {TASKS_PATH}")
        return 1
    rounds = int(os.environ.get("SIFT_ROUNDS", "5"))
    print(f"tasks: {len(tasks)}   rounds: {rounds}\n")

    series = run_learning_experiment(tasks, router, rounds=rounds)
    print(f"{'round':>6} {'cost/task':>12} {'pass':>7} {'local':>7} {'rungs':>7}")
    for m in series:
        print(f"{m.round:>6} {m.avg_cost_usd:>11.5f}$ {m.pass_rate:>6.0%} "
              f"{m.local_served_frac:>6.0%} {m.avg_rungs:>7.2f}")

    first, last = series[0], series[-1]
    print(
        f"\ncold -> warm:"
        f"  cost/task ${first.avg_cost_usd:.5f} -> ${last.avg_cost_usd:.5f}"
        f"  |  local-served {first.local_served_frac:.0%} -> {last.local_served_frac:.0%}"
    )

    served = Counter(r.final_rung or "FAILED" for r in (router.route(t) for t in tasks))
    print("final-rung distribution (warm):", dict(served))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
