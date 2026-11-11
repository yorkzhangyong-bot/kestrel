# Phase 0 Research: Versioned Prompts (009)

All decisions respect Principle X (no new runtime dependency) and the clarifications recorded in `spec.md`
(API-not-CLI surface; version/fingerprint over the **authored template text**; A/B arm limited to attacker/judge).

Code facts this builds on (verified): attacker prompt = `SYSTEM_PROMPT` + per-family `GOALS` in
`src/kestrel/attack/attacker.py` (`{goal}` is a *static authored* slot; runtime hints/conversation are separate
messages); judge `SYSTEM_PROMPT` and recommender `RECOMMEND_SYSTEM_PROMPT` in `src/kestrel/judge/client.py`;
shared `DATA_RULE`/`fence()` in `src/kestrel/prompting.py`; `SCHEMA_VERSION = "6"` with an additive
`TargetStore._migrate` in `src/kestrel/store.py`; `ExperimentArm` + `experiment_arms` + `ARM_DIFF_FIELDS` arm-diff
recomputed in `src/kestrel/api/schemas.py`; `GET /api/config` → `ConfigOut`; judge eval in
`tests/eval/test_judge_accuracy.py`.

---

## D1 — Content fingerprint: stdlib `hashlib.sha256`
- **Decision**: fingerprint = `hashlib.sha256(text.encode("utf-8")).hexdigest()` over the authored template text.
- **Rationale**: stdlib only (Principle X); `hashlib` is already used in `src/kestrel/connection/sessions.py`. A hash
  reveals no text, so it is safe to show (FR-012/SC-007).
- **Alternatives**: md5 (weaker, no upside); an external hashing lib (needless dependency).

## D2 — Semantic version is an opaque, validated label (no semver library)
- **Decision**: versions are `MAJOR.MINOR.PATCH` strings validated by a stdlib `re` pattern. The feature never
  *orders* versions — it records them, compares fingerprints, and names versions in arms/provenance — so no
  comparison logic and no `semver`/`packaging` dependency are required.
- **Rationale**: Principle X; equality/identity is all the FRs need. Mirrors the existing opaque `AttackLibrary.version`
  and `SCHEMA_VERSION` strings.
- **Alternatives**: `semver`/`packaging` dep (rejected — no ordering needed).

## D3 — Registry = code module + committed fingerprint lock (no prompt text in the DB)
- **Decision**: a new module `src/kestrel/prompt_registry.py` enumerates each model-facing prompt as a
  `PromptEntry(id, version, text, fingerprint)`, importing the existing prompt constants. A committed lock file
  `src/kestrel/prompt_versions.lock.json` maps `{id: {version: fingerprint}}`. The DB stores only *provenance*
  (which id+version a run/verdict used), never prompt text.
- **Rationale**: the authored template text already lives in code (the clarification keeps attacker templates in
  `attacker.py` with full text); duplicating it into SQLite would be redundant and would bloat the migration. Keeps
  the v7 migration purely additive. The lock holds only fingerprints — no text, no secrets.
- **Alternatives**: a `prompts` DB table carrying text (rejected — duplication, non-additive migration, and it would
  put the single source of truth in data rather than reviewed code).

## D4 — The "no silent change" guard
- **Decision**: a unit test recomputes each registry entry's fingerprint from its live authored text and asserts it
  equals the lock's fingerprint for that entry's **active** version; a mismatch fails and names the offending prompt
  (FR-006/US2). Bumping a prompt = edit the text, raise its version, and append the new `(version → fingerprint)` to
  the lock. A `(id, version)` pair already present in the lock is immutable by append-only convention (FR-005);
  mutating one is a visible, reviewable diff the code owner rejects.
- **Rationale**: a committed baseline fingerprint that does **not** auto-follow the live text is what makes a silent
  edit detectable. The guard forces a conscious version decision; review enforces append-only immutability.
- **Alternatives**: commit full historical prompt texts and diff them (rejected — commits redundant text and enlarges
  the surface; fingerprints detect drift and reveal nothing).

## D5 — The memory summariser has no prompt (DEVIATION from FR-001)
- **Decision**: the registry versions the **three** model-facing prompt kinds — `attacker:<family>` (one per family),
  `judge`, and `recommender`. There is **no** memory-summariser prompt: `src/kestrel/experience/summary.py`
  (`build_summary`) composes the writeback summary deterministically with no model call.
- **Rationale**: FR-001 (and the original feature request) lists a "memory summariser" prompt that does not exist in
  the code; versioning it is impossible and would be vacuous. No behaviour is lost.
- **Impact**: FR-001/SC-004/US3 enumerations that say "memory summariser" over-count by one. The implementation
  covers attacker/judge/recommender. **Flagged for the user**; recommend a one-line spec footnote in the
  implementation PR (the spec is already merged, so this plan records the deviation rather than editing it silently).
