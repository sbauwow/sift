from __future__ import annotations

from sift.providers import ModelResponse
from sift.serving import probe_endpoint, wait_for_endpoint


class FakeProvider:
    def __init__(self, *, replies, model="nemotron"):
        self._replies = list(replies)
        self.model = model
        self.name = "local"

    def generate(self, messages):
        item = self._replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return ModelResponse(provider=self.name, model=self.model, content=item, raw={})


def _fake_clock():
    ticks = iter([0.0, 0.05, 0.0, 0.05, 0.0, 0.05])
    return lambda: next(ticks)


def test_probe_ok_reports_latency():
    provider = FakeProvider(replies=["ok"])
    result = probe_endpoint(provider, clock=_fake_clock())
    assert result.ok is True
    assert result.latency_ms == 50.0
    assert "model=nemotron" in result.detail


def test_probe_reports_failure_without_raising():
    provider = FakeProvider(replies=[ConnectionError("refused")])
    result = probe_endpoint(provider)
    assert result.ok is False
    assert "ConnectionError" in result.detail


def test_wait_for_endpoint_retries_until_up():
    provider = FakeProvider(replies=[ConnectionError("warming"), ConnectionError("warming"), "ok"])
    sleeps: list[float] = []
    result = wait_for_endpoint(
        provider, attempts=5, delay_s=2.0, sleep_fn=sleeps.append,
    )
    assert result.ok is True
    assert sleeps == [2.0, 2.0]  # slept between the two failed attempts


def test_wait_for_endpoint_gives_up():
    provider = FakeProvider(replies=[ConnectionError("down")] * 3)
    result = wait_for_endpoint(provider, attempts=3, sleep_fn=lambda _: None)
    assert result.ok is False
