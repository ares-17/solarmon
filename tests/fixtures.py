"""Risposte reali del protocollo PI30, catturate dall'inverter il 2026-11-13.

Nessun dato identificativo: il numero di serie non è incluso.
"""

# QPIGS — stato istantaneo (233,2 V AC in, 229,7 V out, 339 W carico, 53,90 V batteria,
# 100 %, 39 °C, 103,4 V PV, 383 W PV). Flags: 00110110.
QPIGS = (
    "233.2 50.0 229.7 50.0 0551 0339 011 376 53.90 000 100 0039 0007 "
    "103.4 53.97 00000 00110110 00 00 00383 110"
)

# QMOD — modalità: B = batteria.
QMOD = "B"

# QPIWS — nessun allarme attivo.
QPIWS_CLEAN = "00000000000000000000000000000000"

# QPIWS — bit 7 attivo (tensione di uscita troppo bassa, sospetto errore 58).
QPIWS_LOW_OUTPUT = "00000001000000000000000000000000"

# QPIRI — configurazione: 230 V, 5000 VA/W, batteria 48 V, bulk 56,4 V, float 54,0 V,
# AGM, max carica 20 A, range UPS, uscita SBU, carica solo solare.
QPIRI = (
    "230.0 21.7 230.0 50.0 21.7 5000 5000 48.0 45.0 42.0 56.4 54.0 0 10 020 1 2 3 9 01 0 0 49.0 0 1 000"
)
