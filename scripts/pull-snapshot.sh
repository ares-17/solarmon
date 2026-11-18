#!/usr/bin/env bash
set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Uso: $0 <HOST> [REMOTE_DB_PATH]" >&2
    echo "Esempio: $0 pi ~/solarmon/data/solar.db" >&2
    exit 2
fi

HOST="$1"
REMOTE_DB="${2:-~/solarmon/data/solar.db}"
SNAPSHOT_NAME="$(date +%F).db"
DEST_DIR="snapshots"

mkdir -p "$DEST_DIR"

echo "Esecuzione backup consistente SQLite su ${HOST}:${REMOTE_DB}..."
ssh "$HOST" python3 -c "'import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(\"/tmp/solarmon-snapshot.db\"); s.backup(d); d.close()'" "$REMOTE_DB"

echo "Download snapshot in ${DEST_DIR}/${SNAPSHOT_NAME}..."
scp "$HOST:/tmp/solarmon-snapshot.db" "${DEST_DIR}/${SNAPSHOT_NAME}"

echo "Pulizia file temporaneo su ${HOST}..."
ssh "$HOST" rm -f /tmp/solarmon-snapshot.db

echo "Completato: ${DEST_DIR}/${SNAPSHOT_NAME}"
