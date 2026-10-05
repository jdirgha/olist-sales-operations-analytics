#!/usr/bin/env bash
# Reset the password of the PostgreSQL 17 superuser 'postgres' (EDB installer, macOS).
#
# How it works:
#   1. Backs up pg_hba.conf.
#   2. Temporarily allows the 'postgres' user to connect from this machine without a password.
#   3. Sets the new password you type (hidden input).
#   4. Restores the original pg_hba.conf - always, even if a step fails.
#
# Usage: sudo scripts/reset_postgres_password.sh

set -euo pipefail

PG_HOME="/Library/PostgreSQL/17"
PG_DATA="${PG_HOME}/data"
HBA="${PG_DATA}/pg_hba.conf"
BACKUP="${PG_DATA}/pg_hba.conf.before_reset"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run with sudo: sudo $0" >&2
  exit 1
fi
if [[ ! -f "${HBA}" ]]; then
  echo "ERROR: ${HBA} not found." >&2
  exit 1
fi

read -r -s -p "New password for PostgreSQL user 'postgres': " NEW_PASSWORD; echo
read -r -s -p "Repeat new password: " CONFIRM_PASSWORD; echo
if [[ -z "${NEW_PASSWORD}" || "${NEW_PASSWORD}" != "${CONFIRM_PASSWORD}" ]]; then
  echo "ERROR: passwords are empty or do not match." >&2
  exit 1
fi

reload() { sudo -u postgres "${PG_HOME}/bin/pg_ctl" reload -D "${PG_DATA}" >/dev/null; }

restore() {
  if [[ -f "${BACKUP}" ]]; then
    cat "${BACKUP}" > "${HBA}"
    rm -f "${BACKUP}"
    reload
    echo "Original authentication settings restored."
  fi
}
trap restore EXIT

cp -p "${HBA}" "${BACKUP}"
{
  echo "# temporary - removed automatically by reset_postgres_password.sh"
  echo "host all postgres 127.0.0.1/32 trust"
  echo "host all postgres ::1/128 trust"
  cat "${BACKUP}"
} > "${HBA}"
reload
sleep 1

"${PG_HOME}/bin/psql" --host localhost --username postgres --dbname postgres \
  --no-psqlrc --quiet --set ON_ERROR_STOP=1 --set new_password="${NEW_PASSWORD}" \
  <<'SQL'
ALTER USER postgres WITH PASSWORD :'new_password';
SQL

echo "Password for 'postgres' updated."
