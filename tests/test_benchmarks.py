from sift.benchmarks import BaselineResult, run_always_model_baselines, run_static_routing_baseline, summarize_baselines
from sift.harness import TaskSpec
from sift.providers import ChatMessage, ModelResponse, TokenUsage


class FixedProvider:
    def __init__(self, name, model, answer, usage=None):
        self.name = name
        self.model = model
        self.answer = answer
        self.usage = usage

    def generate(self, messages):
        return ModelResponse(provider=self.name, model=self.model, content=self.answer, raw={}, usage=self.usage)


def test_runs_always_model_baselines_and_summarizes_pass_rates(tmp_path):
    task = TaskSpec(
        id="exact-pass",
        prompt="return the exact token PASS",
        check_command="test \"$(cat answer.txt)\" = PASS",
    )
    providers = [
        FixedProvider("cheap", "cheap-model", "FAIL"),
        FixedProvider("expensive", "expensive-model", "PASS"),
    ]

    result = run_always_model_baselines(
        tasks=[task],
        providers=providers,
        work_dir=tmp_path,
    )

    assert [run.provider for run in result.runs] == ["cheap", "expensive"]
    assert [run.evaluation.passed for run in result.runs] == [False, True]
    assert summarize_baselines(result) == {
        "cheap": {
            "tasks": 1,
            "passed": 0,
            "pass_rate": 0.0,
            "cost_usd": 0.0,
            "security_events": 0,
            "security_latency_ms": 0.0,
            "avg_security_latency_ms": 0.0,
        },
        "expensive": {
            "tasks": 1,
            "passed": 1,
            "pass_rate": 1.0,
            "cost_usd": 0.0,
            "security_events": 0,
            "security_latency_ms": 0.0,
            "avg_security_latency_ms": 0.0,
        },
    }


def test_static_routing_baseline_routes_by_task_tags(tmp_path):
    easy = TaskSpec(
        id="easy",
        prompt="return the exact token PASS",
        check_command="test \"$(cat answer.txt)\" = PASS",
        tags=("easy",),
    )
    hard = TaskSpec(
        id="hard",
        prompt="return the exact token PASS",
        check_command="test \"$(cat answer.txt)\" = PASS",
        tags=("hard",),
    )
    providers = {
        "local": FixedProvider("local", "local-model", "FAIL"),
        "opus": FixedProvider("opus", "opus-model", "PASS"),
    }

    result = run_static_routing_baseline(
        tasks=[easy, hard],
        providers=providers,
        tag_routes={"easy": "local", "hard": "opus"},
        default_provider="opus",
        work_dir=tmp_path,
    )

    assert [(run.task_id, run.provider, run.evaluation.passed) for run in result.runs] == [
        ("easy", "local", False),
        ("hard", "opus", True),
    ]


def test_baseline_summary_includes_observed_token_cost(tmp_path):
    task = TaskSpec(
        id="exact-pass",
        prompt="return the exact token PASS",
        check_command="test \"$(cat answer.txt)\" = PASS",
    )
    provider = FixedProvider(
        "sonnet",
        "claude-sonnet-4-5",
        "PASS",
        usage=TokenUsage(input_tokens=1000, output_tokens=2000, input_cost_per_million=3.0, output_cost_per_million=15.0),
    )

    result = run_always_model_baselines(tasks=[task], providers=[provider], work_dir=tmp_path)

    assert summarize_baselines(result) == {
        "sonnet": {
            "tasks": 1,
            "passed": 1,
            "pass_rate": 1.0,
            "cost_usd": 0.033,
            "security_events": 0,
            "security_latency_ms": 0.0,
            "avg_security_latency_ms": 0.0,
        }
    }


def test_baseline_summary_includes_security_overhead():
    from sift.harness import EvaluationResult, HarnessRun
    from sift.security import SecurityVerdict

    result = BaselineResult(
        runs=[
        HarnessRun(
            task_id="t1",
            provider="local",
            model="m",
            response="ok",
            evaluation=EvaluationResult("t1", True, 0, "", ""),
            security_verdict=SecurityVerdict(True, "ok"),
            security_events=2,
            security_latency_ms=11.25,
        ),
        HarnessRun(
            task_id="t2",
            provider="local",
            model="m",
            response="ok",
            evaluation=EvaluationResult("t2", True, 0, "", ""),
            security_verdict=SecurityVerdict(True, "ok"),
            security_events=2,
            security_latency_ms=8.75,
        ),
        ],
    )

    assert summarize_baselines(result)["local"]["security_events"] == 4
    assert summarize_baselines(result)["local"]["security_latency_ms"] == 20.0
    assert summarize_baselines(result)["local"]["avg_security_latency_ms"] == 10.0
