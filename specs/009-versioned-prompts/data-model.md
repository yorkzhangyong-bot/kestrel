# Phase 1 Data Model: Versioned Prompts (009)

Entities and schema changes. Column names are proposals for `/speckit-tasks`; all DB changes are **additive**
(nullable columns) on top of `SCHEMA_VERSION "6" → "7"`.

## Registry ids (the versioned prompts)

Three model-facing prompt kinds (D5 — no summariser prompt exists):

| id | Source of `text` (review amendment, D12) | Notes |
|----|------------------------------------------|-------|
| `attacker:<family>` | `src/kestrel/prompts/attacker_<family>.v<N>.md` | one file per family and version (e.g. `attacker_direct_injection.v1.md`); the family's goal sentence is authored into the text |
| `judge` | `src/kestrel/prompts/judge.v<N>.md` | the verdict prompt |
| `recommender` | `src/kestrel/prompts/recommender.v<N>.md` | the fix-advice prompt |

Each file is a YAML front-matter naming `id` and `version` above the text; `text` is everything below it minus
leading/trailing newlines. The front-matter `id` is authoritative (the file name maps `:` to `_`). No prompt text
lives in Python.

The shared `DATA_RULE`/`fence` scaffolding (`prompting.py`) is **excluded** from `text` and the fingerprint (D7).

## Entity: PromptEntry (registry entry, in-process)

Built by `src/kestrel/prompt_registry.py`; not a DB row.

| Field | Type | Rules |
|-------|------|-------|
| `id` | str | one of the registry ids above; stable |
| `version` | str | a positive integer (`"1"`, `"2"`, …; D12), validated by regex; the **active** version for this id = the highest file |
| `text` | str | the authored template text (static; attacker resolved per family) |
| `fingerprint` | str | `sha256(text)` hex (D1); MUST equal the lock entry for `(id, version)` |

**Invariants**: one `(id, version)` → exactly one `text`/`fingerprint` (FR-005); a `(id, version)` is registered iff
its file exists (FR-009 authority: `has()`); seeded active version is `1` with today's text (FR-002).

## Entity: Fingerprint lock (committed)

`src/kestrel/prompt_versions.lock.json` — `{ "<id>": { "<version>": "<sha256>" } }` (D12; no `active` key — the
active version is the highest file). Fingerprints only, never text. Append-only; a present `(id, version)`
fingerprint is immutable (FR-005; `scripts/bump_prompt.py --lock` refuses to re-record one unless `--force`, and
review enforces the rest). The guard (FR-006, `verify_lock()`) fails naming the prompt when a file's text does not
match its pinned fingerprint, when a version file has no lock entry, when a pinned version has no file, or when a
file is malformed (named by file name).

## Schema v7 — provenance columns (all nullable; NULL = "not recorded", FR-004)

**`run_turns`** (adaptive turns; `store.py:96-106`) — add:
- `attacker_prompt_id` TEXT — the `attacker:<family>` id that produced the turn
- `attacker_prompt_version` TEXT
- `judge_prompt_id` TEXT — `judge` (the per-turn verdict's prompt)
- `judge_prompt_version` TEXT

**`runs`** (overall / single-turn verdict; `store.py:72-76`) — add:
- `judge_prompt_id` TEXT, `judge_prompt_version` TEXT

Written where the values are already written: `add_turn(...)` (`store.py:570`) for turns; `finish_run(...)`
(`store.py:543`) for the run verdict. Read back on the `Run` (`judge_prompt_id/version`) and `Turn`
(`attacker_prompt_id/version`, `judge_prompt_id/version`) dataclasses, which the report header uses: `Header`
gains `attacker_prompts` and `judge_prompts` — the distinct `id@version` values the runs recorded, or
`not recorded` for a judged run / attacker-produced turn that predates v7 (review amendment). Single-turn library attacks carry no attacker-prompt provenance (they use the
attack library's existing `attacker_source = "library:<ver>"`, not the attacker model prompt); attacker-prompt
provenance applies to adaptive `run_turns`.

**Migration**: extend `_migrate` accepted-prior set to include `"6"`; add the columns via the ALTER-tuple mechanism
(like `ADAPTIVE_RUN_COLUMNS`); bump the `meta` version to `"7"`.

## Schema v7 — experiment arm columns

**`experiment_arms`** (`store.py:138-150`) — add:
- `prompt_arm_target` TEXT NULL — a registry id, restricted to `attacker:<family>` or `judge` (D10)
- `prompt_arm_version` TEXT NULL — the version this arm pins for that prompt

`ExperimentArm` dataclass (`store.py:276-287`) gains the two fields. `ARM_DIFF_FIELDS` (`schemas.py:339`) gains
`prompt_arm_target`, `prompt_arm_version` so `experiment_diff` renders e.g. `prompt: A=judge@1, B=judge@2`.
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

`scripts/bump_prompt.py <id>` copies the active file to `v<N+1>` (front-matter `version: N+1`) → the new file is
the active version but the guard is red (unpinned) → the author edits the text → `scripts/bump_prompt.py <id>
--lock` records `(N+1 → fingerprint)` in the lock → green. Editing a pinned file without a bump → guard fails
naming the prompt. Prior files and their `(id, version)` fingerprints remain for historical provenance and for
A/B arms. No DB rows change; old runs keep the version they recorded.
