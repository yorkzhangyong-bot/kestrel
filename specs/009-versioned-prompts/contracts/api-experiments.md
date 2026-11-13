# Contract: experiment prompt-version arm

Extends experiment creation/validation (`schemas.py` `validate_experiment`, `ARM_DIFF_FIELDS`, `experiment_diff`;
`store.create_experiment`; `experiments/engine.run_experiment`). No new endpoint — two optional arm fields.

## Request (per arm, additive)

```jsonc
"arm_a": { /* existing fields */ "prompt_arm_target": "judge", "prompt_arm_version": "1.0.0" },
"arm_b": { /* existing fields */ "prompt_arm_target": "judge", "prompt_arm_version": "1.1.0" }
```

- `prompt_arm_target` (optional str): a registry id restricted to `attacker:<family>` or `judge`.
- `prompt_arm_version` (optional str): the version pinned for that prompt in this arm.
- Both omitted (the default) → the arm uses each prompt's active version; behaviour identical to today.

## Validation — all **before any model call** (FR-008/FR-009)

| Condition | Result |
|-----------|--------|
| Two arms differ **only** by `prompt_arm_target`/`prompt_arm_version` | Valid distinct arms (not "arms identical") |
| `prompt_arm_target` is set but is not an `attacker:<family>` or `judge` id (e.g. `recommender`) | Reject (422) — only attacker/judge move the 007 metrics |
| `(prompt_arm_target, prompt_arm_version)` absent from the registry | Reject (422) before the experiment starts |
| One arm sets a prompt target/version, the other leaves it active | Allowed; the diff names both versions |

## Result

- `experiment_diff(arm_a, arm_b)` includes an entry like `prompt: A=judge@1.0.0, B=judge@1.1.0`
  (via `ARM_DIFF_FIELDS`), surfaced in `ExperimentResultOut.diff`.
- The comparison statistics are unchanged: confirmed vs suspected success kept separate, Wilson interval,
  two-proportion note (reuses `experiments/results.py`).

## Engine behaviour
- For an arm with a `prompt_arm_target`, `run_experiment` pins that prompt to `prompt_arm_version` for every run in
  the arm (the attacker or judge client resolves that version's text from the registry); all other prompts stay at
  their active version.
- Recorded on each arm row (`experiment_arms.prompt_arm_target/prompt_arm_version`) and, transitively, in each run's
  provenance (run_turns/runs columns).
