# Contract: PR classification and implementation-PR rules

Spec-only classification and the implementation-PR rules. The pure helpers take plain arguments so they are
unit-tested without GitHub; the script wraps them with the real diff and a live read of the pull request.

**Amended 2026-11-24** (revised after review rounds 1 and 2): the Spec-PR rule's scope is corrected to what the
gate has enforced since 2026-11-10 (`src/` or `ui/` changes, on any branch — commit df9a65f), and the rule gains
the honest path for refactor and bug-fix PRs (FR-009 amended; FR-015–FR-020, FR-022 added). The gate reads the
**raw** description, exactly as today: text inside an HTML comment or any other markup counts like any other line
(the round-1 comment stripping was reversed in round 2, research §16).

## Classification (used by `qa.yml` / helper)

```text
is_spec_only(changed_files: list[str]) -> bool
```

- Returns `True` when no path starts with `src/`, `tests/`, `ui/`, or `scripts/`.
- The workflow's `classify` job computes `changed_files` from `git diff --name-only origin/<base>...HEAD` and
  exposes the result as the job output `spec_only` (`"true"`/`"false"`). The job always exits `0` so the gate
  jobs that depend on it never skip (FR-006).

## The raw description (FR-017)

- Every body-reading helper below works on the raw description text: no comment, code-block or markup filter of
  any kind, for `Spec-PR:`, `Spec-PR-reason:` and `spec-change:` alike. A declaration the rendered view hides is
  the reviewer's to catch, as it has always been for the numbered form.
- A keyed line starts in **column 1**: no pattern below allows indentation, a list marker, a quote or emphasis
  before the key, so an indented or bulleted `Spec-PR: none` is ordinary text.

## `check_traceability.py` additions (implementation PRs only)

The traceability job runs this script when `spec_only == false`. In addition to the existing
tests-traceability check, it evaluates two rules and fails (exit `1`) if either is violated.

### Spec-change rule (FR-010, FR-011) — unchanged

```text
needs_spec_change_note(changed_files) -> bool              # True => must have the note
spec_change_ok(changed_files, pr_body) -> bool
```

- A note is required when `changed_files` contains **both** a `specs/**` file and a `src/**` file.
- The note is a line in `pr_body` matching `^spec-change:\s*\S` (case-insensitive).
- Fails when the note is required but absent. Rationale surfaced in the message: an approved spec may not be
  edited inside a code PR without an explicit, reviewable acknowledgment.
- Applies to a `Spec-PR: none` PR exactly as to any other (FR-022).

### Spec-PR declaration rule (FR-009, FR-015, FR-016, FR-017, FR-018, FR-020, FR-022)

Evaluated only when the PR changes `src/` or `ui/` (`changes_app_code(changed_files)`), on **any** branch. A PR
that changes only `tests/`, `scripts/`, `docs/` or `specs/` is not evaluated: a `Spec-PR:` line on it is ignored.

#### Grammar

```text
SPEC_PR_RE        (?im)^Spec-PR:\s*#\d+                                # numbered form — unchanged
SPEC_PR_LINE_RE   (?im)^Spec-PR:[ \t]*(.*?)[ \t\r]*$                   # every keyed Spec-PR: line, value captured
REASON_LINE_RE    (?im)^Spec-PR-reason:[ \t]*(.*?)[ \t\r]*$            # every reason line, value captured
REASON_VALUE_RE   (?i)^(?:(refactor)|(bugfix):[ \t]*#[0-9]+)$          # a well-formed reason value
REASON_LABELS     {"refactor": "refactor", "bugfix": "bugfix"}         # keyword -> required label
```

- Every keyed line is line-anchored, column 1, and case-insensitive, as `Spec-PR:` and `spec-change:` already
  are (FR-017). "`none`-valued" below means: a `SPEC_PR_LINE_RE` value that, lower-cased, **starts with** `none`.
- `[ \t\r]*$`: a body from the platform's web form arrives with CRLF line endings; a trailing carriage return
  (and trailing blanks) never makes a well-formed line malformed. `\s*$` is **not** used because `\s` crosses line
  breaks and would accept a value split over two lines.
