"""Tests for environment-driven settings and their cross-field validation."""

import importlib.util
import os
from importlib.machinery import ModuleSpec
from typing import Any

import pytest
from pydantic import ValidationError

from sovereign_rag.config import Settings


def _settings(**overrides: Any) -> Settings:
    """Build Settings without reading .env (pyright cannot see BaseSettings' _env_file)."""
    return Settings(_env_file=None, **overrides)  # pyright: ignore[reportCallIssue]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip every real environment variable that maps to a Settings field.

    Guarantees each test sees exactly the environment it builds, regardless of
    what is exported in the developer's shell or in CI.
    """
    field_env_names = {name.upper() for name in Settings.model_fields}
    for key in list(os.environ):
        if key.upper() in field_env_names:
            monkeypatch.delenv(key, raising=False)


def test_defaults_load_with_empty_env() -> None:
    settings = _settings()
    assert settings.app_env == "dev"
    assert settings.log_level == "INFO"
    assert settings.database_url == "postgresql://rag:rag@localhost:5432/rag"
    assert settings.llm_provider == "ollama"
    assert settings.ollama_base_url == "http://localhost:11434"
    assert settings.ollama_model == "qwen3:4b-instruct"
    assert settings.ollama_keep_alive == "10m"
    assert settings.ollama_think is False
    assert settings.azure_openai_api_version == "2024-10-21"
    assert settings.embedding_provider == "local"
    assert settings.embedding_model == "intfloat/multilingual-e5-small"
    assert settings.embedding_dimensions == 384
    assert settings.vector_store == "pgvector"
    assert settings.chunk_size == 1200
    assert settings.chunk_overlap == 200
    assert settings.retrieval_top_k == 8
    assert settings.retrieval_candidates == 40
    assert settings.rrf_k == 60
    assert settings.hnsw_ef_search == 80
    assert settings.max_upload_mb == 25
    assert settings.cors_origins == ["http://localhost:5173"]
    assert settings.seed_demo_data is False
    assert settings.auth_admin_users == set()


def test_azure_llm_requires_endpoint_and_deployment() -> None:
    with pytest.raises(ValidationError) as exc_info:
        _settings(llm_provider="azure_openai")
    expected = (
        "LLM_PROVIDER=azure_openai requires AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_CHAT_DEPLOYMENT"
    )
    assert expected in str(exc_info.value)


def test_openai_compatible_requires_base_url_and_model() -> None:
    with pytest.raises(ValidationError) as exc_info:
        _settings(llm_provider="openai_compatible")
    expected = (
        "LLM_PROVIDER=openai_compatible requires OPENAI_COMPAT_BASE_URL and OPENAI_COMPAT_MODEL"
    )
    assert expected in str(exc_info.value)


def test_azure_embeddings_require_embedding_deployment() -> None:
    with pytest.raises(ValidationError) as exc_info:
        _settings(
            embedding_provider="azure_openai",
            azure_openai_endpoint="https://example.openai.azure.com",
        )
    expected = (
        "EMBEDDING_PROVIDER=azure_openai requires AZURE_OPENAI_ENDPOINT "
        "and AZURE_OPENAI_EMBEDDING_DEPLOYMENT"
    )
    assert expected in str(exc_info.value)


def test_hnsw_ef_search_must_cover_retrieval_candidates() -> None:
    with pytest.raises(ValidationError) as exc_info:
        _settings(hnsw_ef_search=10)
    assert "HNSW_EF_SEARCH must be >= RETRIEVAL_CANDIDATES" in str(exc_info.value)


def test_empty_api_keys_raise_in_prod() -> None:
    with pytest.raises(ValidationError) as exc_info:
        _settings(app_env="prod")
    assert "AUTH_API_KEYS must not be empty in prod" in str(exc_info.value)


def test_empty_api_keys_inject_dev_key_in_dev() -> None:
    settings = _settings(app_env="dev")
    assert settings.auth_api_keys == {"dev-only-key": "demo"}


def test_local_embeddings_require_sentence_transformers(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_spec(name: str, package: str | None = None) -> ModuleSpec | None:
        return None

    monkeypatch.setattr(importlib.util, "find_spec", no_spec)
    with pytest.raises(ValidationError) as exc_info:
        _settings()
    assert "uv sync --extra local" in str(exc_info.value)


def test_auth_api_keys_parsed_from_json_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_API_KEYS", '{"sk-demo-alice": "alice", "sk-demo-bob": "bob"}')
    monkeypatch.setenv("AUTH_ADMIN_USERS", '["alice"]')
    settings = _settings()
    assert settings.auth_api_keys == {"sk-demo-alice": "alice", "sk-demo-bob": "bob"}
    assert settings.auth_admin_users == {"alice"}
