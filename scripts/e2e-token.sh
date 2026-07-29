#!/usr/bin/env bash
#
# Mint an API token for the live end-to-end suite.
#
#   export BN_E2E_TOKEN=$(scripts/e2e-token.sh)
#   cd web && npx playwright test --project=live
#
# Deliberately a real token against the running stack: the live suite exists to
# exercise what the mocked suites cannot -- auth, the proxy, serialization and
# the real query path -- so faking the credential would defeat it.
set -euo pipefail

docker compose exec -T web python -c "
from app.db import get_db_direct
from app import api_tokens
from sqlalchemy import text
db = get_db_direct()
uid = db.execute(text('SELECT id FROM users ORDER BY id LIMIT 1')).scalar()
if uid is None:
    raise SystemExit('No user yet. Register one in the browser first.')
print(api_tokens.issue(db, uid, 'live e2e'))
db.commit()
" 2>/dev/null | grep -v '^INFO' | tr -d '\r' | tail -1
