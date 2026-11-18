"""Lettura dei consumi mensili da bolletta energetica (file CSV)."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from . import ReportError

_MONTH_MAP = {
    "gen": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "mag": 5,
    "giu": 6,
    "lug": 7,
    "ago": 8,
    "set": 9,
    "ott": 10,
    "nov": 11,
    "dic": 12,
}


@dataclass(frozen=True)
class BillRow:
    """Consumo mensile diviso in fasce F1, F2, F3 in kWh."""

    year: int
    month: int
    f1: float
    f2: float
    f3: float

    @property
    def total(self) -> float:
        """Totale kWh mensili."""
        return self.f1 + self.f2 + self.f3


def _parse_month_col(header: str) -> tuple[int, int]:
    """Interpreta intestazioni tipo 'Gen - 26' o 'gen-2026'."""
    clean = header.strip().lower().replace("-", " ")
    parts = clean.split()
    if len(parts) < 2:
        raise ValueError(f"Intestazione mese non valida: '{header}'")
    m_str = parts[0][:3]
    if m_str not in _MONTH_MAP:
        raise ValueError(f"Mese non riconosciuto: '{m_str}' in '{header}'")
    month = _MONTH_MAP[m_str]
    try:
        y_val = int(parts[1])
        year = (2000 + y_val) if y_val < 100 else y_val
    except ValueError as e:
        raise ValueError(f"Anno non valido in '{header}': {e}") from e
    return year, month


def _parse_float(val: str) -> float:
    """Converte un importo italiano con virgola tipo '115,98' in float."""
    clean = val.strip().replace(",", ".")
    return float(clean)


def load_bill(path: str | Path) -> list[BillRow]:
    """Carica e valida i consumi mensili da un file CSV della bolletta."""
    p = Path(path)
    if not p.exists() or not p.is_file():
        raise ReportError(f"File bolletta non trovato: {path}")

    try:
        with p.open("r", encoding="utf-8-sig") as f:
            reader = csv.reader(f, delimiter=";")
            rows = [r for r in reader if any(cell.strip() for cell in r)]
    except Exception as e:
        raise ReportError(f"Impossibile leggere il file CSV della bolletta: {e}") from e

    if not rows:
        raise ReportError(f"Il file bolletta {path} è vuoto.")

    header = rows[0]
    # La prima colonna è vuota o etichetta; le successive sono i mesi
    month_cols: list[tuple[int, tuple[int, int]]] = []
    for idx, cell in enumerate(header[1:], start=1):
        cell_clean = cell.strip()
        if not cell_clean:
            continue
        try:
            ym = _parse_month_col(cell_clean)
            month_cols.append((idx, ym))
        except ValueError as e:
            raise ReportError(f"Errore formato colonne bolletta: {e}") from e

    if not month_cols:
        raise ReportError("Nessuna colonna mese valida trovata nell'intestazione della bolletta.")

    f_data: dict[str, list[float]] = {}
    for r in rows[1:]:
        if not r:
            continue
        label = r[0].strip().upper()
        if label in ("F1", "F2", "F3"):
            vals: list[float] = []
            for col_idx, _ in month_cols:
                if col_idx < len(r) and r[col_idx].strip():
                    try:
                        vals.append(_parse_float(r[col_idx]))
                    except ValueError as e:
                        raise ReportError(f"Valore non numerico per {label} in colonna {col_idx}: {e}") from e
                else:
                    vals.append(0.0)
            f_data[label] = vals

    # Costruisci i record BillRow
    result: list[BillRow] = []
    num_months = len(month_cols)
    f1_list = f_data.get("F1", [0.0] * num_months)
    f2_list = f_data.get("F2", [0.0] * num_months)
    f3_list = f_data.get("F3", [0.0] * num_months)

    for i, (_, (year, month)) in enumerate(month_cols):
        result.append(
            BillRow(
                year=year,
                month=month,
                f1=f1_list[i],
                f2=f2_list[i],
                f3=f3_list[i],
            )
        )

    # Ordina cronologicamente
    result.sort(key=lambda r: (r.year, r.month))
    return result
