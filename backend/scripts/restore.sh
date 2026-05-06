#!/usr/bin/env bash
# QueryWise PostgreSQL Restore Script
# Usage: ./restore.sh <backup_file>

set -euo pipefail

BACKUP_FILE="${1:?Usage: ./restore.sh <backup_file>}"
DB_HOST="${PGHOST:-localhost}"
DB_PORT="${PGPORT:-5434}"
DB_NAME="${PGDATABASE:-saras_metadata}"
DB_USER="${PGUSER:-parthy}"

echo "WARNING: This will restore ${DB_NAME} from ${BACKUP_FILE}"
echo "Press Ctrl+C within 5 seconds to cancel..."
sleep 5

gunzip -c "${BACKUP_FILE}" | pg_restore \
  -h "${DB_HOST}" \
  -p "${DB_PORT}" \
  -U "${DB_USER}" \
  -d "${DB_NAME}" \
  --no-password \
  --clean \
  --if-exists

echo "Restore complete."
