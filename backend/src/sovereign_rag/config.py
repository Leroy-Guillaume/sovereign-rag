"""Environment-driven application settings.

This is the only module that reads the environment; every other module receives
a ``Settings`` instance explicitly. Any configuration error kills the process at
boot with an exact message - never a deferred failure on first use.
"""

import importlib.util
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="forbid")

    app_env: Literal["dev", "prod"] = "dev"
    log_level: str = "INFO"
    database_url: str = "postgresql://rag:rag@localhost:5432/rag"

    # --- LLM ---
    llm_provider: Literal["ollama", "azure_openai", "openai_compatible"] = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:4b"
    ollama_keep_alive: str = "10m"  # keeps the model warm between questions
    ollama_think: bool = False  # native API flag - disables qwen3 <think> blocks
    openai_compat_base_url: str | None = None  # vLLM, Infomaniak AI Tools, Mistral...
    openai_compat_api_key: SecretStr | None = None
    openai_compat_model: str | None = None
    azure_openai_endpoint: str | None = None
    azure_openai_api_key: SecretStr | None = None  # None => azure-identity (extra [azure])
    azure_openai_chat_deployment: str | None = None
    azure_openai_embedding_deployment: str | None = None
    azure_openai_api_version: str = "2024-10-21"

    # --- Embeddings (FROZEN: switching models invalidates the index - see README) ---
    embedding_provider: Literal["local", "azure_openai"] = "local"
    embedding_model: str = "intfloat/multilingual-e5-small"
    embedding_dimensions: int = 384

    # --- Retrieval ---
    vector_store: Literal["pgvector"] = "pgvector"
    chunk_size: int = 1200  # characters (~300 tokens)
    chunk_overlap: int = 200
    retrieval_top_k: int = 8
    retrieval_candidates: int = 40  # per-leg top-n before RRF fusion
    rrf_k: int = 60  # standard RRF constant (original paper)
    hnsw_ef_search: int = 80

    # --- Auth (Phase 1: multi API keys -> user_id) ---
    auth_api_keys: dict[str, str] = {}  # JSON: {"sk-demo-alice":"alice","sk-demo-bob":"bob"}
    auth_admin_users: set[str] = set()  # JSON: ["alice"]

    # --- Misc ---
    max_upload_mb: int = 25
    cors_origins: list[str] = ["http://localhost:5173"]
    seed_demo_data: bool = False  # ingest data/demo/ at boot if documents table empty
    demo_data_dir: str = "../data/demo"  # demo corpus dir; relative to backend/

    @model_validator(mode="after")
    def check_provider_requirements(self) -> "Settings":
        if self.llm_provider == "azure_openai" and not (
            self.azure_openai_endpoint and self.azure_openai_chat_deployment
        ):
            raise ValueError(
                "LLM_PROVIDER=azure_openai requires AZURE_OPENAI_ENDPOINT "
                "and AZURE_OPENAI_CHAT_DEPLOYMENT"
            )
        if self.llm_provider == "openai_compatible" and not (
            self.openai_compat_base_url and self.openai_compat_model
        ):
            raise ValueError(
                "LLM_PROVIDER=openai_compatible requires OPENAI_COMPAT_BASE_URL "
                "and OPENAI_COMPAT_MODEL"
            )
        if self.embedding_provider == "azure_openai" and not (
            self.azure_openai_endpoint and self.azure_openai_embedding_deployment
        ):
            raise ValueError(
                "EMBEDDING_PROVIDER=azure_openai requires AZURE_OPENAI_ENDPOINT "
                "and AZURE_OPENAI_EMBEDDING_DEPLOYMENT"
            )
        if (
            self.embedding_provider == "local"
            and importlib.util.find_spec("sentence_transformers") is None
        ):
            raise ValueError(
                "EMBEDDING_PROVIDER=local requires the local extra: uv sync --extra local"
            )
        if self.hnsw_ef_search < max(self.retrieval_candidates, self.retrieval_top_k):
            raise ValueError(
                "HNSW_EF_SEARCH must be >= RETRIEVAL_CANDIDATES "
                "(HNSW cannot return more than ef_search candidates)"
            )
        if not self.auth_api_keys:
            if self.app_env == "prod":
                raise ValueError("AUTH_API_KEYS must not be empty in prod")
            self.auth_api_keys = {"dev-only-key": "demo"}  # compose demo, never in prod
        return self
