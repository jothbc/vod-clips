#!/usr/bin/env bash
# Create .venv and pip install Reels (Linux / WSL / macOS).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
PY="$(command -v python3 || command -v python)"
exec "${PY}" "${ROOT}/scripts/install_deps.py" "$@"
