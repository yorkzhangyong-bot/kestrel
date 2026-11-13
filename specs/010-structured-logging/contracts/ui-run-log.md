# Contract: the run page's log viewer (Streamlit)

`ui/app.py` renders an opened run's kept log under its finding card. The screen holds no logic: it calls
`api_client.get_run_log(run_id)` (`GET /api/runs/{run_id}/log`) and displays what comes back. It never reads a
file or the database.

## Where

Inside `_render_finding` (so it appears both on the result shown right after a run and when a run is opened from
the Runs tab's "Open a run" selector): a collapsed `st.expander("Log")` — one click from the opened run (SC-003).
It is rendered for **every** opened run: `_render_finding` returns early for a run whose send failed (it shows the
failure message and stops), so the expander is rendered **before** that early return — a send-failed run has a run
id and kept lines (run-start, target-request, turn, memory.writeback, run-end) and must show them (FR-012).

## What

| State | Rendering |
|-------|-----------|
| `lines` non-empty | `st.dataframe` of the columns **Time**, **Event**, **Turn**, **Model**, **Prompt**, **Latency ms**, **Tokens**, **Cost** — one row per line, a cell blank when the line has no such field (`ts`, `event`, `turn`, `model`, `prompt`, `latency_ms`, `total_tokens`, `cost_usd`); then `st.code("\n".join(json.dumps(line) for line in lines), language="json")` with the raw lines |
| `truncated` true | the table and raw view above, plus `st.caption(f"Log truncated: {dropped} line(s) were not kept after the first {kept}.")` and the marker line itself as the last row |
| `lines` empty | `st.caption("No log lines were recorded for this run.")` — no table, no error |
| API error (unreachable, 404, 401) | `st.error(api_message(error))` as the rest of the screen does |

Raw lines are shown with `st.code` only (never markdown), like every other text the screen does not author; every
value comes from the API's allow-listed records, so the viewer can carry no secret, URL, target name, prompt or
reply text (FR-009, SC-002).

## Client

```python
# ui/api_client.py
def get_run_log(run_id: int) -> dict[str, Any]:
    return _request("GET", f"/api/runs/{run_id}/log")
```

## Verification

Streamlit `AppTest` with `api_client` stubbed (the feature-009 UI test pattern): a run with lines shows the
expander, the table's columns and the raw JSON; a run whose send failed (`failure_step` set) shows the failure
message **and** the expander; an empty list shows the caption; a truncated log shows the dropped count; none of a
known secret, URL, name, message or reply appears in any rendered element (SC-002).
