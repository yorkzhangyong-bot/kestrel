# Quickstart & validation: OWASP-Mapped, Fix-Ready Report (feature 005)

How to prove the report works. Details live in [data-model.md](./data-model.md) and [contracts/](./contracts/). No attack text is needed.

## Prerequisites

- `uv sync` (now pulls in `markdown-it-py`).
- A judge key (`KESTREL_JUDGE_API_KEY` or `OPENROUTER_API_KEY`) for recommendations; without one, findings still show evidence with a "no recommendation available" note.
- Run locally:

```bash
# terminal 1 — API
KESTREL_MODE=local OPENROUTER_API_KEY=sk-or-... uv run uvicorn --factory kestrel.api.main:create_app --host 127.0.0.1 --port 8000
# terminal 2 — screen
uv run streamlit run ui/app.py
```

Attack a saved target a few times first (single-turn or adaptive) so there is something to report.

## Automated tests

```bash
uv run pytest                                 # unit + integration, offline (stub judge), no keys
uv run pytest -m e2e                          # the report e2e (T027): a report after a real run
uv run --directory targets/hs_code pytest     # unchanged
```

## Checks (map to FR/SC)

1. **Generate + both formats** (SC-001): with a target that has runs, `GET /api/targets/{id}/report?format=md` and `?format=html` both return `200`; the UI Report section (after Profile) shows a preview and both download buttons; the two formats carry the same content.
2. **Header** (FR-005, SC-010): the header shows target name, purpose, generation time, run count, and the attacker and judge models, token budget and tokens used.
3. **Coverage** (FR-006/7/8, SC-005): the table lists exactly the three tested classes (LLM01 Prompt Injection, LLM06 Excessive Agency, LLM07 System Prompt Leakage) with per-class run counts; a family with 0 runs shows "not run yet"; the report lists the seven untested classes, each with a reason.
4. **Findings** (FR-009–FR-013, SC-002/3/4): exactly one finding per succeeded run and none for others; canary successes quote the evidence byte-for-byte; judge-only successes show the note marked "suspected"; every recommendation is labelled a suggestion (or a "no recommendation available" note with no judge key).
5. **Failed/unclear + limitations** (FR-014/15): one line per non-success run; a closing note that includes the memory/learned-pattern caveat.
6. **No secrets** (FR-016/17/18, SC-006): the target's key, URL and header names never appear in the Markdown or HTML.
7. **HTML is inert** (FR-017, SC-008): open the HTML report containing a run with HTML/script content — it is shown as text, executes 0 scripts and loads 0 external resources.
8. **Read-only** (FR-003, SC-007): generating a report makes 0 sends to the target and 0 writes to the experience store.
9. **Recommendation caching** (FR-012): generating a report twice makes the judge calls only on the first generation (the second reads `report_recommendations`); at most one call per succeeded run.
10. **Empty state** (FR-019, SC-009): a target with no runs shows a clear empty state with 0 model calls and no file, in the UI and from the API.

## Notes

- Offline tests use a stub judge and fixtures for the report model/renderers, so `uv run pytest` makes no network call. Schema moves SQLite `4 → 5` (adds `report_recommendations`); existing data is unaffected.
- The report reads the experience store read-only for the memory/pattern counts in the limitations note; it never writes it and never runs an attack.