- The reason value: `refactor`, or `bugfix:` + optional spaces or tabs + `#` + one or more ASCII digits
  (`[0-9]`, not `\d`, which accepts non-ASCII digits). So `bugfix:#12` and `bugfix:<tab>#12` are well-formed;
  `bugfix: 12`, `bugfix: #`, `bugfix: #١٢` and `refactor of the graph` are not.
- The numbered form keeps its prefix match and its tolerances: text after the number, a second numbered line, an
  unrelated value such as `TBD` beside it, and even the number on the next line (its unchanged `\s*`) — SC-009.
- On the honest path the description carries **exactly one** keyed `Spec-PR:` line in total, and its value is
  exactly `none` (case-insensitive): `none because …`, a second `none`, or a `TBD` beside it all fail.
- Label names are compared lower-cased (`{name.lower() for name in labels}`).

#### Helpers

```text
has_spec_pr_reference(pr_body) -> bool                                       # unchanged: a numbered line exists
spec_pr_rule_problems(pr_body: str | None, labels: list[str]) -> list[str]   # [] == rule satisfied
parse_pr_state(raw: str | None) -> tuple[str, list[str]]                     # (body, label names) from gh's JSON
pr_state() -> tuple[str, list[str]]                                          # the live read (subprocess); any failure -> ("", [])
pr_rule_problems(files: list[str], pr_body: str | None, labels: list[str]) -> list[str]   # the pure wiring
```

`spec_pr_rule_problems` decides in this order (the first matching row wins; it returns at most one problem; every
failure message ends with the accepted-forms sentence of FR-020):

| # | Condition | Result |
|---|---|---|
| 1 | a numbered line; no `none`-valued line; no reason line | pass — unchanged behaviour; labels and other `Spec-PR:` values ignored (SC-009) |
| 2 | a numbered line and (a `none`-valued line or a reason line) | fail: conflicting declaration (FR-016); + the hint |
| 3 | no numbered line and no `none`-valued line | fail: missing `Spec-PR:` declaration (FR-009); every `Spec-PR:` value found is listed as malformed |
| 4 | more than one keyed `Spec-PR:` line, or the one value is not exactly `none` | fail: the honest path needs exactly one `Spec-PR:` line with the value `none`; the values found are listed (FR-016); + the hint |
| 5 | no reason line | fail: `Spec-PR: none` needs a reason line (FR-016) |
| 6 | two or more reason lines | fail: more than one reason line (FR-016); + the hint |
| 7 | the reason value does not match `REASON_VALUE_RE` | fail: malformed reason `<value>` (FR-016) |
| 8 | the matching label is absent | fail: reason `<keyword>` needs the `<label>` label (FR-015, FR-016) |
| 9 | the other reason's label is present | fail: the `<other>` label contradicts the reason (FR-016) |
| 10 | otherwise | pass (FR-015) |

The hint (FR-020), added to the row 2, 4 and 6 messages before the accepted-forms sentence, because a quoted example is
the likely cause of a second keyed line:

```text
every column-1 keyed line counts, also inside code blocks and HTML comments; indent quoted examples
```

Accepted-forms sentence (FR-020), appended to every failure of this rule:

```text
Accepted forms: 'Spec-PR: #<n>'; or 'Spec-PR: none' + 'Spec-PR-reason: refactor' + label 'refactor'; or 'Spec-PR: none' + 'Spec-PR-reason: bugfix: #<issue>' + label 'bugfix'.
```

- The issue number is never looked up (FR-015): `bugfix: #999999` is well-formed.
- **Echoed values** (rows 3, 4, 7): a value from the description is printed as a Python literal — `repr(value)`,
  truncated to 80 characters — never raw, so a lone carriage return or a `::warning::` / `::add-mask::` prefix
  inside a value cannot start a runner log line or a workflow command.

#### The live read (FR-018)

```text
gh pr view "$PR_NUMBER" --repo "$GITHUB_REPOSITORY" --json body,labels      # run by pr_state(), timeout 30 s
```

- `parse_pr_state(raw)`: `body` is the JSON `body` when it is a string, else `""`; `labels` is the `name` of every
  element of the JSON `labels` when it is a list whose every element is an object with a string `name`, else
  `[]`; `None`, an empty string, invalid JSON or a non-object → `("", [])`.
