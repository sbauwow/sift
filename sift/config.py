"""Build a routing ``Ladder`` of real providers from declarative specs + env.

This is the bridge from the stub demo to real models: a cost/capability-ordered
list of ``RungSpec``s becomes a ``Ladder`` of live providers (local Nemotron on
vLLM + the Claude tiers), with API keys pulled from the environment and the
transport injectable so tests and offline runs never touch the network.

The ladder is stack-agnostic — swap the specs for any providers the
``providers`` layer speaks (vLLM/llm-d, Anthropic, OpenAI-compatible, …).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from sift.providers import Transport, build_provider, provider_config
from sift.router import Ladder, Rung


@dataclass(frozen=True)
class RungSpec:
    tier: str                      # rung label used by the policy (region × tier)
    provider: str                  # provider preset name (e.g. "vllm", "llmd", "claude")
    model: str | None = None       # override the preset default model
    is_local: bool = False         # served on the local GPU (counts toward local-served%)
    api_key_env: str | None = None # env var holding the provider's API key
    endpoint: str | None = None    # override the preset endpoint (e.g. an llm-d gateway)


# The default demo ladder: local Nemotron on vLLM, then the Claude tiers.
# NEMOTRON_MODEL / SIFT_LOCAL_ENDPOINT override the local rung without code changes;
# point the local rung at an llm-d gateway to fan out across an idle-GPU fleet.
DEFAULT_LADDER_SPECS: tuple[RungSpec, ...] = (
    RungSpec(tier="local-nemotron", provider="vllm",
             model="nvidia/Nemotron-Mini-4B-Instruct", is_local=True),
    RungSpec(tier="haiku", provider="claude", model="claude-haiku-4-5",
             api_key_env="ANTHROPIC_API_KEY"),
    RungSpec(tier="sonnet", provider="claude", model="claude-sonnet-5",
             api_key_env="ANTHROPIC_API_KEY"),
    RungSpec(tier="opus", provider="claude", model="claude-opus-4-8",
             api_key_env="ANTHROPIC_API_KEY"),
    RungSpec(tier="fable", provider="claude", model="claude-fable-5",
             api_key_env="ANTHROPIC_API_KEY"),
)


def build_ladder(
    specs: tuple[RungSpec, ...] | list[RungSpec],
    *,
    transport: Transport | None = None,
    env: Mapping[str, str] | None = None,
) -> Ladder:
    env = env if env is not None else os.environ
    rungs: list[Rung] = []
    for spec in specs:
        api_key = env.get(spec.api_key_env) if spec.api_key_env else None
        endpoint = spec.endpoint
        if spec.is_local:
            endpoint = env.get("SIFT_LOCAL_ENDPOINT", endpoint)
        model = spec.model
        if spec.is_local:
            model = env.get("NEMOTRON_MODEL", model)
        config = provider_config(spec.provider, model=model, api_key=api_key, endpoint=endpoint)
        provider = build_provider(config, transport=transport)
        rungs.append(Rung(name=spec.tier, provider=provider, is_local=spec.is_local))
    return Ladder(rungs)


def default_ladder(
    *,
    transport: Transport | None = None,
    env: Mapping[str, str] | None = None,
) -> Ladder:
    return build_ladder(DEFAULT_LADDER_SPECS, transport=transport, env=env)
