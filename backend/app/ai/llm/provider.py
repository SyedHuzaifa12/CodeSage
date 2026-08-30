"""LLM provider abstraction — the AI Engine depends on this interface, never on a vendor SDK directly.

Mirrors the exact pattern already established for the other two
pluggable-model concerns in this codebase:
``knowledge/embedding.py::EmbeddingProvider``/``get_embedding_provider()``
and ``retrieval/reranking.py::RerankProvider``/``get_rerank_provider()``
— a ``Protocol``, one or more concrete implementations, and a
process-wide ``lru_cache``d factory that reads settings internally
(since ``Settings`` is a mutable Pydantic model and therefore not
hashable).
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import httpx

from app.core.config import LLMSettings, get_settings

logger = logging.getLogger("codesage.ai.llm.provider")


@dataclass
class LLMCompletion:
    """One completed LLM call's result and bookkeeping."""

    text: str
    provider: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class LLMProvider(Protocol):
    """Interface every LLM backend must implement."""

    provider_name: str
    model: str

    async def complete(self, system_prompt: str, user_prompt: str) -> LLMCompletion:
        """Run one chat completion.

        Args:
            system_prompt: The grounding/role instructions.
            user_prompt: The evidence block + the user's actual query,
                combined into one user-role message (kept separate from
                ``system_prompt`` at the message-role level, per spec §5/§15).

        Returns:
            The model's response text plus provenance.

        Raises:
            Exception: Any provider-specific failure — the caller
                (``_complete_with_retry``) is responsible for
                retry/backoff and for translating a final failure into
                ``app.ai.exceptions.LLMProviderError``/``LLMTimeoutError``.
        """
        ...


class GroqProvider:
    """Groq-backed provider — the configured primary (ADR-014)."""

    provider_name = "groq"

    def __init__(self, settings: LLMSettings) -> None:
        """Construct the Groq client.

        Args:
            settings: The active LLM settings.

        Raises:
            ValueError: If no API key is configured.
        """
        from groq import AsyncGroq

        if not settings.groq_api_key:
            raise ValueError("GROQ_API_KEY is not configured — set it in .env to use the 'groq' provider.")

        self.model = settings.groq_model
        self._temperature = settings.llm_temperature
        self._max_output_tokens = settings.llm_max_output_tokens
        self._timeout = settings.llm_timeout_seconds
        self._client = AsyncGroq(api_key=settings.groq_api_key.get_secret_value(), timeout=self._timeout)

    async def complete(self, system_prompt: str, user_prompt: str) -> LLMCompletion:
        """Run one chat completion against the Groq API.

        Args:
            system_prompt: The grounding/role instructions.
            user_prompt: The evidence block + user query.

        Returns:
            The model's response text plus token usage.
        """
        response = await self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=self._temperature,
            max_completion_tokens=self._max_output_tokens,
        )
        choice = response.choices[0]
        usage = response.usage
        return LLMCompletion(
            text=choice.message.content or "",
            provider=self.provider_name,
            model=self.model,
            prompt_tokens=usage.prompt_tokens if usage else None,
            completion_tokens=usage.completion_tokens if usage else None,
        )


class OllamaProvider:
    """Local Ollama-backed provider — the configured fallback (ADR-014).

    Implemented via a direct REST call (``httpx``, already a project
    dependency) rather than adding the ``ollama`` package — Ollama's
    HTTP API is small and stable enough that a dedicated SDK isn't
    justified (CLAUDE.md's "no unnecessary infrastructure").
    """

    provider_name = "ollama"

    def __init__(self, settings: LLMSettings) -> None:
        """Construct the Ollama HTTP client.

        Args:
            settings: The active LLM settings.
        """
        self.model = settings.ollama_model
        self._base_url = settings.ollama_base_url
        self._temperature = settings.llm_temperature
        self._max_output_tokens = settings.llm_max_output_tokens
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=settings.llm_timeout_seconds)

    async def complete(self, system_prompt: str, user_prompt: str) -> LLMCompletion:
        """Run one chat completion against a local Ollama server.

        Args:
            system_prompt: The grounding/role instructions.
            user_prompt: The evidence block + user query.

        Returns:
            The model's response text (Ollama's ``/api/chat`` doesn't
            report token usage in the same shape as Groq, so those
            fields are left ``None``).
        """
        response = await self._client.post(
            "/api/chat",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "stream": False,
                "options": {"temperature": self._temperature, "num_predict": self._max_output_tokens},
            },
        )
        response.raise_for_status()
        payload = response.json()
        return LLMCompletion(text=payload.get("message", {}).get("content", ""), provider=self.provider_name, model=self.model)


@lru_cache
def get_llm_provider() -> LLMProvider:
    """Return the process-wide cached LLM provider.

    Returns:
        A ready-to-use provider, per ``LLMSettings.llm_provider``.

    Raises:
        ValueError: If an unrecognized provider is configured, or the
            configured provider is missing required credentials.
    """
    settings = get_settings().llm
    if settings.llm_provider == "groq":
        return GroqProvider(settings)
    if settings.llm_provider == "ollama":
        return OllamaProvider(settings)
    raise ValueError(f"Unknown LLM provider: {settings.llm_provider!r}")


async def complete_with_retry(provider: LLMProvider, system_prompt: str, user_prompt: str, settings: LLMSettings) -> LLMCompletion:
    """Call ``provider.complete`` with bounded retries and exponential backoff.

    Args:
        provider: The LLM provider to call.
        system_prompt: The grounding/role instructions.
        user_prompt: The evidence block + user query.
        settings: The active LLM settings (retry count/backoff/timeout).

    Returns:
        The completion, on the first successful attempt.

    Raises:
        app.ai.exceptions.LLMTimeoutError: If every attempt times out.
        app.ai.exceptions.LLMProviderError: If every attempt fails for any other reason.
    """
    from app.ai.exceptions import LLMProviderError, LLMTimeoutError

    last_exception: Exception | None = None
    for attempt in range(settings.llm_max_retries + 1):
        started = time.perf_counter()
        try:
            return await asyncio.wait_for(provider.complete(system_prompt, user_prompt), timeout=settings.llm_timeout_seconds)
        except asyncio.TimeoutError as exc:
            last_exception = exc
            logger.warning(
                "LLM call timed out (attempt %d/%d, %dms)",
                attempt + 1, settings.llm_max_retries + 1, int((time.perf_counter() - started) * 1000),
            )
        except Exception as exc:  # noqa: BLE001 -- any provider failure is retried the same way
            last_exception = exc
            logger.warning("LLM call failed (attempt %d/%d): %s", attempt + 1, settings.llm_max_retries + 1, exc)

        if attempt < settings.llm_max_retries:
            await asyncio.sleep(settings.llm_retry_backoff_seconds * (2**attempt))

    if isinstance(last_exception, asyncio.TimeoutError):
        raise LLMTimeoutError(f"LLM provider '{provider.provider_name}' timed out after {settings.llm_max_retries + 1} attempts.")
    raise LLMProviderError(f"LLM provider '{provider.provider_name}' failed after {settings.llm_max_retries + 1} attempts: {last_exception}")
