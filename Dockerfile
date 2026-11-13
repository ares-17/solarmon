FROM python:3.12-slim

LABEL maintainer="solarmon" \
      description="Monitoraggio inverter solare Voltronic/Axpert (protocollo PI30)"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    IN_DOCKER=1 \
    PORT=8000 \
    DB_PATH=/var/lib/solarmon/solar.db \
    INVERTER_DEV=/dev/inverter

# Dipendenza opzionale per pubblicazione MQTT
RUN pip install --no-cache-dir paho-mqtt

# Utente di sistema non-root dedicato
RUN groupadd -r solarmon && \
    useradd -r -g solarmon -d /var/lib/solarmon -s /usr/sbin/nologin solarmon && \
    mkdir -p /var/lib/solarmon /app && \
    chown -R solarmon:solarmon /var/lib/solarmon

WORKDIR /app

COPY solarmon.py index.html docker-entrypoint.sh /app/
RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 8000

VOLUME ["/var/lib/solarmon"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python3 -c "import urllib.request, os; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/api/now', timeout=3)" || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["python3", "/app/solarmon.py"]
