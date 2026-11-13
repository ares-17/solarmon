#!/bin/sh
set -e

# Se il container è avviato come root (default)
if [ "$(id -u)" = "0" ]; then
    DB_DIR=$(dirname "${DB_PATH:-/var/lib/solarmon/solar.db}")
    mkdir -p "$DB_DIR"
    chown -R solarmon:solarmon "$DB_DIR" 2>/dev/null || true

    # Adatta i permessi del device seriale/USB se presente
    DEV="${INVERTER_DEV:-/dev/inverter}"
    if [ -e "$DEV" ]; then
        DEV_GID=$(stat -c '%g' "$DEV" 2>/dev/null || echo "0")
        if [ "$DEV_GID" != "0" ]; then
            if ! getent group "$DEV_GID" >/dev/null 2>&1; then
                groupadd -g "$DEV_GID" inverter_dev 2>/dev/null || true
            fi
            usermod -aG "$DEV_GID" solarmon 2>/dev/null || true
        else
            chmod 666 "$DEV" 2>/dev/null || true
        fi
    fi

    # Esegue come utente solarmon mantenendo propagazione segnali e gruppi
    exec setpriv --reuid=solarmon --regid=solarmon --init-groups "$@"
fi

# Se avviato già come utente non-root (--user)
exec "$@"
