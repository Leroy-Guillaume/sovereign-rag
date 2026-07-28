"""Application-level exception hierarchy.

Adapters translate transport-level failures (httpx, openai, psycopg) into these
exceptions; nothing outside an adapter ever sees a provider SDK exception.
"""


class SovereignRagError(Exception):
    """Base class for every error raised by this application."""


class ConfigError(SovereignRagError):
    """Invalid or incomplete configuration, detected at startup."""


class ProviderError(SovereignRagError):
    """An external provider (LLM, embeddings, vector store) failed or is unreachable."""


class ExtractionError(SovereignRagError):
    """An uploaded document could not be parsed into extractable text."""


class AuthError(SovereignRagError):
    """Authentication or authorization failed."""
