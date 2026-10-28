# Implementation Plan: OWASP-Mapped, Fix-Ready Report

**Branch**: `005-owasp-report` | **Date**: 2026-10-28 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/005-owasp-report/spec.md`

## Summary

Turn the runs Kestrel already stored into one downloadable, OWASP-mapped, fix-ready report for a target, realising constitution Principle VI. The report is built as a pure function over existing data: a new `report/` package reads targets, runs and conversation turns from SQLite (and the experience store read-only, for counts in the limitations note), assembles a structured report model, renders it once as Markdown from a single template, and derives self-contained, escaped HTML from that Markdown. Findings carry the winning attacker message, the hard evidence quoted verbatim (or the judge's note, marked suspected), and a model-generated recommendation reusing the existing judge client — one call per successful run, cached per run id in SQLite so regenerating a report makes no new model call. A new `GET /api/targets/{id}/report?format=md|html` endpoint serves both formats; the Streamlit screen gains a Report section after Profile with a generate control, two downloads and a rendered preview.

The slice adds no attack behaviour: no new nodes in `attack/graph.py`, no sends to the target, no writes to the experience store, and no new secrets. It reuses the stored runs/turns (features 002/003), the masking already applied to them, the family→OWASP mapping from the attack library (feature 002), and the judge client (feature 002) for recommendations.

## Technical Context

**Language/Version**: Python 3.12 (uv-managed), unchanged.

**Primary Dependencies**: FastAPI, Streamlit, httpx, cryptography, uvicorn, LangGraph, ChromaDB, pytest — all present — plus **`markdown-it-py`** (new) to derive HTML from the report Markdown. Principle X requires a one-line justification (see Complexity Tracking): a vetted, pure-Python Markdown→HTML renderer avoids hand-rolling security-critical escaping for a file users open in a browser. No model SDK; recommendations go through the existing judge client's `httpx` calls.

**Storage**: the existing SQLite file (`meta.schema_version` 4 → 5: add one `report_recommendations` table caching one recommendation per run; additive migration). The experience store (ChromaDB) is read **read-only** for two counts and is never written. Reports are generated on demand and not otherwise persisted.

**Testing**: pytest. Unit tests for the report model, the OWASP mapping and both renderers, driven by fixtures (no database, no model). Integration tests for `GET /api/targets/{id}/report` over a `TestClient` with a stub judge and a stub-backed experience store at a temp path. An end-to-end test is optional (the report makes no target calls; its only model use is recommendations through the judge).

**Target Platform**: the user's machine or hosted; unchanged.

**Project Type**: web application in one repo — FastAPI service, Streamlit screen, the sacrificial target reused unchanged.

**Performance Goals**: generating a report reads the target's runs/turns and makes at most one judge call per successful run on first generation; cached thereafter. No target calls, no embedding calls.

**Constraints (central here)**: the report output MUST NOT contain the target URL, auth header names/values or any secret; hard evidence is quoted byte-for-byte as stored (already masked); the HTML format escapes all run-derived content so nothing executes or loads when opened; generation never attacks, never sends to the target, and never writes to the experience store.

**Scale/Scope**: single user; a target accumulates runs; the report lists every run (findings for successes, one line for the rest).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Verdict | How this feature satisfies it |
|---|---|---|
| I. Scope is security, not quality | PASS | A security report; quality-adjacent OWASP classes (e.g. LLM09) are named as out of scope, not scored. |
| II. Hard evidence over opinion | PASS | Findings quote canary hard evidence verbatim; judge-only successes are shown as suspected, never confirmed (FR-011). |
| III. Every report states the attacker model | PASS | The header names the attacker and judge models, the token budget and tokens used for the target's runs (FR-005). This is the literal report Principle III refers to. |
| IV. Secrets never leave the vault | PASS | No URL/headers/secrets in the output; recommendation input is non-secret run data; HTML escapes run content (FR-016, FR-017, FR-018; SC-006, SC-008). |
| V. Learn from every run | PASS (N/A) | The report runs no attack, so there is nothing to write back; it reads the experience store read-only and never writes it (FR-003). |
| VI. OWASP-mapped, fix-ready findings | PASS | This feature *is* Principle VI: every finding maps to an OWASP class and carries a fix-ready recommendation (FR-006, FR-009–FR-012). |
| VII. Tests first, thin slices | PASS | Unit tests for rendering and the OWASP mapping with fixtures, integration for the endpoint, e2e optional (FR tests in tasks). |
| VIII. Only attack what you own | PASS | Generation is read-only: zero sends to the target, zero new runs (FR-003, SC-007). |
| IX. Simple enough for a vibe coder | PASS | One Generate button, two downloads, a preview; a clear empty state. No config needed beyond the judge key already used. |
| X. Stack is fixed for the MVP | PASS (with note) | Adds one pure-Python dependency, `markdown-it-py`, for Markdown→HTML; justified in Complexity Tracking. No other new dependency. |

**Post-design re-check (after Phase 1)**: unchanged. The design adds one read-only SQLite table, one GET endpoint, a pure report package, a `recommend` method on the existing judge client, and a UI section. No new secret path (recommendation input is non-secret; HTML is escaped); no write to the experience store; no new graph node.

## Project Structure

### Documentation (this feature)

```text
specs/005-owasp-report/
├── plan.md              # This file
├── research.md          # Phase 0 output (R1–R8)
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── report-api.md        # GET /api/targets/{id}/report?format=md|html
│   ├── report-module.md     # build_report / render / recommend interfaces
│   └── ui-screen.md         # the Report section after Profile
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
src/kestrel/
├── report/                  # new package: the report, as a pure function over stored data
│   ├── __init__.py
│   ├── model.py             # build_report(...) -> ReportModel (pure; no I/O)
│   ├── owasp.py             # OWASP LLM Top 10 data: 3 tested classes + families, 7 untested + reasons
│   ├── render.py            # render_markdown(model) + render_html(markdown) (escaped, self-contained)
│   └── recommend.py         # recommendations_for(store, judge, runs, turns): SQLite cache + judge call on miss
├── judge/
│   └── client.py            # changed: add recommend(...) reusing the client's model/key/transport
├── store.py                 # changed: schema v5 — report_recommendations table; get/save recommendation
└── api/
    ├── main.py              # changed: GET /api/targets/{id}/report; orchestrates fetch → recommend → build → render
    └── schemas.py           # unchanged surface (the endpoint returns text, not a Pydantic model)

