"""Orchestrazione dell'analisi e interfaccia a riga di comando (CLI).

Coordina la pipeline di analisi:
1. Caricamento campioni da snapshot SQLite
2. Calcolo flussi, profili orari, fasce e cambi
3. Diagnostica del pacco batterie
4. Analisi e stima potenziale fotovoltaico
5. Lettura facoltativa della bolletta mensile
6. Esecuzione simulazioni di espansione (LFP 10/16/20 kWh, FV x1.5 / x2)
7. Generazione delle raccomandazioni (Cosa fare)
8. Scrittura dei file: report.html, report.md, data.json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import DEFAULT_TZ, SITE_LAT, SITE_LON, VERSION, ReportError
from .battery import analyze_battery
from .bill import load_bill
from .db import load_samples
from .metrics import (
    daily_by_source,
    hourly_profile,
    switch_stats,
    totals,
    voltage_series,
)
from .pv import analyze_pv
from .render import (
    ReportContext,
    render_html,
    render_markdown,
)
from .scenarios import (
    LFP_16_SETTINGS,
    reliability,
    run_scenarios,
    suggested_actions,
)
from .timeutil import get_tz


def build_report(
    db_path: str | Path,
    out_dir: str | Path,
    *,
    config: dict[str, Any] | None = None,
    bill: str | Path | None = None,
    lat: float | None = SITE_LAT,
    lon: float | None = SITE_LON,
    kwp: float | None = None,
    nominal_kwh: float = 4.8,
    price: float | None = None,
    capacities: tuple[float, ...] = (10, 16, 20),
    tz: str = DEFAULT_TZ,
    generated_at: str | None = None,
) -> Path:
    """Esegue l'analisi completa e produce la cartella con report.html, report.md e data.json."""
    zone = get_tz(tz)
    samples = load_samples(db_path)
    if not samples:
        raise ReportError(f"Nessun campione trovato nel database: {db_path}")

    first_ts = int(samples[0].ts)
    last_ts = int(samples[-1].ts)

    # 1. Metriche e flussi
    tot = totals(samples, gap=300)
    days = tot.days
    rel = reliability(days)
    daily = daily_by_source(samples, zone, gap=300)
    hourly = hourly_profile(samples, zone, gap=300)
    switches = switch_stats(samples, gap=300)
    voltage = voltage_series(samples, zone)

    # 2. Diagnostica batteria
    battery = analyze_battery(
        samples,
        config,
        zone,
        nominal_kwh=nominal_kwh,
        gap=300,
    )

    # 3. Potenziale FV
    pv = analyze_pv(
        samples,
        zone,
        lat=lat,
        lon=lon,
        kwp=kwp,
        gap=300,
    )

    # 4. Bolletta
    bill_rows = []
    if bill:
        try:
            bill_rows = load_bill(bill)
        except Exception as e:
            # Bolletta opzionale: non blocca la generazione
            sys.stderr.write(f"Avviso: impossibile elaborare il file bolletta: {e}\n")

    # 5. Scenari
    scenarios = run_scenarios(
        samples,
        pv,
        zone,
        battery=battery,
        cfg=config,
        price=price,
        capacities=capacities,
        gap=300,
    )

    # 6. Azioni suggerite
    actions = suggested_actions(tot, battery, pv, scenarios, rel, hourly)

    # Avvisi operativi
    warnings = []
    if days < 7.0:
        warnings.append(f"Meno di 7 giorni osservati ({days:.1f} giorni): affidabilità bassa, simulazioni come esercizio.")
    if battery.verdict == "da_sostituire":
        warnings.append("Diagnosi batteria: pacco degradato con elevata probabilità di sostituzione richiesta.")

    if not generated_at:
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    ctx = ReportContext(
        generated_at=generated_at,
        tz_name=zone.name,
        first_ts=first_ts,
        last_ts=last_ts,
        days=days,
        reliability=rel,
        totals=tot,
        battery=battery,
        pv=pv,
        switches=switches,
        hourly=hourly,
        daily=daily,
        bill_rows=bill_rows,
        scenarios=scenarios,
        actions=actions,
        settings=LFP_16_SETTINGS,
        warnings=warnings,
        voltage=voltage,
    )

    # 7. Cartella di output deterministica
    timestamp_folder = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
    target_dir = Path(out_dir) / timestamp_folder
    target_dir.mkdir(parents=True, exist_ok=True)

    html_content = render_html(ctx)
    (target_dir / "report.html").write_text(html_content, encoding="utf-8")

    md_content = render_markdown(ctx)
    (target_dir / "report.md").write_text(md_content, encoding="utf-8")

    # Serializza dati strutturati in data.json
    data_dict = {
        "version": VERSION,
        "generated_at": ctx.generated_at,
        "tz": ctx.tz_name,
        "days": ctx.days,
        "reliability": ctx.reliability,
        "period": {
            "first_ts": ctx.first_ts,
            "last_ts": ctx.last_ts,
            "days": ctx.days,
            "reliability": ctx.reliability,
        },
        "totals": asdict(ctx.totals),
        "battery": asdict(ctx.battery),
        "pv": asdict(ctx.pv),
        "switches": ctx.switches,
        "hourly": ctx.hourly,
        "daily": ctx.daily,
        "bill": [asdict(r) for r in ctx.bill_rows],
        "scenarios": [asdict(s) for s in ctx.scenarios],
        "actions": ctx.actions,
        "settings": ctx.settings,
        "warnings": ctx.warnings,
    }
    (target_dir / "data.json").write_text(json.dumps(data_dict, indent=2, ensure_ascii=False), encoding="utf-8")

    return target_dir


