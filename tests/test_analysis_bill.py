"""Test della lettura dei consumi mensili da bolletta CSV."""

import pytest

from analysis import ReportError
from analysis.bill import load_bill

CSV = """;Gen - 26 ;Feb - 26
Fascia unica ;0;0
F1 ;115,98;108,76
F2 ;125,09;107,84
F3 ;179,01;157,08
"""


def test_parse_italian_amounts_and_months(tmp_path):
    path = tmp_path / "bolletta.csv"
    path.write_text(CSV, encoding="utf-8")
    rows = load_bill(path)
    assert [(r.year, r.month) for r in rows] == [(2026, 1), (2026, 2)]
    assert rows[0].f1 == 115.98
    assert rows[0].total == pytest.approx(420.08)


def test_missing_file_is_report_error(tmp_path):
    with pytest.raises(ReportError):
        load_bill(tmp_path / "nope.csv")


def test_invalid_data_is_report_error(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text(";Gen - 26\nF1 ;not_a_number\n", encoding="utf-8")
    with pytest.raises(ReportError):
        load_bill(path)
