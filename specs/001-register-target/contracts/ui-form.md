# Contract: Streamlit screen

`ui/app.py` with `ui/api_client.py`. Layout follows the sidebar of [docs/ui-mockup.html](../../../docs/ui-mockup.html); the deviations and their reasons are listed in [plan.md](../plan.md).

## Rules for the UI

- It calls only the API in [kestrel-api.md](./kestrel-api.md), and it imports nothing from the `kestrel` package. An integration test checks this.
- It holds no product rules. Defaults, terms and mode come from `GET /api/config`, and validation messages come from the API.
- Text that comes from a target (`reply_text`, `detail`) is shown only with `st.code(text, language=None)` or `st.text`, never with `st.markdown` or `st.write` (FR-007, SC-008).
- `st.success` and `st.error` carry only Kestrel's own wording.

## Sidebar, top to bottom

| # | Widget | Behaviour |
|---|---|---|
| 1 | Select **Target**: "New target", then saved targets as "name · URL" | Choosing a target loads its details. Choosing anything starts a new `form_id` |
| 2 | Text input **Display name** | |
| 3 | Select **Method** (POST, GET) and text input **Endpoint URL** | Defaults from `/api/config` |
| 4 | **Auth headers** rows, captioned "stored encrypted, never shown in report" | Each row has a name input and a masked value input (`type="password"`) plus **Remove**. **Add header** appends a row. A stored value shows as an empty field with the placeholder "Stored · leave empty to keep" and is sent as `value: null` |
| 5 | Text inputs **Request body template** and **Response path** | Defaults from `/api/config` |
| 6 | Button **Test connection** | Disabled while a test runs. The API also refuses a second test (FR-009) |
| 7 | Checkbox **I own this agent or have written permission to test it** | Cleared when the URL of a saved target is changed (FR-018) |
| 8 | Expander **Terms of service (version N)** | Shows the terms text; opening it keeps the form input (scenario 2.6) |
| 9 | Button **Save target** | Sends `permission_confirmed` and `terms_version`. API errors are shown at the matching field |
| 10 | Saved targets only: **Delete target**, then **Confirm delete** and **Cancel** | Two steps instead of a pop-up dialog (FR-019) |
| 11 | Caption with the mode | "Running locally", or "Running hosted: local and private addresses are blocked" |

## Main area

**Connection test** panel, after a test:

| Outcome | What it shows |
|---|---|
| Success | `st.success("Connection works · status 200 · 3.1 s")`, then the reply in `st.code(reply_text, language=None)`. Shows "(empty reply)" when the reply is empty, and a caption when it was cut to 2,000 characters |
| Failure | `st.error(message)`, then `st.code(detail, language=None)` if there is a detail |

**Saved targets** table (`st.dataframe`) with name, URL, method, permission confirmed (date) and terms version (FR-015).

## Session behaviour

- A new `form_id` is created when another target is selected, after a save and after a delete.
- After a save, the header values typed into the form are cleared from the session.
