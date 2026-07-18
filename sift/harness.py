from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from sift.providers import ChatMessage, ModelResponse


class Provider(Protocol):
    name: str
    model: str

    def generate(self, messages: list[ChatMessage]) -> ModelResponse: ...


@dataclass(frozen=True)
class TaskSpec:
    id: str
    prompt: str
    check_command: str
    tags: tuple[str, ...] = ()


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


class Harness:
    def __init__(self, work_dir: str | Path):
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)

    def run_task(self, task: TaskSpec, provider: Provider) -> HarnessRun:
        model_response = provider.generate([ChatMessage(role="user", content=task.prompt)])
        evaluation = self.evaluate(task, model_response.content)
        return HarnessRun(
            task_id=task.id,
            provider=model_response.provider,
            model=model_response.model,
            response=model_response.content,
            evaluation=evaluation,
        )

    def evaluate(self, task: TaskSpec, answer: str) -> EvaluationResult:
        task_dir = self.work_dir / task.id
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / "answer.txt").write_text(answer, encoding="utf-8")

        completed = subprocess.run(
            task.check_command,
            cwd=task_dir,
            shell=True,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        return EvaluationResult(
            task_id=task.id,
            passed=completed.returncode == 0,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


def load_tasks(path: str | Path) -> list[TaskSpec]:
    raw_tasks = json.loads(Path(path).read_text(encoding="utf-8"))
    return [
        TaskSpec(
            id=raw["id"],
            prompt=raw["prompt"],
            check_command=raw["check_command"],
            tags=tuple(raw.get("tags", ())),
        )
        for raw in raw_tasks
    ]
