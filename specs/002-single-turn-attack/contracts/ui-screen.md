# Contract: Streamlit screen — feature 002 additions

Additions to [feature 001's screen contract](../../001-register-target/contracts/ui-form.md), which still holds. Layout follows [docs/ui-mockup.html](../../../docs/ui-mockup.html); the deviations and their reasons are in [plan.md](../plan.md).

## Rules for the UI

Unchanged from feature 001, and they now also cover attack text:

- It calls only the API in [kestrel-api.md](./kestrel-api.md), and imports nothing from the `kestrel` package.
- It holds no product rules. Families, prompts, limits and messages come from the API.
- Text that comes from a target or from the library — `reply_text`, `prompt_text`, `reason` — is shown only with `st.code(text, language=None)` or `st.text`, never with `st.markdown` or `st.write` (FR-032, FR-033).
- `st.success` and `st.error` carry only Kestrel's own wording.

## Sidebar additions

Inserted after the **Auth headers** rows (row 4 in feature 001), keeping the rest in order:

| # | Widget | Behaviour |
|---|---|---|
| 4b | **Canary strings** rows, captioned "put these in your agent, so a leak is provable" | Each row is a plain text input plus a **✕** button with the tooltip "Remove this canary". **Add canary** appends a row. Shown in full, never masked. An entry under 8 characters shows the API's message at that row |
| 11b | Caption with the judge | "Judging uses `<model>`" or, when `judge.configured` is false, "No judge configured: only canary evidence can decide a run" |

Changing canaries does not disable **Save target** and does not require a new connection test.

## Main area

A new **Attack** panel, above feature 001's Connection test panel:

| # | Widget | Behaviour |
|---|---|---|
| 1 | Select **Attack family** | From `GET /api/attack-families`, labelled "Direct prompt injection · LLM01: Prompt Injection (6 prompts)" |
| 2 | Select **Prompt** | "Kestrel picks one" by default, then each prompt by title. Picking one shows its text in `st.code` before it is sent |
| 3 | Button **Run attack** | Disabled while a run is in progress, and when no saved target is selected. Shows a spinner naming the 90-second ceiling |
| 4 | Result | After a run |

Before the first run the panel reads "Pick a saved target, choose an attack family, and click Run attack."

**Result**, after a run:

| Outcome | What it shows |
|---|---|
| `succeeded`, hard evidence | `st.error("Attack succeeded · confirmed by canary")`, then the prompt and the reply in `st.code`, then the reason |
| `succeeded`, judge | `st.error("Attack succeeded · suspected, judged by <model>")`, same below |
| `failed` | `st.success("Attack failed · the agent held · judged by <model>")` |
| `unclear` | `st.warning("Unclear · judged by <model>")`, or the judge-failure reason when there was no verdict |
| Send failed | `st.error(<the feature 001 message for that step>)`, no verdict shown |

"Confirmed" appears only with hard evidence; a judge verdict always says "suspected" and names the model (FR-018, Principle II). A successful attack is an error-coloured result, because it is bad news about the user's agent.

**Runs** table (`st.dataframe`) under the panel, for the selected target: when it ran, attack family, prompt title, verdict, evidence ("canary" or "judge · `<model>`"). Newest first (FR-028). Selecting a row opens its detail — prompt, reply, reason — in `st.code`.

With no saved target selected the table is replaced by "Select a saved target to see its runs."

## Blocked runs

Three API refusals are shown at the Attack panel rather than as generic errors:

| Code | Shown |
|---|---|
| `permission_missing` | "Tick the permission box and save the target before attacking it." |
| `terms_outdated` | "The terms of service have changed; read them and tick the box again." with the terms expander opened |
| `run_in_progress` | "A run against this target is already in progress." |

## Session behaviour

- The Run button is claimed in session state before the API call, the way feature 001 claims a pending test, so a rerun during a run cannot send a second one.
- After a run finishes, the runs list for that target is reloaded.
- Selecting another target clears the attack result and reloads its runs.
- The client timeout for `POST /api/runs` is 120 seconds, above the API's own 90-second ceiling.
