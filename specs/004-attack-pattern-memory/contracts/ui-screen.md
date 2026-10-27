# Contract: Screen additions (feature 004)

Streamlit only renders and calls the API (unchanged rule). All new text is shown as plain text; nothing from a target, a summary, or a hint is ever rendered as markup (feature 002, SC-007). Deltas only.

## Target form — purpose description (FR-020, US3)

- A single optional text input, "What is this agent for?", with a caption "One line. No sensitive info — it is stored in plain and shown to the attacker." (key e.g. `description`).
- Sent as `description` on save/update; pre-filled when editing; empty → `null`.
- Editing it alone does not require a new connection test.

## Attack panel — use prior experience (FR-014, US2)

- A "Use prior experience" toggle beside the Single-turn/Adaptive mode toggle, defaulting to **on** (from `config.experience.use_prior_experience_default`).
- A caption explaining warm vs cold in one line (e.g. "On: the attacker is given similar past patterns and this target's memory as hints. Off: a cold run, like before.").
- Sent as `use_prior_experience` on `POST /api/runs`. Meaningful for adaptive runs; for single-turn it is recorded only.

## Run result — write-back warning (FR-010)

- When a finished run's `memory_written` is `false`, show a visible warning on the result (e.g. "⚠️ This run's result was saved, but it could not be written to the experience store."). `true`/`null` → no warning.

## Target profile (FR-022, FR-023, US4)

- A "Profile" section under the selected target (or a clearly-labelled expander), calling `GET /api/targets/{id}/profile`:
  - total runs; counts by family; counts by verdict; the recent one-line summaries (newest first).
  - Empty target → a plain empty-state line ("No runs recorded yet."), not an error.
  - Shows only summaries and non-secret metadata — never an auth value (SC-004).

## api_client.py

- `save_target` / `update_target` pass `description`.
- `run_attack` passes `use_prior_experience`.
- New `get_profile(target_id)` → `ProfileOut`.
- `run_attack` timeout is unchanged (360 s); retrieval and write-back are local and fast.