- `pr_state()`: reads `PR_NUMBER` from the environment and calls `subprocess.run` (both monkeypatched in the unit
  tests). A missing `PR_NUMBER` → `("", [])` without any subprocess call; a non-zero `gh` exit, a
  `TimeoutExpired`, a `FileNotFoundError` (no `gh` on the path) or any other exception → `("", [])`; a successful
  call → `parse_pr_state(stdout)`. Every failure prints a one-line notice that carries no body or label value.
  Fail-closed: with no body the honest path and the numbered form both fail.
- The token is the job's own `github.token`, on a traceability job limited to `permissions: {contents: read,
  pull-requests: read}` (FR-018; item 9 of review round 2).
- Why live and not the event payload: a manual re-run reuses the original event's snapshot, and `gh pr create
  --label` fires `opened` (no labels yet) and `labeled` on one commit; reading at evaluation time makes every
  run judge the same, current state (research §10).

#### Wiring

```text
pr_rule_problems(files, pr_body, labels):
    if not files or is_spec_only(files): return []            # not an implementation PR (or no PR context)
    problems = spec_pr_rule_problems(pr_body, labels) if changes_app_code(files) else []
    if not spec_change_ok(files, pr_body): problems.append(<spec-change message>)
    return problems

_pr_rule_problems() == pr_rule_problems(changed_files(), *pr_state())
```

### Inputs from the environment

- `changed_files`: from `git diff --name-only origin/$GITHUB_BASE_REF...HEAD`.
- `PR_NUMBER` (`github.event.pull_request.number`) and `GITHUB_REPOSITORY` (set by the runner) for the live read;
  `GH_TOKEN` = `github.token`, with the traceability job's `permissions` set to `contents: read` and
  `pull-requests: read` (enough for `gh pr view`; the workflow-level `pull-requests: write` stays because `classify`,
  `quality` — the gitleaks action comments on PRs — and `notify` inherit it, while the review job declares its own
  permissions block).
- `PR_BODY` is **no longer read**: the event snapshot is exactly what the live read replaces.

### Workflow wiring (`qa.yml`)

- `on.pull_request.types: [opened, synchronize, reopened, edited, labeled, unlabeled]` — listing types replaces
  GitHub's default three, so all six are named (FR-019). Every job runs in full on every event; no job and no
  step is conditional on the event — a skipped required job reports success and would replace an earlier failure
  on the same commit (FR-006), and a verdict-only review job would mark an unreviewed commit green (research §11,
  round 2).
- The traceability job declares `permissions: {contents: read, pull-requests: read}`; its step's `env` carries
  `PR_NUMBER: ${{ github.event.pull_request.number }}` and `GH_TOKEN: ${{ github.token }}` in place of `PR_BODY`.

### Exit codes

- `0`: tests-traceability passes and both rules satisfied (or not applicable).
- `1`: any unreferenced requirement, a missing required spec-change note, or a failed Spec-PR declaration; each
  failure is printed with the offending detail (escaped) and, for the Spec-PR rule, the accepted forms.

## Labels (platform, FR-021)

`refactor` and `bugfix` are repository labels created by the owner by hand (`gh label create …`, listed in
`docs/branch-protection.md`); they are not committed configuration. The gate compares names ignoring case.

## Tests

`tests/unit/test_check_traceability.py` unit-tests the pure helpers: classification (code path vs spec-only);
spec-change required-and-missing → fail, required-and-present → pass, not-required → pass; Spec-PR reference
present/absent. (SC-003, SC-007)

Added 2026-11-24 (T021; 006/FR-009, 006/FR-015, 006/FR-016, 006/FR-017, 006/FR-018, 006/FR-020, 006/FR-022,
006/SC-008, 006/SC-009) — the matrix over `spec_pr_rule_problems`, `parse_pr_state`, `pr_state` and
`pr_rule_problems` (the reference probe `probe_006_rule.py`, updated to this contract after each review round,
decides every row below exactly one way):

- **pass** (row 1): `#<n>` with neither new line — with no labels, with `refactor`, with both labels; beside a
  second numbered line; beside `Spec-PR: TBD`; the number on the next line (`Spec-PR:` then `#12`, the unchanged
  `\s*`); the numbered line inside a multi-line `<!--` … `-->` block whose keyed line starts in column 1 (the raw
  description counts); `#<n>` + a one-line reason comment `<!-- Spec-PR-reason: refactor -->` (not a keyed line, so
  no conflict).
