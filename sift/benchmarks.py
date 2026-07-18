from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sift.harness import Harness, HarnessRun, Provider, TaskSpec


@dataclass(frozen=True)
class BaselineResult:
    runs: list[HarnessRun]


def run_always_model_baselines(
    *,
    tasks: list[TaskSpec],
    providers: list[Provider],
    work_dir: str | Path,
) -> BaselineResult:
    runs: list[HarnessRun] = []
    for provider in providers:
        harness = Harness(Path(work_dir) / provider.name)
        for task in tasks:
            runs.append(harness.run_task(task, provider))
    return BaselineResult(runs=runs)


def run_static_routing_baseline(
    *,
    tasks: list[TaskSpec],
    providers: dict[str, Provider],
    tag_routes: dict[str, str],
    default_provider: str,
    work_dir: str | Path,
) -> BaselineResult:
    harness = Harness(Path(work_dir) / "static-routing")
    runs: list[HarnessRun] = []
    for task in tasks:
        provider_name = _provider_for_task(
            task,
            tag_routes=tag_routes,
            default_provider=default_provider,
        )
        runs.append(harness.run_task(task, providers[provider_name]))
    return BaselineResult(runs=runs)


def summarize_baselines(result: BaselineResult) -> dict[str, dict[str, float | int]]:
    summary: dict[str, dict[str, float | int]] = {}
    for run in result.runs:
        provider_summary = summary.setdefault(
            run.provider,
            {"tasks": 0, "passed": 0, "pass_rate": 0.0, "cost_usd": 0.0},
        )
        provider_summary["tasks"] += 1
        provider_summary["cost_usd"] += run.cost_usd
        if run.evaluation.passed:
            provider_summary["passed"] += 1

    for provider_summary in summary.values():
        tasks = provider_summary["tasks"]
        provider_summary["pass_rate"] = provider_summary["passed"] / tasks if tasks else 0.0
        provider_summary["cost_usd"] = round(provider_summary["cost_usd"], 6)

    return summary


def _provider_for_task(
    task: TaskSpec,
    *,
    tag_routes: dict[str, str],
    default_provider: str,
) -> str:
    for tag in task.tags:
        if tag in tag_routes:
            return tag_routes[tag]
    return default_provider