def main(argv: list[str] | None = None) -> int:
    """Entry point della CLI."""
    parser = argparse.ArgumentParser(
        prog="analysis.report",
        description="Genera il report diagnostico e le simulazioni dell'impianto solare da uno snapshot SQLite.",
    )
    parser.add_argument("--db", required=True, help="Percorso del database SQLite (snapshot o locale)")
    parser.add_argument("--out", default="reports", help="Cartella base di destinazione dei report (default: reports/)")
    parser.add_argument("--config", help="Percorso del file now.json contenente la configurazione QPIRI")
    parser.add_argument("--bill", help="Percorso del file CSV con i consumi della bolletta")
    parser.add_argument("--lat", type=float, default=SITE_LAT, help="Latitudine per il modello di cielo chiaro")
    parser.add_argument("--lon", type=float, default=SITE_LON, help="Longitudine per il modello di cielo chiaro")
    parser.add_argument("--kwp", type=float, help="Potenza nominale reale dei pannelli (sostituisce la stima)")
    parser.add_argument("--nominal-kwh", type=float, default=4.8, help="Capacità nominale della batteria attuale in kWh")
    parser.add_argument("--price", help="Prezzo dell'energia in €/kWh per il calcolo dei costi di prelievo")
    parser.add_argument("--capacity", default="10,16,20", help="Capacità in kWh per gli scenari LFP (es. 10,16,20)")
    parser.add_argument("--tz", default=DEFAULT_TZ, help="Fuso orario di riferimento (default: Europe/Rome)")

    args = parser.parse_args(argv)

    cfg_dict = None
    if args.config:
        try:
            with open(args.config, encoding="utf-8") as f:
                c_json = json.load(f)
                cfg_dict = c_json.get("cfg", c_json)
        except Exception as e:
            sys.stderr.write(f"Errore nella lettura del file di configurazione {args.config}: {e}\n")

    price_val = None
    if args.price:
        try:
            price_val = float(str(args.price).replace(",", "."))
        except ValueError:
            sys.stderr.write(f"Valore di prezzo non valido: {args.price}\n")

    try:
        caps = tuple(float(c.strip()) for c in args.capacity.split(",") if c.strip())
    except ValueError:
        caps = (10.0, 16.0, 20.0)

    try:
        out_path = build_report(
            args.db,
            args.out,
            config=cfg_dict,
            bill=args.bill,
            lat=args.lat,
            lon=args.lon,
            kwp=args.kwp,
            nominal_kwh=args.nominal_kwh,
            price=price_val,
            capacities=caps,
            tz=args.tz,
        )
    except ReportError as e:
        sys.stderr.write(f"Errore: {e}\n")
        return 2
    except Exception as e:
        sys.stderr.write(f"Errore imprevisto durante l'analisi: {e}\n")
        return 2

    print(f"Report generato con successo in: {out_path}")
    print(f"  - HTML: {out_path / 'report.html'}")
    print(f"  - Markdown: {out_path / 'report.md'}")
    print(f"  - JSON: {out_path / 'data.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
