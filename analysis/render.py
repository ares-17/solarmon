"""Rendering autonomo del report in HTML e Markdown.

Genera un file HTML autonomo senza dipendenze né connessioni esterne, con grafica SVG
incorporata, stili ottimizzati per desktop, mobile e stampa A4 (@media print).
Genera inoltre un riassunto esecutivo in formato Markdown.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .battery import BatteryReport
from .bill import BillRow
from .metrics import Totals
from .model import ScenarioResult
from .pv import PvReport

# Palette colori solarmon
COLOR_SOLAR = "#e8a33d"
COLOR_BATT = "#4f8fd8"
COLOR_GRID = "#c0504d"
COLOR_LOAD = "#7c858d"
COLOR_BG_CARD = "#ffffff"
COLOR_BORDER = "#e2e8f0"


@dataclass(frozen=True)
class ReportContext:
    """Contesto completo per il rendering del report."""

    generated_at: str
    tz_name: str
    first_ts: int
    last_ts: int
    days: float
    reliability: str
    totals: Totals
    battery: BatteryReport
    pv: PvReport
    switches: dict[str, Any]
    hourly: list[dict[str, Any]]
    daily: dict[str, Any]
    bill_rows: list[BillRow]
    scenarios: list[ScenarioResult]
    actions: list[str]
    settings: dict[str, Any]
    warnings: list[str]
    voltage: list[tuple[float, float]]


def _fmt(val: float | None, dec: int = 1, suffix: str = "") -> str:
    """Formatta un numero gestendo None e NaN con trattino."""
    if val is None:
        return "–"
    return f"{val:.{dec}f}{suffix}"


def _fmt_ts(ts: int | float | None) -> str:
    if not ts:
        return "–"
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%d/%m/%Y %H:%M")


def _render_daily_svg(daily: dict[str, Any], width: int = 680, height: int = 240) -> str:
    """Genera grafico SVG a barre impilate (FV, Batteria, Rete) per giorno."""
    ts_list = daily.get("ts", [])
    if not ts_list:
        return "<p class='no-data'>Dati giornalieri non disponibili.</p>"

    solar = daily.get("solar", [])
    batt = daily.get("batt", [])
    grid = daily.get("grid", [])
    n = len(ts_list)

    pad_left = 50
    pad_right = 20
    pad_top = 25
    pad_bot = 40
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bot

    max_tot = 0.0
    for i in range(n):
        s_val = solar[i] if i < len(solar) else 0.0
        b_val = batt[i] if i < len(batt) else 0.0
        g_val = grid[i] if i < len(grid) else 0.0
        tot = s_val + b_val + g_val
        if tot > max_tot:
            max_tot = tot
    max_tot = max(max_tot, 1.0) * 1.15

    bar_width = min(40, max(10, int(plot_w / (n * 1.5))))
    step = plot_w / n

    elements = [
        f'<svg viewBox="0 0 {width} {height}" class="chart-svg">',
        f'<line x1="{pad_left}" y1="{pad_top + plot_h}" x2="{pad_left + plot_w}" y2="{pad_top + plot_h}" stroke="#cbd5e1" stroke-width="1"/>',
    ]

    # Asse Y
    for tick in (0.0, max_tot / 2.0, max_tot):
        y = pad_top + plot_h - (tick / max_tot) * plot_h
        elements.append(
            f'<text x="{pad_left - 8}" y="{y + 4}" text-anchor="end" font-size="10" fill="#64748b">{tick:.1f}</text>'
        )
        elements.append(
            f'<line x1="{pad_left}" y1="{y}" x2="{pad_left + plot_w}" y2="{y}" stroke="#f1f5f9" stroke-width="1"/>'
        )

    for i, ts in enumerate(ts_list):
        cx = pad_left + i * step + step / 2.0
        x = cx - bar_width / 2.0
        s_val = solar[i] if i < len(solar) else 0.0
        b_val = batt[i] if i < len(batt) else 0.0
        g_val = grid[i] if i < len(grid) else 0.0

        h_s = (s_val / max_tot) * plot_h
        h_b = (b_val / max_tot) * plot_h
        h_g = (g_val / max_tot) * plot_h

        curr_y = pad_top + plot_h
        if h_s > 0:
            curr_y -= h_s
            elements.append(f'<rect x="{x:.1f}" y="{curr_y:.1f}" width="{bar_width}" height="{h_s:.1f}" fill="{COLOR_SOLAR}"/>')
        if h_b > 0:
            curr_y -= h_b
            elements.append(f'<rect x="{x:.1f}" y="{curr_y:.1f}" width="{bar_width}" height="{h_b:.1f}" fill="{COLOR_BATT}"/>')
        if h_g > 0:
            curr_y -= h_g
            elements.append(f'<rect x="{x:.1f}" y="{curr_y:.1f}" width="{bar_width}" height="{h_g:.1f}" fill="{COLOR_GRID}"/>')

        lbl = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d/%m")
        elements.append(
            f'<text x="{cx:.1f}" y="{pad_top + plot_h + 16}" text-anchor="middle" font-size="10" fill="#64748b">{lbl}</text>'
        )

    elements.append("</svg>")
    return "\n".join(elements)


def _render_voltage_svg(voltage: list[tuple[float, float]], width: int = 680, height: int = 220) -> str:
    """Genera grafico SVG per l'andamento temporale della tensione batteria."""
    if not voltage or len(voltage) < 2:
        return "<p class='no-data'>Serie di tensione non disponibile.</p>"

    pad_left = 50
    pad_right = 20
    pad_top = 20
    pad_bot = 35
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bot

    t_min = voltage[0][0]
    t_max = voltage[-1][0]
    dt_span = max(1.0, t_max - t_min)

    v_min = min(v for _, v in voltage)
    v_max = max(v for _, v in voltage)
    v_axis_min = math.floor(min(44.0, v_min))
    v_axis_max = math.ceil(max(58.0, v_max))
    v_span = max(1.0, v_axis_max - v_axis_min)

    points = []
    for t, v in voltage:
        x = pad_left + ((t - t_min) / dt_span) * plot_w
        y = pad_top + plot_h - ((v - v_axis_min) / v_span) * plot_h
        points.append(f"{x:.1f},{y:.1f}")

    elements = [
        f'<svg viewBox="0 0 {width} {height}" class="chart-svg">',
    ]

    # Asse Y
    for v_tick in range(int(v_axis_min), int(v_axis_max) + 1, 2):
        y = pad_top + plot_h - ((v_tick - v_axis_min) / v_span) * plot_h
        elements.append(
            f'<text x="{pad_left - 8}" y="{y + 4}" text-anchor="end" font-size="10" fill="#64748b">{v_tick}V</text>'
        )
        elements.append(
            f'<line x1="{pad_left}" y1="{y:.1f}" x2="{pad_left + plot_w}" y2="{y:.1f}" stroke="#f1f5f9" stroke-width="1"/>'
        )

    # Linea tensione
    elements.append(
        f'<polyline points="{" ".join(points)}" fill="none" stroke="{COLOR_BATT}" stroke-width="2" stroke-linecap="round"/>'
    )

    # Etichette asse X (inizio e fine)
    lbl_start = datetime.fromtimestamp(t_min, tz=timezone.utc).strftime("%d/%m %H:%M")
    lbl_end = datetime.fromtimestamp(t_max, tz=timezone.utc).strftime("%d/%m %H:%M")
    elements.append(f'<text x="{pad_left}" y="{height - 10}" text-anchor="start" font-size="10" fill="#64748b">{lbl_start}</text>')
    elements.append(f'<text x="{pad_left + plot_w}" y="{height - 10}" text-anchor="end" font-size="10" fill="#64748b">{lbl_end}</text>')

    elements.append("</svg>")
    return "\n".join(elements)


