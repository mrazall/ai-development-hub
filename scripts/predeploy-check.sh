#!/bin/bash
# predeploy-check.sh — everything that must pass before a deploy: lint, unit/integration tests of the three
# Python parts (including the user-scenario tests with a real worker), web prettier/lint/types.
# Runs inside the Linux/WSL dev checkout. Needs the dev Postgres (scripts/dev) and per-part venvs:
#   AIHUB_VENV_CONTROL, AIHUB_VENV_AGENTS, AIHUB_VENV_KNOWLEDGE, AIHUB_VENV_MCP (default: <part>/.venv)
#   AIHUB_TEST_DB (default postgresql+psycopg://aihub:aihub-dev-only@127.0.0.1:55432/aihub_predeploy)
#   AIHUB_TEST_PG_CONTAINER (default aihub-dev-pg) — the database is recreated for every run.
set -uo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
DB_NAME=aihub_predeploy
DB=${AIHUB_TEST_DB:-postgresql+psycopg://aihub:aihub-dev-only@127.0.0.1:55432/$DB_NAME}
PG=${AIHUB_TEST_PG_CONTAINER:-aihub-dev-pg}
VC=${AIHUB_VENV_CONTROL:-$ROOT/services/control-plane/.venv}
VA=${AIHUB_VENV_AGENTS:-$ROOT/packages/agent-adapters/.venv}
VK=${AIHUB_VENV_KNOWLEDGE:-$ROOT/services/knowledge/.venv}
VM=${AIHUB_VENV_MCP:-$ROOT/packages/mcp-knowledge/.venv}
fail=0
step() { echo "== $1"; }
check() { if [ "$1" -ne 0 ]; then echo "!! $2 failed"; fail=1; fi; }

docker exec "$PG" dropdb -U aihub --if-exists "$DB_NAME" >/dev/null && docker exec "$PG" createdb -U aihub "$DB_NAME"
export AIHUB_DATABASE_URL=$DB AIHUB_REQUIRE_INTEGRATION=1
# The packages of THIS checkout come first: an editable install in a venv may point at another worktree.
PKGS=$ROOT/packages/contracts:$ROOT/packages/agent-adapters:$ROOT/packages/mcp-knowledge/src

step "control-plane (ruff + tests, incl. user scenarios)"
(cd "$ROOT/services/control-plane" && "$VC/bin/ruff" check -q . && PYTHONPATH=.:$PKGS "$VC/bin/python" -m pytest -q -p no:cacheprovider 2>&1 | tail -3; exit "${PIPESTATUS[0]}")
check $? control-plane
step "agent-adapters"
(cd "$ROOT/packages/agent-adapters" && PYTHONPATH=.:$ROOT/packages/contracts "$VA/bin/python" -m pytest -q -p no:cacheprovider 2>&1 | tail -2; exit "${PIPESTATUS[0]}")
check $? agent-adapters
step "knowledge (ruff + tests)"
(cd "$ROOT/services/knowledge" && "$VC/bin/ruff" check -q . && PYTHONPATH=src "$VK/bin/python" -m pytest -q -p no:cacheprovider 2>&1 | tail -2; exit "${PIPESTATUS[0]}")
check $? knowledge
step "mcp-knowledge"
(cd "$ROOT/packages/mcp-knowledge" && PYTHONPATH=src "$VM/bin/python" -m pytest -q -p no:cacheprovider 2>&1 | tail -2; exit "${PIPESTATUS[0]}")
check $? mcp-knowledge
step "web (prettier, lint, types)"
(cd "$ROOT/apps/web" && npx prettier --check src e2e >/dev/null && npm run -s lint >/dev/null && npm run -s typecheck >/dev/null)
check $? web

if [ "$fail" -ne 0 ]; then echo "PREDEPLOY: FAILED"; exit 1; fi
echo "PREDEPLOY: OK"
