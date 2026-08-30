"""LLM Reasoning (spec §7) — builds the grounded prompt and calls the LLM provider.

No provider-specific logic here — that lives entirely behind
``app.ai.llm.provider.LLMProvider``.
"""
from __future__ import annotations

import logging

from app.ai.llm.provider import LLMCompletion, complete_with_retry, get_llm_provider
from app.ai.prompts.templates import build_system_prompt, build_user_prompt
from app.ai.schemas.intent import QueryIntent
from app.core.config import LLMSettings

logger = logging.getLogger("codesage.ai.engine.reasoning")


async def generate_answer(
    *, llm_settings: LLMSettings, intent: QueryIntent, context_text: str, query: str, is_retry: bool = False,
) -> LLMCompletion:
    """Run one repository-grounded reasoning call.

    Provider construction (``get_llm_provider()``) happens inside this
    function, not in the orchestrator — so a test that monkeypatches
    ``generate_answer`` itself never touches the real provider (which
    requires a configured API key), while production code still gets a
    provider without the orchestrator needing to know how one is built.

    Args:
        llm_settings: Provider call-tuning settings (retries/timeout/backoff).
        intent: The classified query intent — selects the intent-specific
            system-prompt instruction.
        context_text: The formatted evidence block (see ``ai/engine/context.py``).
        query: The user's raw question.
        is_retry: Whether this is the bounded verification-triggered
            retry — uses a stricter system prompt reminding the model
            to cite only the (now broadened) evidence.

    Returns:
        The model's completion.

    Raises:
        app.ai.exceptions.LLMTimeoutError: If every attempt times out.
        app.ai.exceptions.LLMProviderError: If every attempt fails for any other reason.
    """
    provider = get_llm_provider()
    system_prompt = build_system_prompt(intent, is_retry=is_retry)
    user_prompt = build_user_prompt(context_text, query)
    logger.debug("Reasoning call: provider=%s model=%s intent=%s retry=%s", provider.provider_name, provider.model, intent.value, is_retry)
    return await complete_with_retry(provider, system_prompt, user_prompt, llm_settings)
