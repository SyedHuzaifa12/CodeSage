"""Unit tests for the report cache-key generation (spec §13/§19 — repository isolation)."""
from __future__ import annotations

import uuid

from app.core.config import LLMSettings
from app.reports.cache import build_cache_key


class TestBuildCacheKey:
    def test_key_includes_repository_id(self) -> None:
        repository_id = uuid.uuid4()
        key = build_cache_key(repository_id=repository_id, report_type="summary", repository_version="v1")
        assert str(repository_id) in key

    def test_different_repositories_get_different_keys(self) -> None:
        key_a = build_cache_key(repository_id=uuid.uuid4(), report_type="summary", repository_version="v1")
        key_b = build_cache_key(repository_id=uuid.uuid4(), report_type="summary", repository_version="v1")
        assert key_a != key_b

    def test_different_report_types_get_different_keys(self) -> None:
        repository_id = uuid.uuid4()
        key_summary = build_cache_key(repository_id=repository_id, report_type="summary", repository_version="v1")
        key_architecture = build_cache_key(repository_id=repository_id, report_type="architecture", repository_version="v1")
        assert key_summary != key_architecture

    def test_different_repository_versions_get_different_keys(self) -> None:
        repository_id = uuid.uuid4()
        key_v1 = build_cache_key(repository_id=repository_id, report_type="summary", repository_version="v1")
        key_v2 = build_cache_key(repository_id=repository_id, report_type="summary", repository_version="v2")
        assert key_v1 != key_v2

    def test_same_inputs_are_deterministic(self) -> None:
        repository_id = uuid.uuid4()
        key_1 = build_cache_key(repository_id=repository_id, report_type="summary", repository_version="v1")
        key_2 = build_cache_key(repository_id=repository_id, report_type="summary", repository_version="v1")
        assert key_1 == key_2

    def test_different_llm_model_gets_different_key(self) -> None:
        repository_id = uuid.uuid4()
        settings_a = LLMSettings(groq_model="model-a")
        settings_b = LLMSettings(groq_model="model-b")
        key_a = build_cache_key(repository_id=repository_id, report_type="architecture", repository_version="v1", llm_settings=settings_a)
        key_b = build_cache_key(repository_id=repository_id, report_type="architecture", repository_version="v1", llm_settings=settings_b)
        assert key_a != key_b
