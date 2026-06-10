#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/crypto_signal_bot}"
DB_PATH="${DATABASE_PATH:-${APP_DIR}/data/crypto_signal_bot.sqlite}"
BACKUP_DIR="${BACKUP_DIR:-${APP_DIR}/data/backups}"
BACKUP_KEEP_DAYS="${BACKUP_KEEP_DAYS:-7}"

mkdir -p "${BACKUP_DIR}"

if [ ! -f "${DB_PATH}" ]; then
  echo "SQLite database not found: ${DB_PATH}" >&2
  exit 1
fi

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_base="${BACKUP_DIR}/crypto_signal_bot_${timestamp}.sqlite"

if command -v sqlite3 >/dev/null 2>&1; then
  sqlite3 "${DB_PATH}" ".backup '${backup_base}'"
else
  cp "${DB_PATH}" "${backup_base}"
fi

gzip -9 "${backup_base}"
find "${BACKUP_DIR}" -name 'crypto_signal_bot_*.sqlite.gz' -mtime "+${BACKUP_KEEP_DAYS}" -delete

echo "Created ${backup_base}.gz"