def _render_hourly_svg(hourly: list[dict[str, Any]], width: int = 680, height: int = 220) -> str:
    """Genera grafico SVG del profilo orario medio a 24 barre."""
    if not hourly:
        return "<p class='no-data'>Profilo orario non disponibile.</p>"

    pad_left = 50
    pad_right = 20
    pad_top = 20
    pad_bot = 35
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bot

    max_val = max((h.get("load_kwh", 0.0) for h in hourly), default=0.1)
    max_val = max(max_val, 0.1) * 1.15

    step = plot_w / 24.0
    bar_w = max(4.0, step * 0.75)

    elements = [
        f'<svg viewBox="0 0 {width} {height}" class="chart-svg">',
    ]

    for tick in (0.0, max_val / 2.0, max_val):
        y = pad_top + plot_h - (tick / max_val) * plot_h
        elements.append(f'<text x="{pad_left - 8}" y="{y + 4}" text-anchor="end" font-size="10" fill="#64748b">{tick:.2f}</text>')
        elements.append(f'<line x1="{pad_left}" y1="{y:.1f}" x2="{pad_left + plot_w}" y2="{y:.1f}" stroke="#f1f5f9" stroke-width="1"/>')

    for h_data in hourly:
        h = h_data.get("hour", 0)
        cx = pad_left + h * step + step / 2.0
        x = cx - bar_w / 2.0

        s_kwh = h_data.get("solar_kwh", 0.0)
        b_kwh = h_data.get("batt_kwh", 0.0)
        g_kwh = h_data.get("grid_kwh", 0.0)

        h_s = (s_kwh / max_val) * plot_h
        h_b = (b_kwh / max_val) * plot_h
        h_g = (g_kwh / max_val) * plot_h

        curr_y = pad_top + plot_h
        if h_s > 0:
            curr_y -= h_s
            elements.append(f'<rect x="{x:.1f}" y="{curr_y:.1f}" width="{bar_w:.1f}" height="{h_s:.1f}" fill="{COLOR_SOLAR}"/>')
        if h_b > 0:
            curr_y -= h_b
            elements.append(f'<rect x="{x:.1f}" y="{curr_y:.1f}" width="{bar_w:.1f}" height="{h_b:.1f}" fill="{COLOR_BATT}"/>')
        if h_g > 0:
            curr_y -= h_g
            elements.append(f'<rect x="{x:.1f}" y="{curr_y:.1f}" width="{bar_w:.1f}" height="{h_g:.1f}" fill="{COLOR_GRID}"/>')

        if h % 3 == 0:
            elements.append(
                f'<text x="{cx:.1f}" y="{pad_top + plot_h + 16}" text-anchor="middle" font-size="10" fill="#64748b">{h:02d}</text>'
            )

    elements.append("</svg>")
    return "\n".join(elements)


