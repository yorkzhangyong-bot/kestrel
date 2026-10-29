# Contract: `scripts/check_spec.py` (spec-mode requirement check)

Runs on **spec-only** pull requests. Validates a feature's requirement identifiers across its directory.

## CLI

```text
python scripts/check_spec.py [FEATURE_DIR]
```

- `FEATURE_DIR` optional. When omitted, the feature is inferred from the branch prefix exactly as
  `check_traceability.py` does (e.g. branch `006-human-approved-spec` → `specs/006-*`), using `GITHUB_HEAD_REF`
  then the current git branch.
- If the branch has no numeric feature prefix and no `FEATURE_DIR` is given: print a notice and exit `0`
  (nothing to validate).
- If the resolved feature directory does not exist: print an error and exit `1`.

## Behaviour

1. Read every `*.md` under `FEATURE_DIR` (recursively: `spec.md`, `plan.md`, `tasks.md`, `contracts/*.md`,
   `research.md`, `data-model.md`, `quickstart.md`).
2. Collect **definitions** — lines matching `^- \*\*(FR|SC)-\d+\*\*` — and **references** — every `(FR|SC)-\d+`
   token anywhere in the text.
3. Report and fail (exit `1`) on any of:
   - **Malformed**: a token whose number is not exactly three digits (`^(FR|SC)-\d{3}$` fails).
   - **Duplicate definition**: an identifier defined on more than one line.
   - **Orphan reference**: a referenced identifier with no definition in the directory.
4. On success, print a one-line summary (counts of FR/SC defined) and exit `0`. Numbering gaps are **not** errors.

## Output (examples, shape not wording)

```text
Feature 006: 14 FR, 7 SC defined; all well-formed, unique, no orphan references.   # exit 0
Spec check failed:
  - duplicate definition: FR-003 (spec.md:112, spec.md:140)
  - orphan reference: SC-099 (tasks.md:57) is referenced but never defined
  - malformed identifier: FR-7 (spec.md:90)                                         # exit 1
```

## Purity / tests

The ID scanning and rule evaluation are pure functions over text (no network, no PR context), unit-tested by
`tests/unit/test_check_spec.py` with: well-formed+unique+no-orphan (passes), a duplicate definition (fails), an
orphan reference (fails), a malformed ID (fails), and a clean minimal spec (passes). (FR-003, FR-014, SC-002, SC-006)
