#!/usr/bin/env bash
# QueryWise PostgreSQL Backup Script
# Usage: ./backup.sh [output_dir]
# Reads DB connection from environment or defaults

set -euo pipefail

BACKUP_DIR="${1:-./backups}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
DB_HOST="${PGHOST:-localhost}"
DB_PORT="${PGPORT:-5434}"
DB_NAME="${PGDATABASE:-saras_metadata}"
DB_USER="${PGUSER:-parthy}"
BACKUP_FILE="${BACKUP_DIR}/querywise_${TIMESTAMP}.sql.gz"

mkdir -p "${BACKUP_DIR}"

echo "Starting backup of ${DB_NAME} at ${TIMESTAMP}..."
pg_dump \
  -h "${DB_HOST}" \
  -p "${DB_PORT}" \
  -U "${DB_USER}" \
  -d "${DB_NAME}" \
  --no-password \
  --format=custom \
  | gzip > "${BACKUP_FILE}"

echo "Backup complete: ${BACKUP_FILE}"

# Keep last 30 backups
cd "${BACKUP_DIR}" && ls -t querywise_*.sql.gz | tail -n +31 | xargs -r rm --
echo "Cleanup complete. Retained last 30 backups."
