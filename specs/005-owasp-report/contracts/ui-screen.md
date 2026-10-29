# Contract: Screen — Report section (feature 005)

Streamlit only renders and calls the API. The Report section is added to the main column **after the Profile section** and before Connection test. Deltas only.

## Report section (`render_report()` in `ui/app.py`)

- A `Report` subheader.
- No target selected → caption "Select a saved target to generate a report."
- A target with no runs → a clear empty state ("No runs to report yet — attack this target first"); no Generate button action produces a file.
- Otherwise: a **Generate report** button. On click, fetch the Markdown (`api_client.get_report(id, "md")`) and keep it in session.
- Once generated:
  - A **rendered preview** via `st.markdown(report_md, unsafe_allow_html=False)` — safe because run-derived content is fenced (shown as code) and raw HTML is escaped.
  - Two `st.download_button`s: **Download Markdown** (`text/markdown`, `.md`) and **Download HTML** (`text/html`, `.html`); the HTML is fetched via `api_client.get_report(id, "html")`.
- The section shows only report content (summaries, findings, recommendations labelled as suggestions) — never an auth value or URL.

## `api_client.py`

- Add `get_report(target_id, fmt)` → `GET /api/targets/{target_id}/report?format={fmt}`, returning the response text (not JSON).
