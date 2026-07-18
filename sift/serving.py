"""Connectivity + readiness probes for the local serving endpoint.

The local rung is served by vLLM (or an llm-d gateway / Featherless / NIM) behind
an OpenAI-compatible API. Before a live run we probe it: is it up, how fast is a
round-trip, does it answer. ``wait_for_endpoint`` polls while a server warms up.

Provider transport is injectable, so this is unit-testable without a network.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from sift.providers import ChatMessage


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    latency_ms: float
    detail: str


def probe_endpoint(
    provider,
    *,
    prompt: str = "Reply with the single word: ok",
    clock: Callable[[], float] = time.perf_counter,
) -> ProbeResult:
    """Send one tiny completion and report reachability + latency."""
    start = clock()
    try:
        response = provider.generate([ChatMessage(role="user", content=prompt)])
    except Exception as exc:  # noqa: BLE001 — a probe reports failures, doesn't raise
        return ProbeResult(False, (clock() - start) * 1000, f"{type(exc).__name__}: {exc}")
    latency_ms = (clock() - start) * 1000
    content = response.content or ""
    return ProbeResult(
        ok=bool(content),
        latency_ms=latency_ms,
        detail=f"model={response.model} chars={len(content)}",
    )


def wait_for_endpoint(
    provider,
    *,
    attempts: int = 30,
    delay_s: float = 2.0,
    sleep_fn: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.perf_counter,
) -> ProbeResult:
    """Poll ``probe_endpoint`` until it succeeds or ``attempts`` is exhausted."""
    result = ProbeResult(False, 0.0, "no attempts made")
    for attempt in range(attempts):
        result = probe_endpoint(provider, clock=clock)
        if result.ok:
            return result
        if attempt < attempts - 1:
            sleep_fn(delay_s)
    return result