- **pass** (row 10): `none` + `refactor` + label `refactor`, also with both lines inside a multi-line `<!--` … `-->`
  block whose keyed lines start in column 1 (raw read); `none` + `bugfix: #12` + label `bugfix`; `none` + `bugfix: #999999`; `bugfix:#12`; `bugfix:<tab>#12`;
  case variants (`spec-pr: NONE`, `SPEC-PR-REASON: Refactor`, label `Refactor`); CRLF line endings; extra blanks
  around the value.
- **fail** (each message names the accepted forms and the failed condition; the row 2, 4 and 6 messages also carry
  the hint; echoed values are `repr` literals):
  row 2 — `#<n>` + `none`; `#<n>` + `none because …`; `#<n>` + a reason line, also when that reason line sits
  inside a multi-line `<!--` … `-->` block with the reason line in column 1 (raw read: a conflict); row 3 — no
  `Spec-PR:` line; `Spec-PR: TBD` alone; `Spec-PR:` with an empty value; a reason line with no `Spec-PR:` line; an
  indented or bulleted `Spec-PR: none`; a one-line comment `<!-- Spec-PR: #12 -->` (not a keyed line: the key is
  not in column 1); a one-line honest-path pair `<!-- Spec-PR: none -->` + `<!-- Spec-PR-reason: refactor -->`
  (likewise); row 4 —
  `none because …` alone; `none` + `none because …`; `none` + `TBD`; two `none` lines; a `none` value carrying a
  lone carriage return and `::warning::` (the message shows the escaped literal, no raw CR); row 5 — `none`
  alone; row 6 — two reason lines (same and different); row 7 — `refactoring`, `bugfix`, `bugfix: 12`,
  `bugfix: #`, `refactor of the graph`, `bugfix: #١٢`; row 8 — `none` + a reason + no labels; `none` +
  `bugfix: #12` + label `refactor` only; row 9 — `none` + `refactor` + both labels; `none` + `refactor` + label
  `bugfix` only is row 8 (the matching label is checked first).
- **parse**: `parse_pr_state` on `{"body": "…", "labels": [{"name": "refactor"}]}` → the body and
  `["refactor"]`; `body` missing or non-string → `""`; `labels` with an element lacking a string `name`
  (`[{"name": 1}]`, `["refactor"]`), or not a list → `[]`; `None`, `""`, invalid JSON, a non-object → `("", [])`.
- **live read, failure path** (`pr_state` with `os.environ` and `subprocess.run` monkeypatched, stdout
  captured): no `PR_NUMBER` → `("", [])` and `subprocess.run` never called; a non-zero exit → `("", [])`;
  `subprocess.TimeoutExpired` → `("", [])`; `FileNotFoundError` → `("", [])`; a successful call →
  `parse_pr_state` of its stdout; the notice on every failure carries no body or label value.
- **wiring**: `pr_rule_problems` — `["src/kestrel/x.py"]` + a valid honest path + `["refactor"]` → `[]`; the
  same with `[]` labels → exactly the row-8 message; `["tests/unit/t.py"]` with a lone `Spec-PR: none` → `[]`;
  `["src/kestrel/x.py", "specs/006-x/spec.md"]` + a valid honest path with no `spec-change:` → exactly the
  spec-change problem; the same with a column-1 `spec-change:` line, outside a comment or inside a multi-line
  `<!--` … `-->` block (raw read) → `[]`; the same with only a one-line `<!-- spec-change: x -->` → the spec-change
  problem (not a keyed line).
- The spec-change rule is still required on the honest path (`spec_change_ok` with a `specs/**` + `src/**` change
  and `Spec-PR: none` in the body).
- Existing assertions (`has_spec_pr_reference`, `changes_app_code`, `is_spec_only`, spec-change) stay untouched
  (SC-009).
