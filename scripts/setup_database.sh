#!/usr/bin/env bash
# One-time PostgreSQL setup: creates the project role and database defined in .env.
# You will be prompted for the password of the PostgreSQL superuser (default: postgres).
#
# Usage: scripts/setup_database.sh [superuser]

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUPERUSER="${1:-postgres}"

if [[ ! -f "${PROJECT_ROOT}/.env" ]]; then
  echo "ERROR: ${PROJECT_ROOT}/.env not found. Copy .env.example to .env first." >&2
  exit 1
fi
set -a
# shellcheck disable=SC1091
source "${PROJECT_ROOT}/.env"
set +a

# Prefer the PostgreSQL 17 client installed with the server.
PSQL="/Library/PostgreSQL/17/bin/psql"
[[ -x "${PSQL}" ]] || PSQL="$(command -v psql)"

echo "Creating role '${POSTGRES_USER}' and database '${POSTGRES_DB}' on ${POSTGRES_HOST}:${POSTGRES_PORT} as '${SUPERUSER}'."
"${PSQL}" \
  --host "${POSTGRES_HOST}" --port "${POSTGRES_PORT}" \
  --username "${SUPERUSER}" --dbname postgres \
  --set ON_ERROR_STOP=1 \
  --set app_user="${POSTGRES_USER}" \
  --set app_password="${POSTGRES_PASSWORD}" \
  --set app_db="${POSTGRES_DB}" \
  --quiet \
  --file "${PROJECT_ROOT}/sql/setup_database.sql"

echo "Done. The pipeline will connect as '${POSTGRES_USER}' using the password in .env."
