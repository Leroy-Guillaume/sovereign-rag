"""Default-profile proof: building the app must not load any Azure SDK module.

Complemented by the CI job core-no-azure which runs create_app in a venv
synced without any extra.
"""

import sys

from fakes import FakeEmbedding, FakeLLM, InMemoryVectorStore, make_settings
from sovereign_rag.main import create_app


def test_no_azure_module_loaded_in_default_profile() -> None:
    create_app(
        make_settings(),
        llm=FakeLLM(),
        embedder=FakeEmbedding(),
        store=InMemoryVectorStore(),
    )
    loaded = [m for m in sys.modules if m == "azure" or m.startswith("azure.")]
    assert not loaded, f"Azure modules must not load in the default profile: {loaded}"
