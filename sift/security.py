from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

Transport = Callable[["SecurityRequest"], dict[str, Any]]
Clock = Callable[[], int]


@dataclass(frozen=True)
class SecurityRequest:
    url: str
    headers: dict[str, str]
    json: dict[str, Any]


@dataclass(frozen=True)
class SecurityVerdict:
    allowed: bool
    reason: str = ""
    raw: dict[str, Any] | None = None


class HiddenLayerClient:
    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        endpoint: str,
        transport: Transport | None = None,
        clock: Clock | None = None,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.endpoint = endpoint
        self._transport = transport or _urllib_transport
        self._clock = clock or (lambda: int(time.time()))

    @classmethod
    def from_env(
        cls,
        *,
        transport: Transport | None = None,
        clock: Clock | None = None,
    ) -> "HiddenLayerClient":
        required = {
            "HIDDENLAYER_API_KEY": os.environ.get("HIDDENLAYER_API_KEY"),
            "HIDDENLAYER_API_SECRET": os.environ.get("HIDDENLAYER_API_SECRET"),
            "HIDDENLAYER_ENDPOINT": os.environ.get("HIDDENLAYER_ENDPOINT"),
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError(f"Missing HiddenLayer environment variables: {', '.join(missing)}")
        return cls(
            api_key=required["HIDDENLAYER_API_KEY"] or "",
            api_secret=required["HIDDENLAYER_API_SECRET"] or "",
            endpoint=required["HIDDENLAYER_ENDPOINT"] or "",
            transport=transport,
            clock=clock,
        )

    def prepare_event_request(
        self,
        *,
        event_type: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> SecurityRequest:
        payload = {
            "event_type": event_type,
            "content": content,
            "metadata": metadata or {},
        }
        timestamp = str(self._clock())
        body = _canonical_json(payload)
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            f"{timestamp}.{body}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return SecurityRequest(
            url=self.endpoint,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "X-HiddenLayer-Timestamp": timestamp,
                "X-HiddenLayer-Signature": signature,
            },
            json=payload,
        )

    def scan(self, event_type: str, content: str, metadata: dict[str, Any] | None = None) -> SecurityVerdict:
        raw = self._transport(
            self.prepare_event_request(
                event_type=event_type,
                content=content,
                metadata=metadata,
            )
        )
        allowed = raw.get("allowed")
        if allowed is None:
            allowed = not raw.get("flagged", False)
        return SecurityVerdict(allowed=bool(allowed), reason=raw.get("reason", ""), raw=raw)


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _urllib_transport(request: SecurityRequest) -> dict[str, Any]:
    http_request = urllib.request.Request(
        request.url,
        data=_canonical_json(request.json).encode("utf-8"),
        headers=request.headers,
        method="POST",
    )
    with urllib.request.urlopen(http_request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))
