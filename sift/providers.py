from __future__ import annotations

import json
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]
Transport = Callable[["PreparedRequest"], dict[str, Any]]


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: str

    def to_wire(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    model: str
    endpoint: str
    api_key: str | None = None


@dataclass(frozen=True)
class PreparedRequest:
    url: str
    headers: dict[str, str]
    json: dict[str, Any]


@dataclass(frozen=True)
class ModelResponse:
    provider: str
    model: str
    content: str
    raw: dict[str, Any]


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        name: str,
        model: str,
        endpoint: str,
        api_key: str | None = None,
        transport: Transport | None = None,
    ):
        self.name = name
        self.model = model
        self.endpoint = endpoint
        self.api_key = api_key
        self._transport = transport or _urllib_transport

    def prepare_chat_request(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
    ) -> PreparedRequest:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [message.to_wire() for message in messages],
        }
        if temperature is not None:
            payload["temperature"] = temperature

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        return PreparedRequest(url=self.endpoint, headers=headers, json=payload)

    def generate(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
    ) -> ModelResponse:
        request = self.prepare_chat_request(messages, temperature=temperature)
        raw = self._transport(request)
        content = raw["choices"][0]["message"]["content"]
        return ModelResponse(provider=self.name, model=self.model, content=content, raw=raw)


_DEFAULT_ENDPOINTS = {
    "copilot": "https://api.githubcopilot.com/chat/completions",
    "opencode": "http://localhost:4096/v1/chat/completions",
    "vllm": "http://localhost:8000/v1/chat/completions",
    "llmd": "http://localhost:8080/v1/chat/completions",
}

_DEFAULT_MODELS = {
    "copilot": "gpt-5-mini",
    "opencode": "qwen2.5-coder",
    "vllm": "Qwen/Qwen2.5-Coder-7B-Instruct",
    "llmd": "Qwen/Qwen2.5-Coder-7B-Instruct",
}


def provider_config(
    name: str,
    *,
    model: str | None = None,
    api_key: str | None = None,
    endpoint: str | None = None,
) -> ProviderConfig:
    return ProviderConfig(
        name=name,
        model=model or _DEFAULT_MODELS[name],
        endpoint=endpoint or _DEFAULT_ENDPOINTS[name],
        api_key=api_key,
    )


def build_provider(
    config: ProviderConfig,
    *,
    transport: Transport | None = None,
) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        name=config.name,
        model=config.model,
        endpoint=config.endpoint,
        api_key=config.api_key,
        transport=transport,
    )


def _urllib_transport(request: PreparedRequest) -> dict[str, Any]:
    encoded = json.dumps(request.json).encode("utf-8")
    http_request = urllib.request.Request(
        request.url,
        data=encoded,
        headers=request.headers,
        method="POST",
    )
    with urllib.request.urlopen(http_request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))
