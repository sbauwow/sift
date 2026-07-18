from __future__ import annotations

from sift.config import DEFAULT_LADDER_SPECS, RungSpec, build_ladder, default_ladder
from sift.providers import AnthropicProvider, OpenAICompatibleProvider


def _fake_transport(_request):
    return {"choices": [{"message": {"content": "x"}}], "content": [{"text": "x"}]}


def test_default_ladder_orders_local_first_then_claude_tiers():
    ladder = default_ladder(transport=_fake_transport, env={"ANTHROPIC_API_KEY": "k"})
    names = [rung.name for rung in ladder.rungs]
    assert names == ["local-nemotron", "haiku", "sonnet", "opus", "fable"]
    assert ladder.rungs[0].is_local is True
    assert all(not rung.is_local for rung in ladder.rungs[1:])


def test_local_rung_uses_vllm_openai_compatible_provider():
    ladder = default_ladder(transport=_fake_transport, env={})
    local = ladder.rungs[0]
    assert isinstance(local.provider, OpenAICompatibleProvider)
    assert local.provider.endpoint.endswith(":8000/v1/chat/completions")
    assert local.provider.model == "nvidia/Nemotron-Mini-4B-Instruct"


def test_claude_rungs_use_anthropic_provider_and_env_key():
    ladder = default_ladder(transport=_fake_transport, env={"ANTHROPIC_API_KEY": "secret"})
    opus = next(r for r in ladder.rungs if r.name == "opus")
    assert isinstance(opus.provider, AnthropicProvider)
    assert opus.provider.model == "claude-opus-4-8"
    assert opus.provider.api_key == "secret"


def test_env_overrides_local_model_and_endpoint():
    env = {
        "NEMOTRON_MODEL": "nvidia/Nemotron-H-8B",
        "SIFT_LOCAL_ENDPOINT": "http://llmd-gateway:8080/v1/chat/completions",
    }
    ladder = default_ladder(transport=_fake_transport, env=env)
    local = ladder.rungs[0]
    assert local.provider.model == "nvidia/Nemotron-H-8B"
    assert "llmd-gateway" in local.provider.endpoint


def test_build_ladder_is_stack_agnostic():
    specs = [
        RungSpec(tier="local", provider="vllm", is_local=True),
        RungSpec(tier="deepseek", provider="deepseek", api_key_env="DEEPSEEK_KEY"),
    ]
    ladder = build_ladder(specs, transport=_fake_transport, env={"DEEPSEEK_KEY": "d"})
    assert [r.name for r in ladder.rungs] == ["local", "deepseek"]


def test_default_specs_are_cost_ordered_shape():
    assert DEFAULT_LADDER_SPECS[0].is_local is True
    assert [s.tier for s in DEFAULT_LADDER_SPECS][-1] == "fable"
