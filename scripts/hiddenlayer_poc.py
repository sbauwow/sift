#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sift.security import HiddenLayerClient
from sift.security_poc import run_hiddenlayer_poc


def main() -> int:
    try:
        client = HiddenLayerClient.from_env()
    except RuntimeError as exc:
        print(str(exc))
        print("Set HIDDENLAYER_API_KEY, HIDDENLAYER_API_SECRET, and HIDDENLAYER_ENDPOINT, then rerun.")
        return 2

    verdicts = run_hiddenlayer_poc(client)
    for name, verdict in verdicts.items():
        status = "ALLOW" if verdict.allowed else "BLOCK"
        reason = f" reason={verdict.reason}" if verdict.reason else ""
        print(f"{name}: {status}{reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
