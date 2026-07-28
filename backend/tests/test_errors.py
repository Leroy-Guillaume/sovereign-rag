"""Tests for the application error hierarchy."""

import pytest

from sovereign_rag.errors import (
    AuthError,
    ConfigError,
    ExtractionError,
    ProviderError,
    SovereignRagError,
)


def test_hierarchy_and_str_round_trip() -> None:
    subclasses = (ConfigError, ProviderError, ExtractionError, AuthError)
    for exc_type in subclasses:
        assert issubclass(exc_type, SovereignRagError)
        err = exc_type("something went wrong")
        assert str(err) == "something went wrong"
        with pytest.raises(SovereignRagError, match="something went wrong"):
            raise err
    assert issubclass(SovereignRagError, Exception)
