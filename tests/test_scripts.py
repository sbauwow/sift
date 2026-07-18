from __future__ import annotations

import subprocess
import sys


def test_run_demo_script_executes_from_repo_root():
    completed = subprocess.run(
        [sys.executable, "scripts/run_demo.py"],
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert completed.returncode == 0
    assert "recursive-delta demo" in completed.stdout
    assert "ModuleNotFoundError" not in completed.stderr


def test_all_sponsors_poc_script_executes_from_repo_root(tmp_path):
    completed = subprocess.run(
        [sys.executable, "scripts/poc_all_sponsors.py"],
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
        env={"SIFT_STATE_PATH": str(tmp_path / "state.json")},
    )

    assert completed.returncode == 0
    assert "all-sponsor integration POC" in completed.stdout
    assert "Sponsor integration matrix" in completed.stdout
    assert "ModuleNotFoundError" not in completed.stderr


def test_healthcheck_script_executes_from_repo_root_without_import_error():
    completed = subprocess.run(
        [sys.executable, "scripts/healthcheck.py"],
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert "sift — ladder health check" in completed.stdout
    assert "ModuleNotFoundError" not in completed.stderr
