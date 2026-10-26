#!/bin/bash
# Local knowledge service for the dev panel (scripts/dev/dev-panel.sh expects it on :58181).
# The vault is mounted read-only; embeddings are fake (UI work without Ollama).
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "${AIHUB_DEV_ROOT:-$HERE/../..}"
V=${AIHUB_DEV_VENV:-~/.venvs/aihub-dev-knowledge}
[ -d "$V" ] || python3 -m venv "$V"
. "$V/bin/activate"
pip install -q -e packages/contracts -e services/knowledge 2>&1 | grep -v notice || true
pw=$(mktemp); trap 'rm -f "$pw"' EXIT; printf 'aihub-dev-only' > "$pw"  # dev DB password, per runtime contract
export AIHUB_DATABASE_URL=postgresql+psycopg://aihub@127.0.0.1:55432/${AIHUB_DEV_DB:-aihub_dev} AIHUB_DB_PASSWORD_FILE=$pw
export AIHUB_INTERNAL_SECRET=dev-internal-secret-0123456789abcd AIHUB_EMBED_BACKEND=fake
export AIHUB_QDRANT_URL=http://127.0.0.1:56333 AIHUB_VAULT_DIR="${AIHUB_DEV_VAULT:?set AIHUB_DEV_VAULT to an Obsidian vault (read-only)}"
cd services/knowledge && python -m alembic upgrade head >/dev/null
exec python -m uvicorn aihub_knowledge.api:app --host 127.0.0.1 --port ${AIHUB_DEV_KNOWLEDGE_PORT:-58181}
