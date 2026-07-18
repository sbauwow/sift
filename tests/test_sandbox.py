from __future__ import annotations

import subprocess
from pathlib import Path

from sift.harness import Harness, TaskSpec
from sift.sandbox import (
    DirectSandbox,
    OpenShellSandbox,
    build_sandbox_from_env,
    default_policy_path,
)


def test_direct_sandbox_runs_check(tmp_path):
    sandbox = DirectSandbox()
    result = sandbox.run("exit 0", cwd=tmp_path, timeout=5)
    assert result.returncode == 0
    fail = sandbox.run("exit 3", cwd=tmp_path, timeout=5)
    assert fail.returncode == 3


def test_openshell_sandbox_builds_policy_governed_argv(tmp_path):
    captured: dict[str, list[str]] = {}

    def fake_runner(argv):
        captured["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")

    policy = tmp_path / "oracle.yaml"
    policy.write_text("version: '1'\n")
    sandbox = OpenShellSandbox(policy, openshell_bin="openshell", runner=fake_runner)
    result = sandbox.run("grep -q PASS answer.txt", cwd=tmp_path, timeout=30)

    assert result.returncode == 0 and result.stdout == "ok"
    argv = captured["argv"]
    assert argv[0] == "openshell" and "run" in argv
    assert "--policy" in argv and str(policy) in argv
    assert "--workdir" in argv and str(tmp_path) in argv
    # The check is passed to bash inside the sandbox, not run on the host.
    assert argv[-3:] == ["bash", "-c", "grep -q PASS answer.txt"]


def test_harness_runs_oracle_through_injected_sandbox(tmp_path):
    calls: list[str] = []

    class RecordingSandbox:
        def run(self, command, *, cwd, timeout):
            calls.append(command)
            from sift.sandbox import SandboxResult

            return SandboxResult(0, "", "")

    harness = Harness(tmp_path, sandbox=RecordingSandbox())
    task = TaskSpec(id="t", prompt="p", check_command="true", tags=())
    result = harness.evaluate(task, "answer")
    assert result.passed is True
    assert calls == ["true"]  # oracle went through the sandbox, not raw subprocess


def test_env_selects_openshell_sandbox():
    assert isinstance(build_sandbox_from_env({}), DirectSandbox)
    sandbox = build_sandbox_from_env({"SIFT_SANDBOX": "openshell"})
    assert isinstance(sandbox, OpenShellSandbox)


def test_default_policy_file_exists():
    assert default_policy_path().name == "oracle.openshell.yaml"
    assert Path(default_policy_path()).exists()
