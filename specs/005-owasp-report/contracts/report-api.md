# Contract: Report API

## `GET /api/targets/{target_id}/report`

Generate and return the report for one target. Read-only: it starts no run, sends nothing to the target, and writes nothing to the experience store.

**Query parameters**

- `format`: `md` (default) or `html`. Any other value → `422` form error on `format`.

**Responses**

- `200` with the report body:
  - `format=md` → `text/markdown; charset=utf-8`, the Markdown report.
  - `format=html` → `text/html; charset=utf-8`, a self-contained HTML document derived from that Markdown (escaped; no external CSS/JS/images).
- A target **with no runs** → `200` with the empty-state body ("No runs to report yet — attack this target first"); no model call, no finding.
- `404 not_found` if the target does not exist.

**Behaviour**

1. Load the target (`404` if missing) and its runs and conversation turns from SQLite.
2. For each **succeeded** run, obtain its recommendation via `recommendations_for` — from the `report_recommendations` cache, or one judge call on a miss (then cached). Zero model calls when there are no successes or no judge key.
3. Read the experience store **read-only** for this target's memory count and the shared pattern count (best-effort; omitted from the note if unavailable).
4. `build_report(...)` → `render_markdown` → (`render_html` if `format=html`).
5. The body contains no target URL, no auth header names/values, no secret; hard evidence is reproduced byte-for-byte as stored (already masked).

**Not included** (out of scope): per-run report endpoints, PDF, CSV, scheduling.
