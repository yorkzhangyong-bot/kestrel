# Research: OWASP-Mapped, Fix-Ready Report (feature 005)

Decisions resolving the Technical Context. Each: Decision / Rationale / Alternatives. No attack text appears here.

## R1 — Module layout and the pure-function boundary

**Decision**: A new package `src/kestrel/report/`:
- `model.py` — `build_report(...) -> ReportModel`, a **pure function** over already-fetched data (target, runs, turns, recommendations, an optional experience summary, the OWASP map). No I/O.
- `owasp.py` — the OWASP LLM Top 10 reference data: the three tested classes and their families, and the seven untested classes each with a short reason.
- `render.py` — `render_markdown(model) -> str` (the single template) and `render_html(markdown) -> str` (derive HTML from the Markdown, escaped and self-contained).
- `recommend.py` — `recommendations_for(store, judge, runs, turns) -> dict[int, Recommendation]`, the only part that reads the SQLite recommendation cache, calls the judge for misses, and writes the cache.
The API route orchestrates: fetch from SQLite, read the experience store read-only, call `recommendations_for`, `build_report`, then render.

**Rationale**: Keeps the report builder and renderers pure and unit-testable with fixtures (the spec's test ask), with all I/O (SQLite, the judge, the experience store) at the edges. Mirrors how `attack/graph.py` was kept free of storage by taking a callable.

**Alternatives**: One big function that fetches and renders — rejected, not unit-testable without a database and a live model.

## R2 — Markdown is the single source; HTML is derived and escaped

**Decision**: Render the report once as Markdown from a single template. Derive HTML with **`markdown-it-py`** configured with `html=False` (raw HTML in the source is escaped, never passed through). All run-derived content (attacker messages, replies, judge notes) is emitted **inside fenced code blocks**, so the renderer escapes it into `<pre><code>…</code></pre>`. Wrap the body in a minimal, **self-contained** HTML document (inline `<style>`, no external CSS/JS/images), so opening the file loads nothing and runs nothing (SC-008).

**Rationale**: The feature requires HTML "derived from the Markdown with escaping". A vetted Markdown renderer with `html=False` plus code-fenced content is a security-critical path (a downloaded HTML file opened in a browser), and a battle-tested parser is safer here than hand-rolled escaping. `markdown-it-py` is pure-Python, widely used, no heavy transitive dependencies. New dependency justified under Principle X (one line in the plan).

**Alternatives**: Hand-roll a tiny Markdown→HTML converter (no dependency) — rejected: an escaping bug becomes stored XSS in a file users open; not worth the risk/maintenance. Render HTML from the model independently of the Markdown — rejected: contradicts "derive HTML from the Markdown" and risks the two formats drifting.

## R3 — Recommendation caching in SQLite (schema v5)

**Decision**: Add a `report_recommendations` table (schema version 4 → 5, additive): `run_id` (PK, FK to `runs` `ON DELETE CASCADE`), `recommendation` TEXT, `model` TEXT, `created_at` TEXT. `recommendations_for` reads a run's cached recommendation; on a miss it calls the judge once and writes the row. Regenerating a report reuses the cache and makes no new model call.

**Rationale**: The feature requires caching per run id so regeneration does not re-call the model. A dedicated table keeps the provenance (which model, when), cascades away with the run/target, and is a clean additive migration (the v3/v4 pattern).

**Alternatives**: A `recommendation` column on `runs` — simpler but mixes report state into the run row and loses the model/timestamp provenance. An in-memory cache — rejected: lost on restart, re-calls the model.

## R4 — Recommendations use the existing judge client

**Decision**: Add a `recommend(*, family, owasp_category, attack, evidence, timeout) -> (str, int)` method to `JudgeClient`, reusing its model, key, base URL and transport. It is one chat call with a system prompt asking for a short, concrete fix to the target's system prompt or tool configuration, and a user message carrying only **non-secret run data** (the family, the OWASP class, the winning attacker message, the evidence or judge note). One call per successful run. The renderer labels every recommendation a suggestion.

**Rationale**: The spec clarified recommendations reuse the configured judge model, one call per success. Adding a sibling method reuses the existing, tested HTTP plumbing and the same model/key — no new client, no new secret. Sending only non-secret fields satisfies FR-018.

**Alternatives**: A separate report-model client/setting — rejected by clarification (reuse the judge). Reuse `judge()` as-is — rejected: it returns a verdict, not advice; a distinct prompt is needed.

## R5 — Reading the experience store, read-only

**Decision**: When building the report, read the experience store **read-only** for two counts — this target's memory records and the shared pattern count — and surface them in the limitations note ("results were influenced by N memory records for this target and the shared pattern library"). This is best-effort: if the store is unavailable, the note omits the counts rather than failing. The report **never writes** to the experience store and never retrieves pattern/memory *content* into the report body.

**Rationale**: Honours the plan's "reads the learned patterns from the experience store read-only" and makes the limitations note concrete (memory and patterns affect results, FR-015), while keeping Principle V's write-back untouched and avoiding any secret/attack content from the store.

**Alternatives**: Ignore the store entirely — simpler, but the limitations note would be vaguer and it would not honour the plan input. Include pattern/memory text — rejected: unnecessary and risks surfacing content that belongs in the store, not a shareable report.

## R6 — OWASP mapping data

**Decision**: `report/owasp.py` holds the fixed OWASP LLM Top 10 (2025) list. The three tested classes map to families via the attack library's canonical `owasp_category` (already stored on each run): **LLM01 Prompt Injection** (direct & indirect injection), **LLM06 Excessive Agency** (tool-mediated exfiltration), **LLM07 System Prompt Leakage** (system-prompt leak). The seven untested — LLM02, LLM03, LLM04, LLM05, LLM08, LLM09, LLM10 — each carry a short, honest reason (e.g. LLM09 Misinformation is quality not security, Principle I; LLM10 Unbounded Consumption would need load/DoS, barred by Principle VIII; the rest need target internals, training/supply-chain access, or downstream output handling a black-box chat attacker cannot reach).

**Rationale**: Clarified to use the code/OWASP canonical labels. Deriving each run's class from its stored `owasp_category` keeps the coverage table consistent with what actually ran.

**Alternatives**: Re-derive the class from the family at report time — equivalent, but reading the stored `owasp_category` is the source of truth for that run.

## R7 — API endpoint and preview safety

**Decision**: `GET /api/targets/{id}/report?format=md|html` (default `md`) returns the report as `text/markdown` or `text/html`. The Streamlit Report section calls it, previews the Markdown with `st.markdown(..., unsafe_allow_html=False)` (safe: run content is fenced, so it renders as code, and raw HTML is escaped), and offers two `st.download_button`s (Markdown, HTML). `404` if the target is missing; a target with no runs returns the empty-state content (not an error).

**Rationale**: One endpoint, two formats, matches the spec. `st.markdown` with `unsafe_allow_html=False` over fenced content is a safe rendered preview, consistent with SC-007/SC-008.

**Alternatives**: Render the derived HTML inside the UI via an HTML component — rejected: would execute any leaked script; the Markdown preview is safe. Two endpoints (`/report.md`, `/report.html`) — rejected: one endpoint with a `format` parameter is simpler.

## R8 — Empty state and the safety invariants

**Decision**: With no runs, both the endpoint and the UI show a clear empty state, make zero model calls, and produce no file. Report generation issues zero sends to the target and zero writes to the experience store (it only reads). The report output excludes the target URL, auth header names/values and any secret; stored run text is already masked and is reproduced verbatim as-stored.

**Rationale**: FR-003, FR-016, FR-019 and SC-006/SC-007/SC-009. The report is inert and safe to generate anytime.

**Alternatives**: none.