ui/
├── app.py                   # changed: render_report() after render_profile(); generate, two downloads, preview
└── api_client.py            # changed: get_report(target_id, format)

pyproject.toml               # changed: add markdown-it-py

tests/
├── unit/                    # report model + OWASP mapping + Markdown/HTML renderers (fixtures); judge.recommend; schema v5 migration
├── integration/             # GET /api/targets/{id}/report (md + html), empty state, secret-hygiene, recommendation caching
└── e2e/                     # optional: a report over the sacrificial target after a real run
```

**Structure Decision**: all report logic lives in a new `report/` package with a pure core (`model.py`, `render.py`, `owasp.py`) and one I/O-touching helper (`recommend.py`), so rendering and mapping are unit-testable with fixtures. `store.py` keeps all SQL (one new table + two methods). The API route is the only orchestrator that reads SQLite, reads the experience store read-only, and calls the judge. `attack/graph.py` is untouched (no new node).

## Deviations from the mockup and the diagram

[docs/architecture.html](../../docs/architecture.html) shows a report with a risk score mapped to the OWASP Top 10. This feature delivers the OWASP-mapped, fix-ready report; the single numeric **risk score** is the one piece still thinner:

| Mockup/diagram shows | This feature | Why |
|---|---|---|
| OWASP-mapped report with fix actions | Exactly this (coverage table + findings + recommendations) | The core of the feature. |
| A single risk score | Not included | The spec scopes the report to coverage + findings + honest limitations; a scored risk number is deferred (it needs a scoring model this feature does not define). |
| Attach-a-fix / re-scan loop | Recommendations only (suggestions) | Applying a fix and re-scanning is a later concern; findings are structured so a fix can attach later (Principle VI). |

## Complexity Tracking

| Item | Why needed | Simpler alternative rejected because |
|-----------|------------|-------------------------------------|
| New dependency: `markdown-it-py` | Derive the HTML report from the single Markdown source with reliable escaping (`html=False`, run content in code fences). The HTML file is opened in a browser, so escaping is security-critical (SC-008). | Hand-rolling a Markdown→HTML converter was considered and rejected: a subtle escaping bug would become stored XSS in a downloaded file; a vetted, pure-Python parser is safer and smaller than a correct hand-rolled one. Rendering HTML independently from the model was rejected: it contradicts "derive HTML from the Markdown" and risks the two formats drifting. |
| New SQLite table `report_recommendations` (schema v5) | Cache one recommendation per run id so regenerating a report makes no new model call (a feature requirement). | A column on `runs` loses model/timestamp provenance; an in-memory cache is lost on restart and re-calls the model. |
