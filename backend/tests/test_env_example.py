"""Anti-drift guard: every Settings field must appear in the root .env.example.

Extra keys (e.g. COMPOSE_PROFILES, read by docker compose itself) are allowed;
missing keys are not — the env template can never lag behind the code.
"""

from pathlib import Path

from sovereign_rag.config import Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"


def test_env_example_covers_all_settings_fields() -> None:
    keys: set[str] = set()
    for raw_line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        keys.add(line.split("=", 1)[0].strip())
    expected = {name.upper() for name in Settings.model_fields}
    missing = expected - keys
    assert not missing, f".env.example is missing keys: {sorted(missing)}"
