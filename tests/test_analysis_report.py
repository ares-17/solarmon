"""Test dell'orchestrazione del report e del CLI."""

import json

from analysis_helpers import make_db, row

from analysis.report import build_report, main


def two_days(path):
    rows = []
    for d in range(2):
        for i in range(1440):
            ts = d * 86400 + i * 60
            pv = 1500 if 600 <= i < 840 else 0
            rows.append(
                row(
                    ts=ts,
                    pv_w=pv,
                    batt_v=51.0,
                    out_w=400.0,
                    mode="B",
                    e_pv_wh=pv / 60.0,
                    e_solar_wh=pv / 60.0,
                )
            )
    return make_db(path, rows)


def test_build_report_writes_three_files(tmp_path):
    db = two_days(tmp_path / "solar.db")
    out = build_report(db, tmp_path / "reports", generated_at="2026-11-18 10:00")
    assert (out / "report.html").exists()
    assert (out / "report.md").exists()
    data = json.loads((out / "data.json").read_text(encoding="utf-8"))
    assert data["days"] > 0
    assert data["battery"]["verdict"] in {"sana", "da_controllare", "da_sostituire", "indeterminato"}


def test_empty_database_exits_with_two(tmp_path):
    db = make_db(tmp_path / "solar.db", [])
    code = main(["--db", str(db), "--out", str(tmp_path / "reports")])
    assert code == 2