def render_html(ctx: ReportContext) -> str:
    """Produce l'HTML autosufficiente completo del report."""
    daily_svg = _render_daily_svg(ctx.daily)
    voltage_svg = _render_voltage_svg(ctx.voltage)
    hourly_svg = _render_hourly_svg(ctx.hourly)

    verdict_badge_color = {
        "sana": "#10b981",
        "da_controllare": "#f59e0b",
        "da_sostituire": "#ef4444",
        "indeterminato": "#64748b",
    }.get(ctx.battery.verdict, "#64748b")

    verdict_text = ctx.battery.verdict.replace("_", " ").upper()

    scenarios_rows = []
    for s in ctx.scenarios:
        scenarios_rows.append(
            f"""<tr>
                <td class="font-medium">{s.name}</td>
                <td>{_fmt(s.grid_kwh_day, 1)}</td>
                <td>{_fmt(s.self_sufficiency, 1, '%')}</td>
                <td>{_fmt(s.curtailed_kwh_day, 1)}</td>
                <td>{_fmt(s.cycles_day, 2)}</td>
                <td>{_fmt(s.empty_hours_day, 1)}h</td>
                <td>{_fmt(s.cost_day_eur, 2, ' €')}</td>
                <td class="text-sm text-slate-500">{s.note}</td>
            </tr>"""
        )

    bill_section = ""
    if ctx.bill_rows:
        b_rows = "".join(
            f"<tr><td>{r.year}-{r.month:02d}</td><td>{_fmt(r.f1)}</td><td>{_fmt(r.f2)}</td><td>{_fmt(r.f3)}</td><td class='font-bold'>{_fmt(r.total)}</td></tr>"
            for r in ctx.bill_rows
        )
        bill_section = f"""
        <div class="card mt-4">
            <h3 class="card-subtitle">Confronto bolletta (kWh fatturati contatore)</h3>
            <table class="data-table">
                <thead><tr><th>Mese</th><th>F1 (kWh)</th><th>F2 (kWh)</th><th>F3 (kWh)</th><th>Totale (kWh)</th></tr></thead>
                <tbody>{b_rows}</tbody>
            </table>
        </div>"""

    actions_list = "".join(f"<li>{a}</li>" for a in ctx.actions)
    battery_reasons = "".join(f"<li>{r}</li>" for r in ctx.battery.reasons)

    return f"""<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Report Impianto Solare — {ctx.generated_at}</title>
    <style>
        :root {{
            --solar: {COLOR_SOLAR};
            --batt: {COLOR_BATT};
            --grid: {COLOR_GRID};
            --load: {COLOR_LOAD};
            --bg: #f8fafc;
            --surface: #ffffff;
            --border: #e2e8f0;
            --text-main: #0f172a;
            --text-sub: #475569;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: var(--bg);
            color: var(--text-main);
            line-height: 1.5;
            padding: 24px;
        }}
        .container {{ max-width: 900px; margin: 0 auto; }}
        header {{
            background: var(--surface);
            padding: 24px;
            border-radius: 12px;
            border: 1px solid var(--border);
            margin-bottom: 20px;
        }}
        h1 {{ font-size: 24px; font-weight: 700; margin-bottom: 6px; }}
        .meta {{ font-size: 14px; color: var(--text-sub); }}
        .badge {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: 9999px;
            font-size: 12px;
            font-weight: 700;
            color: #fff;
            text-transform: uppercase;
        }}
        .kpi-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 16px;
            margin: 20px 0;
        }}
        .kpi-card {{
            background: var(--surface);
            padding: 16px;
            border-radius: 10px;
            border: 1px solid var(--border);
        }}
        .kpi-val {{ font-size: 24px; font-weight: 700; margin-top: 4px; }}
        .kpi-lbl {{ font-size: 12px; color: var(--text-sub); text-transform: uppercase; }}
        .card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
        }}
        h2 {{ font-size: 18px; font-weight: 700; margin-bottom: 14px; border-bottom: 2px solid #f1f5f9; padding-bottom: 8px; }}
        .card-subtitle {{ font-size: 14px; font-weight: 600; color: var(--text-sub); margin-bottom: 10px; }}
        .chart-svg {{ width: 100%; height: auto; display: block; }}
        .data-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
            margin-top: 10px;
        }}
        .data-table th, .data-table td {{
            padding: 8px 12px;
            text-align: left;
            border-bottom: 1px solid var(--border);
        }}
        .data-table th {{ background: #f8fafc; font-weight: 600; color: var(--text-sub); }}
        .settings-box {{
            background: #f8fafc;
            border: 1px dashed var(--border);
            border-radius: 8px;
            padding: 14px;
            font-size: 13px;
            margin-top: 14px;
        }}
        ul {{ padding-left: 20px; margin-top: 8px; }}
        li {{ margin-bottom: 6px; font-size: 14px; }}
        @media print {{
            body {{ background: #fff; padding: 0; }}
            .card {{ page-break-inside: avoid; border: 1px solid #ccc; }}
        }}
    </style>
</head>
<body>
<div class="container">
    <header>
        <h1>Report Impianto Solare</h1>
        <div class="meta">
            Periodo: {_fmt_ts(ctx.first_ts)} &rarr; {_fmt_ts(ctx.last_ts)} ({ctx.days:.1f} giorni osservati) &middot;
            Fuso: {ctx.tz_name} &middot;
            Affidabilità: <span class="badge" style="background:#64748b;">{ctx.reliability}</span> &middot;
            Generato il: {ctx.generated_at}
        </div>
        <div style="margin-top: 14px;">
            Stato batteria: <span class="badge" style="background:{verdict_badge_color};">{verdict_text}</span>
        </div>
    </header>

    <div class="kpi-grid">
        <div class="kpi-card">
            <div class="kpi-lbl">Autosufficienza</div>
            <div class="kpi-val" style="color:#10b981;">{_fmt(ctx.totals.self_sufficiency, 1, '%')}</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-lbl">Carico Totale</div>
            <div class="kpi-val">{_fmt(ctx.totals.load_kwh, 1, ' kWh')}</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-lbl">Produzione FV</div>
            <div class="kpi-val" style="color:var(--solar);">{_fmt(ctx.totals.pv_kwh, 1, ' kWh')}</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-lbl">Prelievo Rete</div>
            <div class="kpi-val" style="color:var(--grid);">{_fmt(ctx.totals.grid_kwh, 1, ' kWh')}</div>
        </div>
    </div>

    <!-- 1. Flussi -->
    <div class="card">
        <h2>1. Flussi di Energia</h2>
        <div class="card-subtitle">Ripartizione giornaliera dell'energia erogata al carico (FV, Batteria, Rete)</div>
        {daily_svg}
    </div>

    <!-- 2. Batteria -->
    <div class="card">
        <h2>2. Diagnostica Batteria</h2>
        <div class="card-subtitle">Tensione osservata nel tempo e motivazioni del verdetto ({verdict_text})</div>
        {voltage_svg}
        <ul style="margin-top:14px;">
            <li>Throughput misurato: Carica {_fmt(ctx.battery.e_chg_kwh, 2)} kWh &middot; Scarica {_fmt(ctx.battery.e_dis_kwh, 2)} kWh</li>
            <li>Ciclo più profondo registrato: {_fmt(ctx.battery.e_dis_max_kwh, 2)} kWh (Riferimento 50% DoD: {_fmt(ctx.battery.ref_kwh, 2)} kWh)</li>
            <li>Salti di tensione bruschi (&ge; 4 V in &le; 120 s): {_fmt(ctx.battery.jumps_per_day, 1)} al giorno</li>
            <li>Tempo notturno sotto soglia di ritorno rete: {_fmt(ctx.battery.night_below_pct, 1, '%')}</li>
            {battery_reasons}
        </ul>
    </div>

    <!-- 3. Fotovoltaico -->
    <div class="card">
        <h2>3. Produzione Fotovoltaica</h2>
        <div class="card-subtitle">{ctx.pv.note}</div>
        <table class="data-table">
            <tr><th>FV Osservato</th><td>{_fmt(ctx.pv.observed_kwh, 2)} kWh</td></tr>
            <tr><th>Picco di Potenza Registrato</th><td>{_fmt(ctx.pv.peak_w, 0)} W ({_fmt_ts(ctx.pv.peak_ts)})</td></tr>
            <tr><th>Taglia Efficace Stimata</th><td>{_fmt(ctx.pv.kwp_eff, 2)} kWp</td></tr>
            <tr><th>Potenziale Disponibile a Cielo Chiaro</th><td>{_fmt(ctx.pv.available_kwh, 2)} kWh</td></tr>
            <tr><th>Energia Strozzata (Curtailment stimato)</th><td>{_fmt(ctx.pv.curtailed_kwh, 2)} kWh</td></tr>
        </table>
    </div>

    <!-- 4. Consumi -->
    <div class="card">
        <h2>4. Profilo dei Consumi</h2>
        <div class="card-subtitle">Profilo orario medio (kWh/giorno) nelle 24 ore locali</div>
        {hourly_svg}
        {bill_section}
    </div>

    <!-- 5. Simulazioni -->
    <div class="card">
        <h2>5. Simulazioni di Scenario</h2>
        <div class="card-subtitle">Confronto del prelievo di rete ed efficienza con varie taglie di accumulo LFP</div>
        <table class="data-table">
            <thead>
                <tr>
                    <th>Scenario</th>
                    <th>Rete (kWh/g)</th>
                    <th>Autosuff.</th>
                    <th>Strozzati (kWh/g)</th>
                    <th>Cicli/g</th>
                    <th>Vuota (h/g)</th>
                    <th>Costo/g</th>
                    <th>Note</th>
                </tr>
            </thead>
            <tbody>
                {''.join(scenarios_rows)}
            </tbody>
        </table>

        <div class="settings-box">
            <strong>Parametri raccomandati per banco LFP 16 kWh 51.2 V (Programma Axpert):</strong><br>
            Tipo: <code>{ctx.settings.get('battery_type', 'USER')}</code> &middot;
            Bulk: <code>{_fmt(ctx.settings.get('bulk_v'))}V</code> &middot;
            Float: <code>{_fmt(ctx.settings.get('float_v'))}V</code> &middot;
            Cutoff: <code>{_fmt(ctx.settings.get('cutoff_v'))}V</code> &middot;
            Ritorno Rete: <code>{_fmt(ctx.settings.get('return_grid_v'))}V</code> &middot;
            Ritorno Batt: <code>{_fmt(ctx.settings.get('return_batt_v'))}V</code> &middot;
            Max Carica: <code>{_fmt(ctx.settings.get('max_charge_a'), 0)} A (Prog. 02)</code>
        </div>
    </div>

    <!-- 6. Cosa fare -->
    <div class="card">
        <h2>6. Cosa fare</h2>
        <div class="card-subtitle">Raccomandazioni prioritarie basate sui dati e sulla simulazione</div>
        <ul>
            {actions_list}
        </ul>
    </div>

    <!-- 7. Dati e limiti -->
    <div class="card">
        <h2>7. Dati e limiti del report</h2>
        <ul>
            <li>Tutte le grandezze si basano su campionamenti discreti a 60 s; i buchi oltre max_gap non generano energia inventata.</li>
            <li>Il verdetto sulla batteria riflette l'energia erogabile reale e non una stima da curva di tensione.</li>
            <li>Con affidabilità bassa le simulazioni rappresentano un esercizio di dimensionamento e non una previsione d'acquisto definitiva.</li>
        </ul>
    </div>
</div>
</body>
</html>
"""


