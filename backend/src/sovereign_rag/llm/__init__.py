"""LLM provider factory.

The only place in the codebase that maps ``Settings.llm_provider`` to a concrete
adapter. Imports are lazy (inside the match branches) so optional dependencies
stay optional: the azure adapter pulls ``azure-identity`` for keyless auth, which
is only installed with ``uv sync --extra azure``.

Adding a provider (see CONTRIBUTING.md, "add an LLM provider in 30 minutes"):
1. Add the value to ``Settings.llm_provider`` -- pyright flags this match as
   non-exhaustive.
2. Write the adapter (``openai_compat.py`` is the commented model, ~80 lines).
3. Add the factory branch below.
4. Append a factory to ``CLIENT_FACTORIES`` in
   ``tests/contract/test_llm_contract.py`` -- the contract suite runs
   automatically against the new implementation.
"""

from typing import assert_never

from sovereign_rag.config import Settings
from sovereign_rag.errors import ConfigError
from sovereign_rag.llm.base import LLMClient


def get_llm_client(settings: Settings) -> LLMClient:
    """Build the LLM client selected by ``settings.llm_provider``."""
    match settings.llm_provider:
        case "ollama":
            from .ollama import OllamaLLM

            return OllamaLLM(settings)
        case "openai_compatible":
            from .openai_compat import OpenAICompatLLM

            return OpenAICompatLLM(settings)
        case "azure_openai":
            try:
                from .azure import AzureOpenAILLM
            except ImportError as exc:
                raise ConfigError(
                    "LLM_PROVIDER=azure_openai in keyless mode requires azure-identity; "
                    "install it with: uv sync --extra azure"
                ) from exc

            return AzureOpenAILLM(settings)
        case _:
            assert_never(settings.llm_provider)
