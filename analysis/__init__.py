"""Report offline dell'impianto: legge uno snapshot, non importa solarmon."""
VERSION = "1.0"
DEFAULT_TZ = "Europe/Rome"
SITE_LAT = 41.20187970064
SITE_LON = 13.849261783999081


class ReportError(Exception):
    """Errore leggibile: il CLI lo stampa ed esce con codice 2."""
