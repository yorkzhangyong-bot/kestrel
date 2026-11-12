# Phase 1 Data Model: Versioned Prompts (009)

Entities and schema changes. Column names are proposals for `/speckit-tasks`; all DB changes are **additive**
(nullable columns) on top of `SCHEMA_VERSION "6" → "7"`.

## Registry ids (the versioned prompts)

Three model-facing prompt kinds (D5 — no summariser prompt exists):

| id | Source of `text` | Notes |
|----|------------------|-------|
| `attacker:<family>` | `SYSTEM_PROMPT.format(goal=GOALS[family])` in `attack/attacker.py` | one per family in `GOALS` (e.g. `attacker:direct_injection`); `{goal}` is authored, not runtime data |
| `judge` | `SYSTEM_PROMPT` in `judge/client.py` | the verdict prompt |
| `recommender` | `RECOMMEND_SYSTEM_PROMPT` in `judge/client.py` | the fix-advice prompt |

The shared `DATA_RULE`/`fence` scaffolding (`prompting.py`) is **excluded** from `text` and the fingerprint (D7).

## Entity: PromptEntry (registry entry, in-process)

Built by `src/kestrel/prompt_registry.py`; not a DB row.

| Field | Type | Rules |
|-------|------|-------|
| `id` | str | one of the registry ids above; stable |
| `version` | str | `MAJOR.MINOR.PATCH`, validated by regex (D2); the **active** version for this id |
| `text` | str | the authored template text (static; attacker resolved per family) |
| `fingerprint` | str | `sha256(text)` hex (D1); MUST equal the lock entry for `(id, version)` |

**Invariants**: one `(id, version)` → exactly one `text`/`fingerprint` (FR-005); every active `(id, version)` exists
in the lock (FR-009 authority); seeded active version is `1.0.0` with today's text (FR-002).

## Entity: Fingerprint lock (committed)

`src/kestrel/prompt_versions.lock.json` — `{ "<id>": { "active": "<version>", "versions": { "<version>": "<sha256>" } } }`.
Fingerprints only, never text. Append-only; a present `(id, version)` fingerprint is immutable (FR-005, enforced in
review). Non-active versions keep their **text** as template files beside the active prompts
(`src/kestrel/prompt_templates/<id with ':'→'_'>@<version>.txt`); the active version's text is the live code
constant. The guard (FR-006, `verify_lock()`) asserts every registered version's resolved text (code for the active
version, the template file for a non-active one) matches its pinned fingerprint, and fails naming the prompt on a
mismatch or a missing file.

## Schema v7 — provenance columns (all nullable; NULL = "not recorded", FR-004)

**`run_turns`** (adaptive turns; `store.py:96-106`) — add:
- `attacker_prompt_id` TEXT — the `attacker:<family>` id that produced the turn
- `attacker_prompt_version` TEXT
- `judge_prompt_id` TEXT — `judge` (the per-turn verdict's prompt)
- `judge_prompt_version` TEXT

**`runs`** (overall / single-turn verdict; `store.py:72-76`) — add:
- `judge_prompt_id` TEXT, `judge_prompt_version` TEXT

Written where the values are already written: `add_turn(...)` (`store.py:570`) for turns; `finish_run(...)`
(`store.py:543`) for the run verdict. Single-turn library attacks carry no attacker-prompt provenance (they use the
attack library's existing `attacker_source = "library:<ver>"`, not the attacker model prompt); attacker-prompt
provenance applies to adaptive `run_turns`.

**Migration**: extend `_migrate` accepted-prior set to include `"6"`; add the columns via the ALTER-tuple mechanism
(like `ADAPTIVE_RUN_COLUMNS`); bump the `meta` version to `"7"`.

## Schema v7 — experiment arm columns

**`experiment_arms`** (`store.py:138-150`) — add:
- `prompt_arm_target` TEXT NULL — a registry id, restricted to `attacker:<family>` or `judge` (D10)
- `prompt_arm_version` TEXT NULL — the version this arm pins for that prompt

`ExperimentArm` dataclass (`store.py:276-287`) gains the two fields. `ARM_DIFF_FIELDS` (`schemas.py:339`) gains
`prompt_arm_target`, `prompt_arm_version` so `experiment_diff` renders e.g. `prompt: A=judge@1.0.0, B=judge@1.1.0`.
`validate_experiment` (`schemas.py:342`) treats a prompt-version difference as a valid arm distinction.

**Validation (refuse before any model call, FR-008/FR-009)**:
- `prompt_arm_target`, when set, MUST be an `attacker:<family>` or `judge` id — a `recommender` target (or any
  non-attacker/non-judge id) is rejected;
- `(prompt_arm_target, prompt_arm_version)` MUST exist in the registry.

## Entity: PromptVersionOut (API)

`ConfigOut` (`schemas.py:55-62`) gains `prompts: list[PromptVersionOut]`, each `{ id: str, version: str }`, from the
registry's active entries. No text, no fingerprint on the wire (FR-007/SC-004). Hosted mode: the call carries
`X-Kestrel-Token` (unchanged auth).

## State transition: bumping a prompt

`edit text` → guard fails (live fingerprint ≠ lock active) → author raises `version` and appends
`(new version → new fingerprint)` to the lock → active version advances; prior `(id, version)` fingerprints remain
for historical provenance. No DB rows change; old runs keep the version they recorded.
