import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from openai import APITimeoutError

from app.agents.client import (
    OpenRouterClient,
    OpenRouterConfigurationError,
    OpenRouterProviderError,
)
from app.core.config import Settings


def configured_settings(**values):
    return Settings(
        openrouter_api_key="test-key",
        openrouter_model="test/model",
        openrouter_base_url="https://openrouter.test/v1",
        openrouter_timeout_seconds=12,
        **values,
    )


def test_missing_api_key_or_model_is_configuration_error():
    with pytest.raises(OpenRouterConfigurationError, match="API_KEY"):
        OpenRouterClient(Settings(openrouter_api_key=None, openrouter_model="m"))
    with pytest.raises(OpenRouterConfigurationError, match="MODEL"):
        OpenRouterClient(Settings(openrouter_api_key="k", openrouter_model=None))


def test_sdk_receives_base_url_timeout_and_retries(monkeypatch):
    factory = MagicMock()
    monkeypatch.setattr("app.agents.client.AsyncOpenAI", factory)
    OpenRouterClient(configured_settings(openrouter_max_retries=4))
    kwargs = factory.call_args.kwargs
    assert kwargs["api_key"] == "test-key"
    assert kwargs["base_url"] == "https://openrouter.test/v1"
    assert kwargs["timeout"] == 12
    assert kwargs["max_retries"] == 4


@pytest.mark.asyncio
async def test_completion_passes_model_messages_and_tools(caplog):
    caplog.set_level(logging.INFO, logger="app.agents.client")
    create = AsyncMock(return_value=object())
    sdk = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    client = OpenRouterClient(configured_settings(), client=sdk)
    messages = [{"role": "user", "content": "research"}]
    tools = [{"type": "openrouter:web_search"}]
    await client.create_completion(messages=messages, tools=tools)
    create.assert_awaited_once_with(model="test/model", messages=messages, tools=tools)
    assert "OpenRouter request started model=test/model web_search=true" in caplog.text
    assert "OpenRouter request completed elapsed=" in caplog.text


@pytest.mark.asyncio
async def test_timeout_is_mapped_to_safe_provider_error():
    error = APITimeoutError(request=httpx.Request("POST", "https://openrouter.test"))
    create = AsyncMock(side_effect=error)
    sdk = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    client = OpenRouterClient(configured_settings(), client=sdk)
    with pytest.raises(OpenRouterProviderError, match="timed out after 12 seconds"):
        await client.create_completion(messages=[])
