"""Unit tests for the LLM provider abstraction's retry/backoff logic (Sprint 5)."""
from __future__ import annotations

import asyncio

import pytest

from app.ai.exceptions import LLMProviderError, LLMTimeoutError
from app.ai.llm.provider import LLMCompletion, complete_with_retry
from app.core.config import Settings


def make_llm_settings(**overrides):
    settings = Settings().llm
    for key, value in overrides.items():
        setattr(settings, key, value)
    return settings


class _AlwaysFailsProvider:
    provider_name = "fake"
    model = "fake-model"
    call_count = 0

    async def complete(self, system_prompt: str, user_prompt: str) -> LLMCompletion:
        self.call_count += 1
        raise RuntimeError("simulated provider failure")


class _AlwaysTimesOutProvider:
    provider_name = "fake"
    model = "fake-model"
    call_count = 0

    async def complete(self, system_prompt: str, user_prompt: str) -> LLMCompletion:
        self.call_count += 1
        await asyncio.sleep(10)  # longer than the test's configured timeout
        return LLMCompletion(text="never reached", provider=self.provider_name, model=self.model)


class _FailsOnceThenSucceedsProvider:
    provider_name = "fake"
    model = "fake-model"

    def __init__(self) -> None:
        self.call_count = 0

    async def complete(self, system_prompt: str, user_prompt: str) -> LLMCompletion:
        self.call_count += 1
        if self.call_count == 1:
            raise RuntimeError("transient failure")
        return LLMCompletion(text="ok", provider=self.provider_name, model=self.model)


class TestCompleteWithRetry:
    async def test_succeeds_on_first_try(self) -> None:
        class _Provider:
            provider_name = "fake"
            model = "fake-model"

            async def complete(self, system_prompt, user_prompt):
                return LLMCompletion(text="answer", provider=self.provider_name, model=self.model)

        settings = make_llm_settings(llm_max_retries=2, llm_retry_backoff_seconds=0.01, llm_timeout_seconds=5.0)
        result = await complete_with_retry(_Provider(), "system", "user", settings)
        assert result.text == "answer"

    async def test_retries_transient_failure_then_succeeds(self) -> None:
        provider = _FailsOnceThenSucceedsProvider()
        settings = make_llm_settings(llm_max_retries=2, llm_retry_backoff_seconds=0.01, llm_timeout_seconds=5.0)
        result = await complete_with_retry(provider, "system", "user", settings)
        assert result.text == "ok"
        assert provider.call_count == 2

    async def test_exhausts_retries_and_raises_provider_error(self) -> None:
        provider = _AlwaysFailsProvider()
        settings = make_llm_settings(llm_max_retries=2, llm_retry_backoff_seconds=0.01, llm_timeout_seconds=5.0)
        with pytest.raises(LLMProviderError):
            await complete_with_retry(provider, "system", "user", settings)
        assert provider.call_count == 3  # initial attempt + 2 retries

    async def test_timeout_raises_llm_timeout_error(self) -> None:
        provider = _AlwaysTimesOutProvider()
        settings = make_llm_settings(llm_max_retries=0, llm_retry_backoff_seconds=0.01, llm_timeout_seconds=0.05)
        with pytest.raises(LLMTimeoutError):
            await complete_with_retry(provider, "system", "user", settings)

    async def test_zero_retries_means_exactly_one_attempt(self) -> None:
        provider = _AlwaysFailsProvider()
        settings = make_llm_settings(llm_max_retries=0, llm_retry_backoff_seconds=0.01, llm_timeout_seconds=5.0)
        with pytest.raises(LLMProviderError):
            await complete_with_retry(provider, "system", "user", settings)
        assert provider.call_count == 1


class TestGroqProviderConstruction:
    def test_raises_without_api_key(self) -> None:
        from app.ai.llm.provider import GroqProvider

        settings = make_llm_settings(groq_api_key=None)
        with pytest.raises(ValueError):
            GroqProvider(settings)
