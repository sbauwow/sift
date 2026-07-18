from sift.providers import ChatMessage, ProviderConfig, build_provider, model_pricing, provider_config


def test_builds_github_copilot_provider_from_config():
    provider = build_provider(
        ProviderConfig(
            name="copilot",
            model="gpt-5-mini",
            endpoint="https://api.githubcopilot.com/chat/completions",
            api_key="test-token",
        )
    )

    assert provider.name == "copilot"
    assert provider.model == "gpt-5-mini"
    assert provider.endpoint == "https://api.githubcopilot.com/chat/completions"


def test_provider_prepares_openai_compatible_chat_request():
    provider = build_provider(
        ProviderConfig(
            name="vllm",
            model="Qwen/Qwen2.5-Coder-7B-Instruct",
            endpoint="http://localhost:8000/v1/chat/completions",
            api_key="local-token",
        )
    )

    request = provider.prepare_chat_request(
        [ChatMessage(role="user", content="write a regex for hex colors")],
        temperature=0.2,
    )

    assert request.url == "http://localhost:8000/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer local-token"
    assert request.json == {
        "model": "Qwen/Qwen2.5-Coder-7B-Instruct",
        "messages": [{"role": "user", "content": "write a regex for hex colors"}],
        "temperature": 0.2,
    }


def test_provider_config_has_builtin_presets_for_supported_backends():
    assert provider_config("copilot", api_key="x").model == "gpt-5-mini"
    assert provider_config("copilot", model="gpt-5-mini", api_key="x").endpoint == "https://api.githubcopilot.com/chat/completions"
    assert provider_config("vllm", model="qwen", api_key="x").endpoint == "http://localhost:8000/v1/chat/completions"
    assert provider_config("llmd", model="qwen", api_key="x").endpoint == "http://localhost:8080/v1/chat/completions"
    assert provider_config("opencode", model="qwen", api_key="x").endpoint == "http://localhost:4096/v1/chat/completions"


def test_provider_config_has_anthropic_claude_preset():
    config = provider_config("anthropic", api_key="x")

    assert config.model == "claude-sonnet-4-6"
    assert config.endpoint == "https://api.anthropic.com/v1/messages"


def test_anthropic_default_uses_claude_4_6_without_temperature():
    provider = build_provider(provider_config("anthropic", api_key="x"))

    request = provider.prepare_chat_request(
        [ChatMessage(role="user", content="write a regex for hex colors")],
        temperature=0.2,
    )

    assert request.json["model"] == "claude-sonnet-4-6"
    assert "temperature" not in request.json


def test_anthropic_provider_prepares_messages_request():
    provider = build_provider(provider_config("claude", api_key="anthropic-key"))

    request = provider.prepare_chat_request(
        [
            ChatMessage(role="system", content="Be terse."),
            ChatMessage(role="user", content="write a regex for hex colors"),
        ],
        temperature=0.2,
    )

    assert request.url == "https://api.anthropic.com/v1/messages"
    assert request.headers["x-api-key"] == "anthropic-key"
    assert request.headers["anthropic-version"] == "2023-06-01"
    assert "Authorization" not in request.headers
    assert request.json == {
        "model": "claude-sonnet-4-6",
        "max_tokens": 4096,
        "system": "Be terse.",
        "messages": [{"role": "user", "content": "write a regex for hex colors"}],
    }


def test_provider_config_has_chinese_provider_presets():
    expected = {
        "deepseek": ("deepseek-chat", "https://api.deepseek.com/chat/completions"),
        "qwen": ("qwen-plus", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"),
        "moonshot": ("moonshot-v1-8k", "https://api.moonshot.cn/v1/chat/completions"),
        "zhipu": ("glm-4.5", "https://open.bigmodel.cn/api/paas/v4/chat/completions"),
        "yi": ("yi-large", "https://api.lingyiwanwu.com/v1/chat/completions"),
        "baichuan": ("Baichuan4", "https://api.baichuan-ai.com/v1/chat/completions"),
    }

    for provider_name, (model, endpoint) in expected.items():
        config = provider_config(provider_name, api_key="x")
        assert config.model == model
        assert config.endpoint == endpoint


def test_provider_generates_text_through_injected_transport():
    calls = []

    def transport(request):
        calls.append(request)
        return {"choices": [{"message": {"content": "use ^#[0-9a-fA-F]{6}$"}}]}

    provider = build_provider(
        ProviderConfig(
            name="copilot",
            model="gpt-5-mini",
            endpoint="https://api.githubcopilot.com/chat/completions",
            api_key="test-token",
        ),
        transport=transport,
    )

    response = provider.generate([ChatMessage(role="user", content="regex?")])

    assert response.content == "use ^#[0-9a-fA-F]{6}$"
    assert response.model == "gpt-5-mini"
    assert calls[0].json["messages"] == [{"role": "user", "content": "regex?"}]


def test_openai_compatible_provider_parses_usage_with_pricing_table():
    def transport(request):
        return {
            "choices": [{"message": {"content": "use ^#[0-9a-fA-F]{6}$"}}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 2000},
        }

    provider = build_provider(
        ProviderConfig(
            name="copilot",
            model="gpt-5-mini",
            endpoint="https://api.githubcopilot.com/chat/completions",
            api_key="test-token",
        ),
        transport=transport,
    )

    response = provider.generate([ChatMessage(role="user", content="regex?")])

    pricing = model_pricing("gpt-5-mini")
    assert response.usage is not None
    assert response.usage.input_tokens == 1000
    assert response.usage.output_tokens == 2000
    assert response.usage.input_cost_per_million == pricing.input_cost_per_million
    assert response.usage.output_cost_per_million == pricing.output_cost_per_million


def test_anthropic_provider_parses_usage_with_pricing_table():
    def transport(request):
        return {
            "content": [{"type": "text", "text": "use ^#[0-9a-fA-F]{6}$"}],
            "usage": {"input_tokens": 1000, "output_tokens": 2000},
        }

    provider = build_provider(provider_config("anthropic", api_key="anthropic-key"), transport=transport)

    response = provider.generate([ChatMessage(role="user", content="regex?")])

    pricing = model_pricing("claude-sonnet-4-6")
    assert response.usage is not None
    assert response.usage.input_tokens == 1000
    assert response.usage.output_tokens == 2000
    assert response.usage.input_cost_per_million == pricing.input_cost_per_million
    assert response.usage.output_cost_per_million == pricing.output_cost_per_million
