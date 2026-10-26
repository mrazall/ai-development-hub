#!/bin/bash
# Local dev panel: the control plane serving a fresh build of apps/web, against the dev Postgres
# (infra/docker-compose.yml, port 55432). Test users admin and viewer are created once; their passwords are
# in scripts/dev/.dev-users (git-ignored). Run from a checkout, or set AIHUB_DEV_ROOT to one.
# Parallel copies: AIHUB_DEV_ROOT, AIHUB_DEV_VENV, AIHUB_DEV_PORT, AIHUB_DEV_KNOWLEDGE_PORT, AIHUB_DEV_DB, AIHUB_DEV_CREDS.
set -euo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "${AIHUB_DEV_ROOT:-$HERE/../..}"
creds=${AIHUB_DEV_CREDS:-$HERE/.dev-users}
if [ ! -f "$creds" ]; then
  umask 077
  printf 'admin=%s\nviewer=%s\n' "$(openssl rand -hex 12)" "$(openssl rand -hex 12)" > "$creds"
fi
V=${AIHUB_DEV_VENV:-~/.venvs/aihub-dev-cp}
[ -d "$V" ] || python3 -m venv "$V"
. "$V/bin/activate"
pip install -q -e packages/contracts -e services/control-plane 2>&1 | grep -v notice || true
(cd apps/web && npm run -s build >/dev/null)
pw=$(mktemp); trap 'rm -f "$pw"' EXIT; printf 'aihub-dev-only' > "$pw"  # dev DB password, per runtime contract
export AIHUB_DATABASE_URL=postgresql+psycopg://aihub@127.0.0.1:55432/${AIHUB_DEV_DB:-aihub_dev} AIHUB_DB_PASSWORD_FILE=$pw
export AIHUB_SECRET_KEY=dev-panel-secret-key-0123456789abcdef AIHUB_INTERNAL_SECRET=dev-internal-secret-0123456789abcd
export AIHUB_WEB_DIR=$PWD/apps/web/dist AIHUB_KNOWLEDGE_URL=http://127.0.0.1:${AIHUB_DEV_KNOWLEDGE_PORT:-58181}
cd services/control-plane && python -m alembic upgrade head >/dev/null
python - "$creds" <<'PY'
import sys
from aihub_control.auth import hash_password
from aihub_control.db import get_session_factory
from aihub_control.models import User
creds = dict(line.strip().split("=", 1) for line in open(sys.argv[1]) if "=" in line)
_, factory = get_session_factory()
db = factory()
for name, role in (("admin", "admin"), ("viewer", "viewer")):
    user = db.query(User).filter_by(username=name).first()
    if not user:
        db.add(User(username=name, password_hash=hash_password(creds[name]), role=role))
    else:
        # The creds file is the source of truth: a recreated file must not lock the dev panel.
        user.password_hash = hash_password(creds[name])
db.commit()
PY
exec python -m uvicorn aihub_control.main:app --host 127.0.0.1 --port ${AIHUB_DEV_PORT:-58090}
