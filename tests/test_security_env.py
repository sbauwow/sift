import pytest

from sift.security import HiddenLayerClient


def test_hiddenlayer_client_loads_credentials_from_environment(monkeypatch):
    monkeypatch.setenv("HIDDENLAYER_API_KEY", "test-key")
    monkeypatch.setenv("HIDDENLAYER_API_SECRET", "test-secret")
    monkeypatch.setenv("HIDDENLAYER_ENDPOINT", "https://security.example.test/events")

    client = HiddenLayerClient.from_env(clock=lambda: 1234567890)
    request = client.prepare_event_request(event_type="prompt", content="hello")

    assert request.url == "https://security.example.test/events"
    assert request.headers["Authorization"] == "Bearer test-key"


def test_hiddenlayer_client_reports_missing_environment_without_leaking_secret(monkeypatch):
    monkeypatch.delenv("HIDDENLAYER_API_KEY", raising=False)
    monkeypatch.setenv("HIDDENLAYER_API_SECRET", "super-secret")
    monkeypatch.delenv("HIDDENLAYER_ENDPOINT", raising=False)

    with pytest.raises(RuntimeError) as excinfo:
        HiddenLayerClient.from_env()

    assert "HIDDENLAYER_API_KEY" in str(excinfo.value)
    assert "HIDDENLAYER_ENDPOINT" in str(excinfo.value)
    assert "super-secret" not in str(excinfo.value)
