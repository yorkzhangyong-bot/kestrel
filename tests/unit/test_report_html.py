"""render_html derives a self-contained, escaped HTML document from the Markdown (FR-017, SC-008)."""
from kestrel.report.render import render_html, render_markdown
from tests.unit.test_report_render import a_model

FEATURE = "005"


def test_html_is_a_self_contained_document_with_no_scripts_or_external_resources():
    html = render_html(render_markdown(a_model()))
    assert "<!doctype html>" in html.lower() and "<html" in html.lower()
    assert "<script" not in html.lower()          # no scripts at all (we add none; raw ones are escaped)
    assert 'src="http' not in html and 'href="http' not in html   # nothing external is loaded


def test_hostile_run_content_is_escaped_to_text():
    html = render_html(render_markdown(a_model()))
    # the finding's winning message contained <script>alert(1)</script>; it must appear escaped, not live
    assert "<script>alert(1)" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_tables_render():
    html = render_html(render_markdown(a_model()))
    assert "<table>" in html and "LLM07: System Prompt Leakage" in html
