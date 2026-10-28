"""Render a ReportModel to Markdown (one template) and derive escaped, self-contained HTML (contracts/report-module.md).

All run-derived content is emitted inside fenced code blocks, so Markdown shows it as code and the HTML renderer
escapes it (FR-017, SC-008). The HTML is a single self-contained document with inline style and no external resources.
"""
from __future__ import annotations

import re

from markdown_it import MarkdownIt

from kestrel.report.model import ReportModel

EMPTY_MESSAGE = "No runs to report yet — attack this target first."

# commonmark with tables; html=False so raw HTML in the source is escaped, never passed through (SC-008).
_MD = MarkdownIt("commonmark", {"html": False}).enable("table")

_STYLE = ("body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;max-width:52rem;margin:2rem auto;"
          "padding:0 1rem;line-height:1.5;color:#1a1a1a}"
          "table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccc;padding:.4rem .6rem;text-align:left}"
          "pre{background:#f5f5f5;padding:.75rem;overflow:auto;white-space:pre-wrap;word-break:break-word}"
          "code{font-family:ui-monospace,Consolas,monospace}h1,h2,h3{line-height:1.25}")


def _fence(text: str) -> list[str]:
    """A fenced code block whose fence is longer than any backtick run in the content, so it can't be closed early."""
    longest = max((len(run) for run in re.findall(r"`+", text or "")), default=0)
    ticks = "`" * max(3, longest + 1)
    return [ticks, text or "", ticks, ""]


def render_markdown(model: ReportModel) -> str:
    h = model.header
    if model.is_empty:
        return f"# Security report — {h.target_name}\n\n{EMPTY_MESSAGE}\n"

    lines: list[str] = [f"# Security report — {h.target_name}", ""]
    lines.append(f"- **Purpose**: {h.purpose or '—'}")
    lines.append(f"- **Generated**: {h.generated_at}")
    lines.append(f"- **Runs**: {h.run_count}")
    lines.append(f"- **Attacker model(s)**: {', '.join(h.attacker_models) or '—'}")
    lines.append(f"- **Judge model(s)**: {', '.join(h.judge_models) or '—'}")
    budget = h.token_budget if h.token_budget is not None else "—"
    lines += [f"- **Token budget / used**: {budget} / {h.tokens_used}", ""]

    if model.coverage:
        lines += ["## OWASP coverage", "", "| OWASP class | Family | Runs | Result |", "| --- | --- | --- | --- |"]
        lines += [f"| {r.owasp_class} | {r.families} | {r.run_count} | {r.result} |" for r in model.coverage]
        lines.append("")
    if model.untested:
        lines += ["**Not tested** (out of scope):", ""]
        lines += [f"- **{u.owasp_class}** — {u.reason}" for u in model.untested]
        lines.append("")

    lines += ["## Findings", ""]
    if not model.findings:
        lines += ["No successful attacks recorded.", ""]
    for finding in model.findings:
        lines += [f"### {finding.family} — {finding.owasp_class}", "", "Winning attacker message:"]
        lines += _fence(finding.winning_message)
        if finding.evidence is not None:
            lines.append("Hard evidence (verbatim):")
            lines += _fence(finding.evidence)
        elif finding.judge_note is not None:
            lines.append("Judge note (suspected — not confirmed):")
            lines += _fence(finding.judge_note)
        if finding.recommendation is not None:
            label = f" ({finding.recommendation.model})" if finding.recommendation.model else ""
            lines += [f"**Suggestion{label}**: {finding.recommendation.text}", ""]
        else:
            lines += ["_No recommendation available (no judge model configured)._", ""]

    lines += ["## Failed and unclear runs", ""]
    if not model.other_runs:
        lines += ["None.", ""]
    for other in model.other_runs:
        stop = f" · stopped at {other.stopping_condition}" if other.stopping_condition else ""
        lines.append(f"- {other.family} · {other.when} · {other.verdict}{stop}")
    if model.other_runs:
        lines.append("")

    lines += ["## Limitations", "", model.limitations, ""]
    return "\n".join(lines)


def render_html(markdown: str) -> str:
    """Derive a self-contained HTML document from the Markdown; raw and fenced content is escaped (SC-008)."""
    body = _MD.render(markdown)
    return ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            '<title>Kestrel security report</title>'
            f"<style>{_STYLE}</style></head>\n<body>\n{body}</body></html>\n")
