#!/usr/bin/env bash
# Provisions the dev container: uv, backend dependencies, frontend dependencies.
# Kept in a script rather than inline in devcontainer.json so that quoting and
# pipes survive whichever editor drives the container.
set -euo pipefail

cd "$(dirname "$0")/.."

export UV_INSTALL_DIR="${HOME}/.local/bin"
export PATH="${UV_INSTALL_DIR}:${PATH}"

if ! command -v uv >/dev/null 2>&1; then
  echo "==> installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
uv --version

# The named volumes mount as root-owned; hand them to the container user.
for d in backend/.venv frontend/node_modules; do
  if [ -d "$d" ] && [ ! -w "$d" ]; then
    sudo chown "$(id -u):$(id -g)" "$d"
  fi
done

echo "==> backend dependencies (all extras, so pyright resolves every adapter)"
(cd backend && uv sync --all-extras)

echo "==> frontend dependencies"
(cd frontend && npm install)

echo "==> dev container ready"
