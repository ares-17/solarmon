#!/bin/sh
set -eu

DB="${DB_PATH:-/var/lib/solarmon/solar.db}"
DEST="${BACKUP_DIR:-/var/lib/solarmon/backups}"
KEEP="${BACKUP_KEEP:-14}"
STAMP="$(date +%Y%m%d-%H%M%S)"

[ -f "$DB" ] || exit 0

mkdir -p "$DEST"
sqlite3 "$DB" ".backup '$DEST/solar-$STAMP.db'"
chmod 640 "$DEST/solar-$STAMP.db"
ls -1t "$DEST"/solar-*.db 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f

echo "backup: $DEST/solar-$STAMP.db"
