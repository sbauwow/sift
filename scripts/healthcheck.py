#!/usr/bin/env python3
"""Probe the configured routing ladder — is each rung reachable and how fast?

    uv run python scripts/healthcheck.py

Local rung comes from SIFT_LOCAL_ENDPOINT / NEMOTRON_MODEL (default vLLM :8000).
Claude rungs need ANTHROPIC_API_KEY. Missing keys are reported, not fatal — the
local rung is what this checks before a live run.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sift.config import default_ladder
from sift.serving import probe_endpoint


def main() -> int:
    ladder = default_ladder()
    print("sift — ladder health check\n")
    any_fail = False
    for rung in ladder.rungs:
        # Local rung needs no API key; Claude rungs are skipped without one.
        needs_key = not rung.is_local and getattr(rung.provider, "api_key", None) in (None, "")
        if needs_key:
            print(f"  {rung.name:<16} SKIP  (no API key configured)")
            continue
        result = probe_endpoint(rung.provider)
        status = "OK  " if result.ok else "FAIL"
        any_fail = any_fail or not result.ok
        print(f"  {rung.name:<16} {status}  {result.latency_ms:7.0f}ms  {result.detail}")

    local = ladder.rungs[0]
    print(f"\nlocal endpoint: {local.provider.endpoint}")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("note: ANTHROPIC_API_KEY unset — Claude rungs will be skipped in a live run.")
    return 1 if any_fail else 0


if __name__ == "__main__":
    sys.exit(main())
