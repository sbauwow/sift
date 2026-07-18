from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from sift.providers import ChatMessage, ModelResponse
from sift.sandbox import DirectSandbox, Sandbox
from sift.security import SecurityVerdict


class Provider(Protocol):
    name: str
    model: str

    def generate(self, messages: list[ChatMessage]) -> ModelResponse: ...


class SecurityScanner(Protocol):
    def __call__(self, event_type: str, content: str, metadata: dict[str, str]) -> SecurityVerdict: ...


@dataclass(frozen=True)
class TaskSpec:
    id: str
    prompt: str
    check_command: str
    tags: tuple[str, ...] = ()
    split: str = "train"


@dataclass(frozen=True)
class EvaluationResult:
    task_id: str
    passed: bool
    exit_code: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class HarnessRun:
    task_id: str
    provider: str
    model: str
    response: str
    evaluation: EvaluationResult
    cost_usd: float = 0.0
    security_verdict: SecurityVerdict = SecurityVerdict(allowed=True, reason="not scanned")
    security_events: int = 0
    security_latency_ms: float = 0.0


class Harness:
    def __init__(
        self,
        work_dir: str | Path,
        security_scanner: SecurityScanner | None = None,
        sandbox: Sandbox | None = None,
        clock=time.perf_counter,
    ):
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.security_scanner = security_scanner
        self.sandbox = sandbox or DirectSandbox()
        self._clock = clock

    def run_task(self, task: TaskSpec, provider: Provider) -> HarnessRun:
        security_events = 0
        security_latency_ms = 0.0
        prompt_verdict, elapsed = self._scan("prompt", task.prompt, {"task_id": task.id, "split": task.split})
        security_events += 1 if self.security_scanner is not None else 0
        security_latency_ms += elapsed
        if not prompt_verdict.allowed:
            return HarnessRun(
                task_id=task.id,
                provider=provider.name,
                model=provider.model,
                response="",
                evaluation=EvaluationResult(
                    task_id=task.id,
                    passed=False,
                    exit_code=1,
                    stdout="",
                    stderr=prompt_verdict.reason,
                ),
                security_verdict=prompt_verdict,
                security_events=security_events,
                security_latency_ms=security_latency_ms,
            )

        model_response = provider.generate([ChatMessage(role="user", content=task.prompt)])
        response_verdict, elapsed = self._scan(
            "response",
            model_response.content,
            {"task_id": task.id, "provider": model_response.provider, "model": model_response.model},
        )
        security_events += 1 if self.security_scanner is not None else 0
        security_latency_ms += elapsed
        if not response_verdict.allowed:
            return HarnessRun(
                task_id=task.id,
                provider=model_response.provider,
                model=model_response.model,
                response=model_response.content,
                evaluation=EvaluationResult(
                    task_id=task.id,
                    passed=False,
                    exit_code=1,
                    stdout="",
                    stderr=response_verdict.reason,
                ),
                cost_usd=model_response.usage.cost_usd if model_response.usage else 0.0,
                security_verdict=response_verdict,
                security_events=security_events,
                security_latency_ms=security_latency_ms,
            )

        evaluation = self.evaluate(task, model_response.content)
        return HarnessRun(
            task_id=task.id,
            provider=model_response.provider,
            model=model_response.model,
            response=model_response.content,
            evaluation=evaluation,
            cost_usd=model_response.usage.cost_usd if model_response.usage else 0.0,
            security_verdict=response_verdict,
            security_events=security_events,
            security_latency_ms=security_latency_ms,
        )

    def evaluate(self, task: TaskSpec, answer: str) -> EvaluationResult:
        task_dir = self.work_dir / task.id
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "answer.txt").write_text(answer, encoding="utf-8")

        result = self.sandbox.run(task.check_command, cwd=task_dir, timeout=30)
        return EvaluationResult(
            task_id=task.id,
            passed=result.returncode == 0,
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    def _scan(self, event_type: str, content: str, metadata: dict[str, str]) -> tuple[SecurityVerdict, float]:
        if self.security_scanner is None:
            return SecurityVerdict(allowed=True, reason="not scanned"), 0.0
        start = self._clock()
        verdict = self.security_scanner(event_type, content, metadata)
        elapsed_ms = round((self._clock() - start) * 1000, 6)
        return verdict, elapsed_ms


def load_tasks(path: str | Path) -> list[TaskSpec]:
    raw_tasks = json.loads(Path(path).read_text(encoding="utf-8"))
    return [
        TaskSpec(
            id=raw["id"],
            prompt=raw["prompt"],
            check_command=raw["check_command"],
            tags=tuple(raw.get("tags", ())),
            split=raw.get("split", "train"),
        )
        for raw in raw_tasks
    ]
