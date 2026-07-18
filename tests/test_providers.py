from sift.providers import ChatMessage, ProviderConfig, build_provider, provider_config


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
