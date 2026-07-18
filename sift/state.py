"""Persistent state backends for the Claw agent.

The heartbeat agent checkpoints its learned policy after every wake. ``StateStore``
abstracts *where*: ``JsonStateStore`` (local file, the dev default) or
``SupabaseStateStore`` (Supabase Postgres via its REST API — the sponsor-backed
"persistent with context" store). Transport is injectable so the Supabase path is
unit-testable without a network.
"""

from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

State = dict[str, Any]


class StateStore(Protocol):
    def save(self, state: State) -> None: ...
    def load(self) -> State | None: ...


class JsonStateStore:
    """Checkpoint to a local JSON file."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def save(self, state: State) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def load(self) -> State | None:
        if not self.path.exists():
            return None
        return json.loads(self.path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class HttpRequest:
    method: str
    url: str
    headers: dict[str, str]
    body: bytes | None


HttpTransport = Callable[[HttpRequest], Any]


class SupabaseStateStore:
    """Upsert/read agent state in a Supabase table via PostgREST.

    Table shape (SQL):
        create table sift_agent_state (
            agent_id text primary key,
            state    jsonb not null,
            updated_at timestamptz default now()
        );
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        agent_id: str,
        table: str = "sift_agent_state",
        transport: HttpTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.agent_id = agent_id
        self.table = table
        self._transport = transport or _urllib_transport

    @classmethod
    def from_env(
        cls,
        agent_id: str,
        *,
        env: dict[str, str] | None = None,
        transport: HttpTransport | None = None,
    ) -> "SupabaseStateStore":
        env = env if env is not None else dict(os.environ)
        base_url = env.get("SUPABASE_URL")
        api_key = env.get("SUPABASE_KEY") or env.get("SUPABASE_SERVICE_ROLE_KEY")
        if not base_url or not api_key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set")
        return cls(
            base_url=base_url,
            api_key=api_key,
            agent_id=agent_id,
            table=env.get("SUPABASE_TABLE", "sift_agent_state"),
            transport=transport,
        )

    def _headers(self, *, upsert: bool = False) -> dict[str, str]:
        headers = {
            "apikey": self.api_key,
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if upsert:
            headers["Prefer"] = "resolution=merge-duplicates,return=minimal"
        return headers

    def save(self, state: State) -> None:
        row = [{"agent_id": self.agent_id, "state": state}]
        self._transport(
            HttpRequest(
                method="POST",
                url=f"{self.base_url}/rest/v1/{self.table}",
                headers=self._headers(upsert=True),
                body=json.dumps(row).encode("utf-8"),
            )
        )

    def load(self) -> State | None:
        result = self._transport(
            HttpRequest(
                method="GET",
                url=f"{self.base_url}/rest/v1/{self.table}"
                f"?agent_id=eq.{self.agent_id}&select=state",
                headers=self._headers(),
                body=None,
            )
        )
        if not result:
            return None
        first = result[0] if isinstance(result, list) else result
        return first.get("state") if isinstance(first, dict) else None


def build_state_store(agent_id: str, *, env: dict[str, str] | None = None) -> StateStore:
    """Supabase if configured, else a local JSON checkpoint."""
    env = env if env is not None else dict(os.environ)
    if env.get("SUPABASE_URL") and (env.get("SUPABASE_KEY") or env.get("SUPABASE_SERVICE_ROLE_KEY")):
        return SupabaseStateStore.from_env(agent_id, env=env)
    path = env.get("SIFT_STATE_PATH", f"./_sift_state/{agent_id}.json")
    return JsonStateStore(path)


def _urllib_transport(request: HttpRequest) -> Any:
    http_request = urllib.request.Request(
        request.url, data=request.body, headers=request.headers, method=request.method
    )
    with urllib.request.urlopen(http_request, timeout=15) as response:
        payload = response.read().decode("utf-8")
    return json.loads(payload) if payload.strip() else None
