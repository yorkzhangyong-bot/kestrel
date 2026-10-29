# Contract: Report module (`src/kestrel/report/`)

## `model.build_report(...) -> ReportModel` (pure)

```text
build_report(*, target, runs, turns_by_run, recommendations, experience_summary=None, now) -> ReportModel
```

- `target`: the `Target` (name, description).
- `runs`: the target's `Run` list (newest-first).
- `turns_by_run`: `{run_id: [Turn, ...]}` for adaptive runs.
- `recommendations`: `{run_id: Recommendation}` for succeeded runs that have one (may be empty).
- `experience_summary`: `{memory_count, pattern_count}` or `None`.
- `now`: the generation timestamp.

Pure: no database, no model, no clock of its own. Produces the `ReportModel` (header, coverage rows, findings, other runs, limitations, `is_empty`) per [data-model.md](../data-model.md). Findings appear only for `verdict == "succeeded"`; hard-evidence findings carry the stored evidence verbatim, judge-only findings carry the judge note marked "suspected".

## `render.render_markdown(model) -> str`

One template producing the five sections in order: header, OWASP coverage table + untested-classes list, findings, failed/unclear runs, limitations. **All run-derived content (winning messages, evidence, judge notes) is emitted inside fenced code blocks.** Recommendations are rendered under a clear "Suggestion" label. An empty model renders the empty-state message only.

## `render.render_html(markdown) -> str`

Derive HTML from the Markdown with `markdown-it-py` (`html=False`, so raw HTML in the source is escaped, never passed through), wrapped in a minimal self-contained HTML document (inline `<style>`, no external resources). Fenced code blocks become escaped `<pre><code>`; opening the file executes nothing and loads nothing.

## `recommend.recommendations_for(store, judge, runs, turns_by_run) -> dict[int, Recommendation]`

The only I/O-touching report function. For each **succeeded** run: return the cached recommendation from `report_recommendations` if present; otherwise, if the judge is configured, call `judge.recommend(...)` once with **non-secret** inputs (family, OWASP class, winning message, evidence/judge note), cache the result (`save_recommendation`), and return it. Skips runs with no judge key (FR-013). Never calls the target, never writes the experience store.

## `JudgeClient.recommend(...)` (added)

```text
recommend(*, family, owasp_category, attack, evidence, timeout=None) -> (recommendation: str, tokens: int)
```

One chat call reusing the judge's model, key, base URL and transport, with a system prompt asking for a short, concrete fix to the target's system prompt or tool configuration, and a user message carrying only the non-secret fields above. Raises `JudgeError` if not configured or the call fails (the caller then omits that recommendation).