def render_markdown(ctx: ReportContext) -> str:
    """Genera un riepilogo sintetico in formato Markdown."""
    lines = [
        f"# Report Impianto Solare — {ctx.generated_at}",
        "",
        f"- **Periodo osservato**: {_fmt_ts(ctx.first_ts)} &rarr; {_fmt_ts(ctx.last_ts)} ({ctx.days:.1f} giorni)",
        f"- **Fuso orario**: {ctx.tz_name}",
        f"- **Affidabilità**: {ctx.reliability}",
        f"- **Stato Batteria**: {ctx.battery.verdict.upper()}",
        "",
        "## KPI Chiave",
        "",
        f"- Autosufficienza: {_fmt(ctx.totals.self_sufficiency, 1, '%')}",
        f"- Produzione FV: {_fmt(ctx.totals.pv_kwh, 1)} kWh",
        f"- Consumo Carico: {_fmt(ctx.totals.load_kwh, 1)} kWh",
        f"- Prelievo Rete: {_fmt(ctx.totals.grid_kwh, 1)} kWh",
        "",
        "## Diagnostica Batteria",
        "",
        f"- Throughput: carica {_fmt(ctx.battery.e_chg_kwh, 2)} kWh / scarica {_fmt(ctx.battery.e_dis_kwh, 2)} kWh",
        f"- Ciclo più profondo: {_fmt(ctx.battery.e_dis_max_kwh, 2)} kWh (ref: {_fmt(ctx.battery.ref_kwh, 2)} kWh)",
        f"- Salti bruschi tensione: {_fmt(ctx.battery.jumps_per_day, 1)} / giorno",
        f"- Tempo sotto soglia notturna: {_fmt(ctx.battery.night_below_pct, 1, '%')}",
        "",
        "## Simulazioni",
        "",
        "| Scenario | Rete kWh/g | Autosuff. | Strozzati kWh/g | Note |",
        "|---|---|---|---|---|",
    ]

    for s in ctx.scenarios:
        lines.append(
            f"| {s.name} | {_fmt(s.grid_kwh_day, 1)} | {_fmt(s.self_sufficiency, 1, '%')} | {_fmt(s.curtailed_kwh_day, 1)} | {s.note} |"
        )

    lines.extend([
        "",
        "## Azioni Raccomandate",
        "",
    ])
    for a in ctx.actions:
        lines.append(f"- {a}")

    lines.extend([
        "",
        "## Limiti e Metodologia",
        "",
        "- Valori integrati sul tempo reale.",
        "- Simulazione con dispacciamento deterministico a passi.",
    ])

    return "\n".join(lines)
