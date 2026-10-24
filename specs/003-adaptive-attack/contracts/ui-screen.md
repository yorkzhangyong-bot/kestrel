# Contract: Streamlit screen — feature 003 additions

Additions to [feature 002's screen contract](../../002-single-turn-attack/contracts/ui-screen.md), which still holds. Only the new surface is described; behaviour and layout only, no attack text.

## Rules for the UI

Unchanged from feature 002, and they now also cover the conversation:

- The screen calls only the API; it holds no product rules. The mode options, caps and attacker/judge models come from `GET /api/config`.
- Attacker messages, target replies and the judge's reason and "how close" note are shown only with `st.code(..., language=None)` or `st.text`, never `st.markdown`/`st.write` (FR-024, SC-007).
- `st.success`/`st.error`/`st.warning` carry only Kestrel's own wording.

## Attack panel additions

| # | Widget | Behaviour |
|---|---|---|
| 1 | **Mode** toggle: Single-turn / Adaptive | Defaults to Single-turn (feature 002). Reuses the same family and prompt controls and the one Run button (FR-001). The chosen mode rides the run request as `mode` |
| 2 | **Run attack** button | For Adaptive, disabled when `attacker.configured` is false, with a caption saying no attacker is configured (FR-016); the client timeout exceeds the wall-clock cap |
| 3 | Caption with the attacker and caps | "Adaptive: attacker `<model>`, up to `<max_turns>` turns" when Adaptive is selected, from `/api/config` |

## Result and run detail

After an adaptive run, and when an adaptive run is opened from the Runs table, the main area shows the **conversation turn by turn** (FR-023):

| Part | What it shows |
|---|---|
| Verdict banner | As feature 002: "Attack succeeded · confirmed by canary", "· suspected, judged by `<model>`", "Attack failed · …", or "Unclear"; plus how it ended (succeeded at turn N, or stopped at the turn/token/time cap) |
| Each turn, in order | The attacker's message and the target's reply, each in `st.code`, labelled by who sent it; the turn's judge note shown as `st.text` |
| Footer | The attacker model, the judge model, the budgets allowed and used (turns, tokens, time) — Principle III |

A single-turn run opened from the table displays exactly as in feature 002 (one prompt, one reply); the kind is taken from the run's `mode`.

## Runs table

The existing Runs table (feature 002) gains a **Mode** column (single-turn / adaptive); otherwise unchanged — newest first, with verdict and evidence, each run openable (FR-022, US2.2).

## Session behaviour

- The Run button is claimed in session state before the call, so a rerun cannot double-send (as feature 002).
- Selecting the mode does not clear the chosen family or prompt.
- After an adaptive run finishes, the target's runs list is reloaded so the new run appears.
