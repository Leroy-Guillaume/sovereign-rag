# Contributing to sovereign-rag

## Development setup

Prerequisites: Python 3.12, [uv](https://docs.astral.sh/uv/), Node 22, Docker with Compose v2.

```bash
# environment file first: compose refuses to load the project without it
cp .env.example .env

# backend dependencies (dev group included by default; torch comes as CPU-only
# wheels via the pytorch-cpu index; --all-extras so pyright can resolve the azure adapters)
cd backend
uv sync --all-extras

# frontend dependencies
cd ../frontend
npm install

# database only (from the repo root)
# (set POSTGRES_HOST_PORT in .env if another PostgreSQL already owns 5432)
cd ..
docker compose up -d postgres

# run the API with hot reload (from backend/)
cd backend
uv run uvicorn sovereign_rag.main:app --reload

# run the frontend dev server (from frontend/, where Vite proxies /api to :8000)
cd ../frontend
npm run dev
```

Note on env resolution: `Settings` resolves its `.env` file against the current
working directory, so uvicorn started from `backend/` does **not** read the
repo-root `.env`. Without a `backend/.env` the dev API falls back to the
built-in dev defaults: the `dev-only-key` API key and the
`localhost:5432` `DATABASE_URL`. If you want the repo-root values (for example
the `sk-demo` keys or a custom `POSTGRES_HOST_PORT`), copy or link the file
into `backend/`: `cp .env backend/.env`.

## Quality gates

Every PR must pass all of these locally. CI runs the same commands.

Backend (from `backend/`):

```bash
uv run ruff check .            # lint      (fix with: uv run ruff check --fix .)
uv run ruff format --check .   # format    (fix with: uv run ruff format .)
uv run pyright                 # strict type check, 0 errors required
uv run pytest --cov=sovereign_rag   # tests, total coverage must stay >= 80%
```

Tests marked `integration` need a PostgreSQL with pgvector; they **skip cleanly** when the
database is unreachable. To run them, point `TEST_DATABASE_URL` at a scratch database
(default: `postgresql://rag:rag@localhost:5432/rag_test`):

```bash
docker compose exec postgres createdb -U rag rag_test   # first run only
export TEST_DATABASE_URL=postgresql://rag:rag@localhost:5432/rag_test
uv run pytest -m integration
```

(PowerShell: `$env:TEST_DATABASE_URL = "postgresql://rag:rag@localhost:5432/rag_test"`)

Frontend (from `frontend/`):

```bash
npm run lint         # eslint ., 0 problems required
npm run typecheck    # tsc --noEmit, 0 errors required
npm run build        # must succeed
```

## Commit conventions

Conventional commits, English, imperative mood, atomic (one logical change per commit):
`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`.

## Add an LLM provider in 30 minutes

The codebase is designed so that the type checker walks you through this. Say you want to add
a provider called `mistral_api`:

1. **Add the Literal value.** In `backend/src/sovereign_rag/config.py`:

   ```python
   llm_provider: Literal["ollama", "azure_openai", "openai_compatible", "mistral_api"] = "ollama"
   ```

   Run `uv run pyright`. It now FAILS on `backend/src/sovereign_rag/llm/__init__.py`: the
   `match settings.llm_provider` is no longer exhaustive, and the `assert_never(...)` in the
   final `case _:` branch reports the unhandled `"mistral_api"` case. The type checker is now
   your to-do list.

2. **Write the adapter.** `backend/src/sovereign_rag/llm/mistral_api.py` (~80 lines). Use
   `backend/src/sovereign_rag/llm/openai_compat.py` as a commented template. Your class must
   structurally satisfy the `LLMClient` Protocol (`llm/base.py`), with no inheritance needed:

   ```python
   model: str   # e.g. "mistral-small-latest", persisted as "{provider}/{model}"

   def stream_chat(
       self,
       messages: Sequence[ChatMessage],
       *,
       temperature: float = 0.1,
       max_tokens: int = 1024,
   ) -> AsyncIterator[CompletionChunk]: ...   # implement as an async generator

   async def healthcheck(self) -> None: ...   # raises ProviderError when the provider is down
   ```

   Contract: yield at least one chunk, terminate with a final chunk carrying
   `prompt_tokens` / `completion_tokens` when the provider reports them, and wrap EVERY
   transport error in `ProviderError`: httpx/openai exceptions must never leak to callers.

3. **Add the factory branch.** In `backend/src/sovereign_rag/llm/__init__.py`, before the
   `case _:`:

   ```python
   case "mistral_api":
       from .mistral_api import MistralApiLLM

       return MistralApiLLM(settings)
   ```

   `uv run pyright` is green again.

4. **Add the contract case.** In `backend/tests/contract/test_llm_contract.py`, register your
   adapter in the parametrized `CASES` list, mocking its HTTP surface with `respx` like the
   existing three adapters. The whole contract suite (streams chunks, final chunk has usage,
   `ProviderError` on failure, healthcheck behavior) runs automatically against your
   implementation:

   ```bash
   uv run pytest tests/contract/test_llm_contract.py
   ```

If your provider needs new settings fields, add them to `Settings` (with a
`check_provider_requirements` validation branch so misconfiguration fails at boot, not at first
call) and mirror them in `.env.example`, or `tests/test_env_example.py` fails.

## PR checklist

- [ ] `uv run ruff check .` and `uv run ruff format --check .` pass
- [ ] `uv run pyright` reports 0 errors
- [ ] `uv run pytest` green, total coverage >= 80%
- [ ] `npm run lint` and `npm run typecheck` clean (if the frontend is touched)
- [ ] `.env.example` updated for any new `Settings` field
- [ ] Conventional, atomic commit messages
- [ ] No process/spec/plan documents added; committed docs are only README.md, COMPLIANCE.md,
      ARCHITECTURE.md, CONTRIBUTING.md
