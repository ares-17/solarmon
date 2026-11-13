#!/usr/bin/env bash
set -euo pipefail

APP_DIR=/opt/solarmon
STATE_DIR=/var/lib/solarmon
ENV_FILE=/etc/solarmon.env
SERVICE_USER=solarmon
SERVICE_GROUP=solarmon
INVERTER_GROUP=inverter
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ ${EUID} -ne 0 ]]; then
  echo "esegui con sudo: sudo bash setup.sh" >&2
  exit 1
fi

for file in solarmon.py index.html solarmon.env.example \
            deploy/solarmon.service deploy/99-inverter.rules deploy/backup.sh \
            deploy/solarmon-backup.service deploy/solarmon-backup.timer; do
  if [[ ! -f "$SRC_DIR/$file" ]]; then
    echo "file mancante: $file" >&2
    exit 1
  fi
done

apt-get update
apt-get install -y python3 python3-venv sqlite3

getent group "$INVERTER_GROUP" >/dev/null || groupadd --system "$INVERTER_GROUP"
getent group "$SERVICE_GROUP" >/dev/null || groupadd --system "$SERVICE_GROUP"
id -u "$SERVICE_USER" >/dev/null 2>&1 || useradd --system --gid "$SERVICE_GROUP" \
  --home-dir /nonexistent --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
usermod -aG "$INVERTER_GROUP" "$SERVICE_USER"

install -d -m 755 -o root -g root "$APP_DIR"
install -m 644 "$SRC_DIR/solarmon.py" "$APP_DIR/solarmon.py"
install -m 644 "$SRC_DIR/index.html" "$APP_DIR/index.html"
install -m 755 "$SRC_DIR/deploy/backup.sh" "$APP_DIR/backup.sh"

if [[ ! -x "$APP_DIR/.venv/bin/python" ]]; then
  python3 -m venv "$APP_DIR/.venv"
fi

install -d -m 750 -o "$SERVICE_USER" -g "$SERVICE_GROUP" "$STATE_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
  install -m 600 -o root -g root "$SRC_DIR/solarmon.env.example" "$ENV_FILE"
  echo "configura $ENV_FILE: TG_TOKEN, TG_CHAT, TG_ADMIN_ID, BIND_ADDR"
fi

install -m 644 "$SRC_DIR/deploy/99-inverter.rules" /etc/udev/rules.d/99-inverter.rules
udevadm control --reload
udevadm trigger --subsystem-match=hidraw

install -m 644 "$SRC_DIR/deploy/solarmon.service" /etc/systemd/system/solarmon.service
install -m 644 "$SRC_DIR/deploy/solarmon-backup.service" /etc/systemd/system/solarmon-backup.service
install -m 644 "$SRC_DIR/deploy/solarmon-backup.timer" /etc/systemd/system/solarmon-backup.timer

systemctl daemon-reload
systemctl enable solarmon.service
systemctl enable --now solarmon-backup.timer
systemctl restart solarmon.service

echo "installato. Verifica: systemctl status solarmon"
