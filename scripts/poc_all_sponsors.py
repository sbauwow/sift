#!/usr/bin/env python3
"""sift — all-sponsor integration POC.

One script that wires every sponsor technology into a single running Claw agent
and prints which integrations are live:

  vLLM + Nemotron  local answerer tier (OpenAI-compatible endpoint)
  llm-d            distributed local tier (endpoint override -> idle-GPU fleet)
  Anthropic        the Claude escalation ladder (haiku/sonnet/opus/fable)
  HiddenLayer      runtime security scanning of every prompt/response
  NemoClaw/OpenShell  the oracle runs inside a YAML-policy sandbox
  Supabase         persistent Claw state across restarts

Runs the heartbeat loop for a few ticks. With no services configured it uses a
stub runner so the integrated loop and the recursive delta still demonstrate —
the *wiring* is real, only the inference is mocked. Configure env (.env.example)
to light each row up for real.

    uv run python scripts/poc_all_sponsors.py
"""

from __future__ import annotations

import os
import random
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sift.agent import HeartbeatAgent
from sift.config import default_ladder
from sift.harness import EvaluationResult, Harness, HarnessRun, TaskSpec, load_tasks
from sift.router import Ladder, Policy, Router, Rung
from sift.sandbox import build_sandbox_from_env
from sift.serving import probe_endpoint
from sift.state import build_state_store


def _env(*names: str) -> bool:
    return all(os.environ.get(n) for n in names)


def _row(name: str, active: bool, detail: str) -> str:
    mark = "LIVE " if active else "off  "
    return f"  [{mark}] {name:<22} {detail}"


# -- stub inference so the POC runs with zero services --------------------------

@dataclass
class _StubProvider:
    name: str
    model: str = "stub"
    is_local: bool = False


class _StubRunner:
    def run_task(self, task: TaskSpec, provider) -> HarnessRun:
        local = getattr(provider, "is_local", False)
        passed = (not local) or "easy" in task.tags
        return HarnessRun(
            task_id=task.id, provider=provider.name, model=provider.model,
            response="ok" if passed else "no",
            evaluation=EvaluationResult(task.id, passed, 0 if passed else 1, "", ""),
            cost_usd=0.0 if local else 0.02,
        )


def _stub_ladder(real: Ladder) -> Ladder:
    return Ladder([
        Rung(r.name, _StubProvider(r.name, is_local=r.is_local), is_local=r.is_local)
        for r in real.rungs
    ])


def _archetype_tasks() -> list[TaskSpec]:
    return [t for t in load_tasks("tasks/dev_help_archetypes.json") if t.split == "train"]


def _synthetic_tasks() -> list[TaskSpec]:
    # Clean easy/hard split for the stub-mode convergence curve.
    return [TaskSpec(id=f"e{i}", prompt="p", check_command="true", tags=("easy",)) for i in range(8)] \
        + [TaskSpec(id=f"h{i}", prompt="p", check_command="true", tags=("hard",)) for i in range(2)]


def main() -> int:
    print("=" * 68)
    print("sift — all-sponsor integration POC")
    print("=" * 68)

    ladder = default_ladder()
    local = ladder.rungs[0]
    local_probe = probe_endpoint(local.provider)
    sandbox = build_sandbox_from_env()
    has_hiddenlayer = _env("HIDDENLAYER_API_KEY", "HIDDENLAYER_API_SECRET", "HIDDENLAYER_ENDPOINT")
    has_supabase = bool(os.environ.get("SUPABASE_URL")) and bool(
        os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    )
    has_claude = bool(os.environ.get("ANTHROPIC_API_KEY"))
    is_llmd = "8080" in local.provider.endpoint or "llmd" in local.provider.endpoint

    print("\nSponsor integration matrix:")
    print(_row("vLLM + Nemotron", local_probe.ok, f"{local.provider.model} @ {local.provider.endpoint}"))
    print(_row("llm-d (fleet)", is_llmd, "distributed local tier" if is_llmd else "single-node (set SIFT_LOCAL_ENDPOINT)"))
    print(_row("Anthropic ladder", has_claude, "haiku/sonnet/opus/fable" if has_claude else "no ANTHROPIC_API_KEY"))
    print(_row("HiddenLayer", has_hiddenlayer, "I/O scanning on" if has_hiddenlayer else "scanning disabled"))
    print(_row("NemoClaw/OpenShell", type(sandbox).__name__ == "OpenShellSandbox",
              f"oracle sandbox = {type(sandbox).__name__}"))
    print(_row("Supabase", has_supabase, "state persisted to Postgres" if has_supabase else "JSON fallback"))

    # Real path if anything can actually answer; else stub the inference.
    live = local_probe.ok or has_claude
    if live:
        scanner = None
        if has_hiddenlayer:
            from sift.security import HiddenLayerClient

            scanner = HiddenLayerClient.from_env().scan
        runner = Harness("./_sift_poc", security_scanner=scanner, sandbox=sandbox)
        run_ladder = ladder
        tasks = _archetype_tasks() or _synthetic_tasks()
        mode = "LIVE inference"
    else:
        runner = _StubRunner()
        run_ladder = _stub_ladder(ladder)
        tasks = _synthetic_tasks()
        mode = "STUB inference (wiring real, models mocked)"

    router = Router(run_ladder, runner, policy=Policy(), rng=random.Random(0))
    store = build_state_store("sift-poc")
    # Probe the full suite each heartbeat so the per-tick curve reflects learning,
    # not which random subset got sampled.
    agent = HeartbeatAgent(router, tasks, state_store=store, probe_size=len(tasks),
                           sleep_fn=lambda _: None)

    print(f"\nRunning heartbeat Claw loop ({mode}), state -> {type(store).__name__}:\n")
    print(f"{'tick':>5} {'cost/task':>12} {'pass':>7} {'local':>7} {'rungs':>7}")
    reports = agent.run(max_ticks=8)
    for r in reports:
        print(f"{r.tick:>5} {r.avg_cost_usd:>11.5f}$ {r.pass_rate:>6.0%} "
              f"{r.local_served_frac:>6.0%} {r.avg_rungs:>7.2f}")

    first, last = reports[0], reports[-1]
    print(
        f"\nrecursive delta: cost/task ${first.avg_cost_usd:.5f} -> ${last.avg_cost_usd:.5f}"
        f"  |  local-served {first.local_served_frac:.0%} -> {last.local_served_frac:.0%}"
        f"  (across {agent.tick_count} persisted heartbeats)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
