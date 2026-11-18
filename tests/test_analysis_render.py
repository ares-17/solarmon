"""Test di generazione del report HTML e Markdown."""

from test_analysis_render_context import make_context

from analysis.render import render_html, render_markdown


def test_html_is_self_contained():
    html = render_html(make_context())
    assert html.startswith("<!DOCTYPE html>")
    assert "NaN" not in html and "None" not in html
    assert "http://" not in html and "https://" not in html
    assert "<script" not in html


def test_html_has_all_sections():
    html = render_html(make_context())
    for title in (
        "Flussi",
        "Batteria",
        "Fotovoltaico",
        "Consumi",
        "Simulazioni",
        "Cosa fare",
        "Dati e limiti",
    ):
        assert title in html


def test_markdown_keeps_the_verdict():
    md = render_markdown(make_context())
    assert "da_sostituire" in md.lower() or "da sostituire" in md.lower()
    assert "simulazioni" in md.lower()
