import json

from sift.harness import Harness, TaskSpec, load_tasks
from sift.providers import ChatMessage, ModelResponse


class StubProvider:
    name = "stub"
    model = "stub-model"

    def generate(self, messages):
        assert messages == [ChatMessage(role="user", content="write a regex that matches hex colors")]
        return ModelResponse(provider="stub", model="stub-model", content="^#[0-9a-fA-F]{6}$", raw={})


def test_harness_marks_submission_passed_when_check_command_exits_zero(tmp_path):
    task = TaskSpec(
        id="regex-hex",
        prompt="write a regex that matches hex colors",
        check_command="test \"$(cat answer.txt)\" = '^#[0-9a-fA-F]{6}$'",
    )

    result = Harness(work_dir=tmp_path).evaluate(task, "^#[0-9a-fA-F]{6}$")

    assert result.task_id == "regex-hex"
    assert result.passed is True
    assert result.exit_code == 0


def test_harness_runs_provider_and_evaluates_the_model_response(tmp_path):
    task = TaskSpec(
        id="regex-hex",
        prompt="write a regex that matches hex colors",
        check_command="test \"$(cat answer.txt)\" = '^#[0-9a-fA-F]{6}$'",
    )

    run = Harness(work_dir=tmp_path).run_task(task, StubProvider())

    assert run.provider == "stub"
    assert run.model == "stub-model"
    assert run.response == "^#[0-9a-fA-F]{6}$"
    assert run.evaluation.passed is True


def test_loads_task_suite_from_json_file(tmp_path):
    suite_path = tmp_path / "tasks.json"
    suite_path.write_text(
        json.dumps(
            [
                {
                    "id": "regex-hex",
                    "prompt": "write a regex that matches hex colors",
                    "check_command": "test -s answer.txt",
                    "tags": ["regex", "easy"],
                    "split": "train",
                }
            ]
        ),
        encoding="utf-8",
    )

    tasks = load_tasks(suite_path)

    assert tasks == [
        TaskSpec(
            id="regex-hex",
            prompt="write a regex that matches hex colors",
            check_command="test -s answer.txt",
            tags=("regex", "easy"),
            split="train",
        )
    ]
