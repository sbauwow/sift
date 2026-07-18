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
class TokenUsage:
    input_tokens: int
    output_tokens: int
    input_cost_per_million: float = 0.0
    output_cost_per_million: float = 0.0

    @property
    def cost_usd(self) -> float:
        input_cost = self.input_tokens * self.input_cost_per_million / 1_000_000
        output_cost = self.output_tokens * self.output_cost_per_million / 1_000_000
        return input_cost + output_cost


@dataclass(frozen=True)
class ModelPricing:
    model: str
    tier: str
    input_cost_per_million: float
    output_cost_per_million: float


@dataclass(frozen=True)
class ModelResponse:
    provider: str
    model: str
    content: str
    raw: dict[str, Any]
    usage: TokenUsage | None = None


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
        usage = _openai_compatible_usage(raw, self.model)
        return ModelResponse(provider=self.name, model=self.model, content=content, raw=raw, usage=usage)


class AnthropicProvider:
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
        system_messages = [message.content for message in messages if message.role == "system"]
        non_system_messages = [message.to_wire() for message in messages if message.role != "system"]
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": non_system_messages,
        }
        if system_messages:
            payload["system"] = "\n\n".join(system_messages)
        if temperature is not None and not _anthropic_model_drops_temperature(self.model):
            payload["temperature"] = temperature

        headers = {
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key

        return PreparedRequest(url=self.endpoint, headers=headers, json=payload)

    def generate(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
    ) -> ModelResponse:
        request = self.prepare_chat_request(messages, temperature=temperature)
        raw = self._transport(request)
        content = raw["content"][0]["text"]
        usage = _anthropic_usage(raw, self.model)
        return ModelResponse(provider=self.name, model=self.model, content=content, raw=raw, usage=usage)


_DEFAULT_ENDPOINTS = {
    "anthropic": "https://api.anthropic.com/v1/messages",
    "claude": "https://api.anthropic.com/v1/messages",
    "copilot": "https://api.githubcopilot.com/chat/completions",
    "deepseek": "https://api.deepseek.com/chat/completions",
    "opencode": "http://localhost:4096/v1/chat/completions",
    "vllm": "http://localhost:8000/v1/chat/completions",
    "llmd": "http://localhost:8080/v1/chat/completions",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    "moonshot": "https://api.moonshot.cn/v1/chat/completions",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
    "yi": "https://api.lingyiwanwu.com/v1/chat/completions",
    "baichuan": "https://api.baichuan-ai.com/v1/chat/completions",
}

_DEFAULT_MODELS = {
    "anthropic": "claude-opus-4-6",
    "claude": "claude-opus-4-6",
    "copilot": "gpt-5-mini",
    "deepseek": "deepseek-chat",
    "opencode": "qwen2.5-coder",
    "vllm": "Qwen/Qwen2.5-Coder-7B-Instruct",
    "llmd": "Qwen/Qwen2.5-Coder-7B-Instruct",
    "qwen": "qwen-plus",
    "moonshot": "moonshot-v1-8k",
    "zhipu": "glm-4.5",
    "yi": "yi-large",
    "baichuan": "Baichuan4",
}


_MODEL_PRICING = {
    "gpt-5-mini": ModelPricing(
        model="gpt-5-mini",
        tier="value",
        input_cost_per_million=0.25,
        output_cost_per_million=2.0,
    ),
    "claude-opus-4-6": ModelPricing(
        model="claude-opus-4-6",
        tier="frontier",
        input_cost_per_million=5.0,
        output_cost_per_million=25.0,
    ),
}


_ZERO_COST_PRICING = ModelPricing(
    model="unknown",
    tier="unknown",
    input_cost_per_million=0.0,
    output_cost_per_million=0.0,
)


def model_pricing(model: str) -> ModelPricing:
    return _MODEL_PRICING.get(model, _ZERO_COST_PRICING)


def _anthropic_model_drops_temperature(model: str) -> bool:
    return "claude" in model and any(version in model for version in ("4-6", "4.6"))


def _openai_compatible_usage(raw: dict[str, Any], model: str) -> TokenUsage | None:
    raw_usage = raw.get("usage")
    if not raw_usage:
        return None
    pricing = model_pricing(model)
    return TokenUsage(
        input_tokens=raw_usage.get("prompt_tokens", 0),
        output_tokens=raw_usage.get("completion_tokens", 0),
        input_cost_per_million=pricing.input_cost_per_million,
        output_cost_per_million=pricing.output_cost_per_million,
    )


def _anthropic_usage(raw: dict[str, Any], model: str) -> TokenUsage | None:
    raw_usage = raw.get("usage")
    if not raw_usage:
        return None
    pricing = model_pricing(model)
    return TokenUsage(
        input_tokens=raw_usage.get("input_tokens", 0),
        output_tokens=raw_usage.get("output_tokens", 0),
        input_cost_per_million=pricing.input_cost_per_million,
        output_cost_per_million=pricing.output_cost_per_million,
    )


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
) -> OpenAICompatibleProvider | AnthropicProvider:
    if config.name in {"anthropic", "claude"}:
        return AnthropicProvider(
            name=config.name,
            model=config.model,
            endpoint=config.endpoint,
            api_key=config.api_key,
            transport=transport,
        )
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
