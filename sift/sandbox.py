"""Containment for the oracle — the untrusted-code execution boundary.

The executable oracle runs a shell check against a model-produced answer. That is
the highest-risk surface in sift: model output influencing a subprocess. This
module puts a policy boundary around it.

* ``DirectSandbox`` — the dev default: runs the check directly (no containment).
* ``OpenShellSandbox`` — the NemoClaw + OpenShell bounty integration: runs the
  check inside an OpenShell sandbox governed by a declarative YAML policy
  (``policies/oracle.openshell.yaml``) that blocks network egress, confines the
  filesystem to the task's work dir, and forbids irreversible actions. The agent
  *can* run code; the policy is what stops it exfiltrating or escaping.

This pairs with HiddenLayer as defense-in-depth: HiddenLayer *detects* the
injection at the model boundary; OpenShell *contains* the blast radius at the
execution boundary.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

CommandRunner = Callable[[list[str]], subprocess.CompletedProcess]


@dataclass(frozen=True)
class SandboxResult:
    returncode: int
    stdout: str
    stderr: str


class Sandbox(Protocol):
    def run(self, command: str, *, cwd: Path, timeout: int) -> SandboxResult: ...


class DirectSandbox:
    """No containment — runs the check in a plain subprocess. Dev default."""

    def run(self, command: str, *, cwd: Path, timeout: int) -> SandboxResult:
        completed = subprocess.run(
            command, cwd=cwd, shell=True, text=True,
            capture_output=True, timeout=timeout, check=False,
        )
        return SandboxResult(completed.returncode, completed.stdout, completed.stderr)


class OpenShellSandbox:
    """Runs the check inside an OpenShell sandbox under a YAML policy.

    ``runner`` is injectable so the argv contract is testable without OpenShell
    installed; in production it defaults to a real subprocess call to the
    ``openshell`` CLI.
    """

    def __init__(
        self,
        policy_path: str | Path,
        *,
        openshell_bin: str = "openshell",
        runner: CommandRunner | None = None,
    ):
        self.policy_path = Path(policy_path)
        self.openshell_bin = openshell_bin
        self._runner = runner or self._default_runner

    def argv(self, command: str, cwd: Path) -> list[str]:
        return [
            self.openshell_bin, "run",
            "--policy", str(self.policy_path),
            "--workdir", str(cwd),
            "--", "bash", "-c", command,
        ]

    def run(self, command: str, *, cwd: Path, timeout: int) -> SandboxResult:
        completed = self._runner(self.argv(command, cwd))
        return SandboxResult(completed.returncode, completed.stdout or "", completed.stderr or "")

    @staticmethod
    def _default_runner(argv: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(argv, text=True, capture_output=True, timeout=60, check=False)


def default_policy_path() -> Path:
    """Repo-relative path to the oracle OpenShell policy."""
    return Path(__file__).resolve().parent.parent / "policies" / "oracle.openshell.yaml"


def build_sandbox_from_env(env: dict[str, str] | None = None) -> Sandbox:
    """Select the sandbox from ``SIFT_SANDBOX`` (``openshell`` | ``direct``)."""
    env = env if env is not None else dict(os.environ)
    if env.get("SIFT_SANDBOX", "direct").lower() == "openshell":
        policy = env.get("SIFT_OPENSHELL_POLICY") or str(default_policy_path())
        return OpenShellSandbox(policy, openshell_bin=env.get("OPENSHELL_BIN", "openshell"))
    return DirectSandbox()