- **Alternatives**: introduce a model-backed summariser to have something to version (rejected — out of scope and a
  behaviour change, violating FR-013/SC-003).

## D6 — Attacker entry is per family; `{goal}` is authored, not runtime data
- **Decision**: id `attacker:<family>`; authored template text = `SYSTEM_PROMPT.format(goal=GOALS[family])` — fully
  static, because `GOALS[family]` is authored text, not runtime data. The fingerprint is over that static text.
- **Rationale**: FR-001 says "attacker prompt **per family**"; a per-family entry keeps provenance aligned to the
  family a run used. Editing either the shared `SYSTEM_PROMPT` or a family's `GOALS` entry changes that family's
  fingerprint and requires a bump (caught by D4).
- **Alternatives**: version `SYSTEM_PROMPT` once plus each `GOALS` entry separately (rejected — splits one logical
  prompt into two ids and complicates provenance).

## D7 — `DATA_RULE`/`fence` scaffolding is shared, not per-prompt-versioned
- **Decision**: the shared `DATA_RULE` string and `fence()` wrapper (`prompting.py`, feature 008) are cross-cutting
  security scaffolding appended to every system prompt and applied to untrusted inputs. They are **excluded** from
  each entry's authored template text and fingerprint, and are versioned with the code, not per prompt.
- **Rationale**: `DATA_RULE` is identical across the three prompts; folding it into each fingerprint would force a
  simultaneous bump of all prompts whenever it changes, destroying the per-prompt signal.
- **Alternatives**: include `DATA_RULE` in each fingerprint (rejected — mass-bump coupling).

## D8 — Schema v7 is an additive migration in the existing `_migrate` pattern
- **Decision**: bump `SCHEMA_VERSION` `"6" → "7"`; extend the accepted-prior-versions tuple to include `"6"`; add
  nullable columns via the existing ALTER-tuple mechanism (like `ADAPTIVE_RUN_COLUMNS`). New columns:
  `run_turns`: `attacker_prompt_id`, `attacker_prompt_version`, `judge_prompt_id`, `judge_prompt_version`;
  `runs`: `judge_prompt_id`, `judge_prompt_version` (the overall / single-turn verdict's judge prompt);
  `experiment_arms`: `prompt_arm_target`, `prompt_arm_version`. Pre-migration rows keep `NULL`, surfaced as the
  "not recorded" marker (FR-004).
- **Rationale**: matches the proven additive routine (features 003/004 added columns the same way); no table rewrite.
- **Alternatives**: a separate `prompt_provenance` table (rejected — additive columns fit the existing pattern and
  keep reads simple).

## D9 — Expose active versions on `GET /api/config` (no new CLI; no new endpoint)
- **Decision**: add `prompts: list[PromptVersionOut{id, version}]` to `ConfigOut`, sourced from the registry's active
  entries. The UI (which already consumes `/api/config`) renders them; the "command-line view" is `curl /api/config`
  (carrying `X-Kestrel-Token` in hosted mode).
- **Rationale**: the clarification chose API-not-CLI; `/api/config` already carries `judge{model,configured}` and
  `attacker{model,configured}`, so prompt versions belong beside them — fewer endpoints (Principle IX).
- **Alternatives**: a dedicated `/api/prompts` endpoint (rejected — `/config` already answers "what is active?").

## D10 — Prompt-version experiment arm (attacker/judge only)
- **Decision**: add `prompt_arm_target` (a registry id — an `attacker:<family>` or `judge`) and `prompt_arm_version`
  to `ExperimentArm`, the `experiment_arms` table, and `ARM_DIFF_FIELDS` (so `experiment_diff` names them).
  `validate_experiment` accepts two arms differing only by these fields. The engine passes the chosen version to the
  attacker/judge client for that arm. Refused **before any model call** (FR-009): a target that is not an
  `attacker:<family>` or `judge` id (i.e. a recommender target), or a `(target, version)` absent from the registry.
- **Rationale**: clarification limits the arm subject to the prompts whose version moves the 007 confirmed/suspected
  metrics; recommender/summariser arms are unmeasurable there.
- **Alternatives**: allow any registry prompt as an arm subject (rejected per clarification).

## D11 — Judge eval reports per judge prompt version
- **Decision**: `tests/eval/test_judge_accuracy.py` resolves the **active** judge prompt version from the registry,
  prints its metrics under a `judge_prompt_version=<v>` group header, and keeps the existing recall floor
  (`DEFAULT_MIN_RECALL = 0.8`). Output is structured so that if more than one judge version is exercised, results
  group per version (US5 acceptance #1); with one active version it still names that version (acceptance #2).
- **Rationale**: satisfies US5/FR-010 with the smallest change; the harness already judges each row with the active
  judge prompt.
- **Alternatives**: iterate the eval across every registered judge version in one run (deferred — not required by the
  spec; adds model cost).
