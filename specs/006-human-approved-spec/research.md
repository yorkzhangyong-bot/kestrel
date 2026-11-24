# Research: Human-Approved Spec Workflow

Phase 0 decisions. The clarify session (spec §Clarifications, 2026-10-29) already settled: CI enforces the
spec-PR reference; the spec-mode check reads the whole feature directory; IDs are `FR-###`/`SC-###` (zero-padded,
gaps allowed). The items below resolve the remaining design unknowns.

## 1. Detecting a spec-only pull request

- **Decision**: Compute the PR's changed files with `git diff --name-only origin/<base>...HEAD` and classify the
  PR as **spec-only** when none of those paths start with `src/`, `tests/`, `ui/`, or `scripts/`. Do this in one
  fast `classify` job that exposes `spec_only` as a job output.
- **Rationale**: Matches FR-002 exactly (classification depends only on the absence of code-directory changes, so
  a spec PR may also touch `.github/` or `docs/`). A single classify job keeps the rule in one place; the three
  gate jobs read `needs.classify.outputs.spec_only`.
- **Alternatives considered**: Computing the diff independently inside each gate job (more robust against a
  cross-job skip, but duplicates the rule three times); using the GitHub "paths" filter on the workflow trigger
  (can't express "no code dirs" as a single gate and would skip whole jobs, tripping the required-check gotcha
  below).

## 2. Required checks must always report (the skip gotcha)

- **Decision**: `traceability`, `quality`, and `review` run on **every** PR and always report a result; on a
  spec-only PR the quality job reports success without running its heavy steps (each heavy step is guarded by
  `if: needs.classify.outputs.spec_only != 'true'`). The `classify` job is written to always exit 0.
- **Rationale**: GitHub branch protection waits on a *required* status check by job name. A job that is skipped
  (never runs) never reports, so protection would block forever. Running the job and short-circuiting to success
  keeps the required check green (FR-006). Making `classify` always succeed guarantees the three jobs that
  `need` it are never skipped.
- **Alternatives considered**: Marking the quality job itself conditional (`if:` at job level) — this makes it
  "skipped", which does **not** satisfy a required check; rejected.

## 3. CODEOWNERS and branch protection

- **Decision**: Add `.github/CODEOWNERS` with `/specs/ @<owner>` (and a catch-all `* @<owner>` so every PR needs
  the owner). Document in `docs/branch-protection.md` the exact settings to apply by hand on `master`: require a
  pull request before merging; require at least 1 approving review; require review from Code Owners; require
  status checks to pass with "Require branches to be up to date"; list `traceability`, `quality`, `review` as the
  required checks; do not allow bypass.
- **Rationale**: FR-007/FR-008. GitHub does not let a repository set its own branch protection from committed
  files — it is an admin setting applied through the UI or the REST API by the owner — so the repo can only ship
  the `CODEOWNERS` file plus a precise manual guide (FR-013).
- **Alternatives considered**: A rulesets-as-code tool/action to apply protection — rejected as a new dependency
  and out of scope (Principle X; the feature explicitly keeps protection manual).
- **Note**: The required-check **names** must match the job names in `qa.yml` exactly, or protection waits on a
  check that never appears. The guide calls this out.

## 4. Reading the PR body and head/base refs in CI

- **Decision**: The spec-change rule (FR-010/011) and the spec-PR-reference rule (FR-009) read the PR body from
  the event payload (`github.event.pull_request.body`, passed to the checker as an environment variable) and the
  changed paths from `git diff` against `origin/<base>`. The checker treats a missing body as empty.
- **Rationale**: The `pull_request` event carries the body; passing it as an env var keeps `check_traceability.py`
  unit-testable (the pure helpers take `changed_files` and `pr_body` as arguments). `GITHUB_HEAD_REF`/
  `GITHUB_BASE_REF` already drive the existing traceability checker.
- **Alternatives considered**: Querying the body via `gh pr view` inside the script — rejected; it couples the
  pure logic to the network and is harder to test than an injected string.
- **Superseded 2026-11-24 by §10** for the *read*: the body and the labels are now fetched live with `gh pr view`
  at evaluation time. The rejection above stands only for the *rule*, which still takes `changed_files` and
  `pr_body` as plain arguments.

## 5. Spec-mode check: scope, format, and what counts as an orphan

- **Decision**: `check_spec.py` reads every `*.md` under the feature directory (`spec.md`, `plan.md`, `tasks.md`,
  `contracts/*`), collects **definitions** (a line matching `- **FR-### / SC-###**`) and **references** (any
  `FR-###`/`SC-###` token). It fails if: an identifier is not well-formed (`FR`/`SC` + exactly three digits), a
  definition ID appears twice (duplicate), or a referenced ID has no definition (orphan). Numbering gaps are
  allowed. It prints each offending ID and exits non-zero.
- **Rationale**: Directly from the clarifications. Reading the whole feature directory catches a dangling
  reference in `plan.md`/`tasks.md`, not just in `spec.md`. The "definition = `- **FR-###**`" convention matches
  how the existing specs and `check_traceability.py` already treat definitions, so there is one shared notion of
  a requirement ID.
- **Alternatives considered**: Validating only `spec.md` (misses plan/tasks orphans); treating "orphan" as a
  defined-but-unreferenced requirement (rejected in clarify — orphan means a dangling reference).

## 6. Two checkers rather than one

- **Decision**: Keep `check_spec.py` pure and spec-only; put the implementation-PR rules (tests-traceability +
  spec-change + spec-PR-reference) in the existing `check_traceability.py`. The `traceability` job runs
  `check_spec.py` when `spec_only`, else `check_traceability.py`.
- **Rationale**: `check_spec.py` stays a pure file-reader (easy to unit-test, reusable locally). The PR rules
  belong with the traceability checker that already runs on code PRs and already reads the branch/diff. Each
  checker exposes small pure functions so the rules are unit-tested without GitHub.
- **Alternatives considered**: One mega-script with a `--mode` flag (muddier responsibilities, harder tests);
  three separate scripts (more surface, no benefit).

## 7. Switching the review checklist for spec PRs

- **Decision**: The `review` job has two Claude Code Action steps, one gated on `spec_only == true` pointing its
  prompt at `.github/review/spec-checklist.md` and the feature spec, the other (the existing step) pointing at
  `checklist.md`. Both are followed by the shared verdict-enforcement step that fails on `VERDICT: FAIL`.
- **Rationale**: The prompt text is static per step, so a conditional pair is simpler and more predictable than
  asking the model to detect the PR type and pick a checklist. The spec checklist targets spec-level defects
  (ambiguity, missing/weak success criteria, untestable requirements, constitution conflicts) per FR-004.
- **Alternatives considered**: One step with a templated checklist path — Actions expression interpolation into
  `claude_args`/`prompt` is possible but makes the step harder to read than two explicit steps.

## 8. Bootstrap / rollout order

- **Decision**: This feature's own rollout follows the cycle it defines: this spec PR (specs/ + docs/ only) is
  approved and merged first; a later implementation PR adds `check_spec.py`, the `qa.yml` changes,
  `CODEOWNERS`, `spec-checklist.md`, the docs, and the tests; the owner then applies `branch-protection.md`
  manually. The workflow governs features 006 onward and is not applied retroactively to 001–005.
- **Rationale**: Dogfoods the feature and matches the spec's Bootstrap edge case. Branch protection is applied
  after the workflow jobs exist so the required-check names resolve.
- **Alternatives considered**: Applying branch protection before the jobs exist — rejected; protection would wait
  on check names that do not yet report.

## 2026-11-24 — an honest Spec-PR path for refactor and bug-fix PRs

Amendment research. The owner's requirement (roadmap Housekeeping item): accept `Spec-PR: none` only with a reason
line (`refactor` or `bugfix: #<issue>`) and a matching label; fail-closed otherwise. What the gate enforces today:
`Spec-PR: #<n>` on any PR that changes `src/` or `ui/`, on any branch, syntax only (commit df9a65f, 2026-11-10).

## 9. The reason line's grammar

- **Decision**: a second keyed line, `Spec-PR-reason: refactor` or `Spec-PR-reason: bugfix: #<issue>`, exactly
  one, valid only beside `Spec-PR: none`; whole-line value; key, `none` and keywords case-insensitive, like the
  existing `Spec-PR:` / `spec-change:` lines; trailing blanks and a trailing carriage return tolerated (the
  platform's web form sends CRLF). The numbered form keeps its prefix match and its tolerance of duplicates.
- **Rationale**: the owner asked for "a reason line"; a key tied to `Spec-PR` cannot be mistaken for prose, and a
  whole-line value keeps the vocabulary closed (two reasons, nothing else) so the gate stays fail-closed.
- **Alternatives considered**: a bare `Reason:` line (collides with ordinary prose at a line start, so a
  description could grow an accidental, malformed reason); an inline form `Spec-PR: none (refactor)` (one line,
  but it gives the `Spec-PR:` key two grammars and does not read as "a reason line"); anchoring the value with
  `\s*$` (rejected: `\s` crosses line breaks, so a value split over two lines would pass; `[ \t\r]*$` keeps the
  value on its line and handles CRLF explicitly).

## 10. How the gate receives the description and the labels (revised after review round 1)

- **Decision**: the traceability job reads both **live** at evaluation time: `check_traceability.py` runs
  `gh pr view "$PR_NUMBER" --repo "$GITHUB_REPOSITORY" --json body,labels` (the runner's `gh`, `GH_TOKEN` =
  `github.token`), and `parse_pr_state` turns the JSON into `(body, label names)`; a non-zero exit, a timeout,
  unparsable JSON, a missing `PR_NUMBER`, a non-string body or a labels array with any element lacking a string
  `name` → `("", [])` or `[]` labels respectively, so the honest path fails closed. The rule stays the pure
  `spec_pr_rule_problems(pr_body, labels)`, and the wiring is the pure `pr_rule_problems(files, pr_body, labels)`.
- **Rationale**: the event snapshot (`github.event.pull_request.*`, whether as `PR_BODY` or as a `toJSON(labels)`
  array) is wrong in two real cases the reviewer named: a manual *re-run* reuses the original event, so re-running
  a failed `opened` run after adding the label fails again, and re-running a stale passing run after the label was
  removed shows green; and `gh pr create --label` fires `opened` (no labels yet) and `labeled` on one commit, two
  overlapping runs whose winner depends on undocumented newest-run-per-check-name behaviour. Reading live makes
  every run — first, overlapping or re-run — judge the same current state. §4's rejection of `gh` in the script
  stands for the *rule*, which is still pure; only the *read* moves, and the token is the job's own.
- **Alternatives considered**: `PR_BODY`/`PR_LABELS` from the event payload (the first design; rejected for the
  two cases above); `join(labels.*.name, ',')` (a label name may contain a comma); `github.event.label` (only
  the one label of a `labeled` event); a `gh` call in the *workflow step* exporting env vars (equivalent, but the
  fail-closed handling would then live in shell instead of a unit-tested parser).

## 11. Re-running the gate on description and label changes

- **Decision**: `on.pull_request.types: [opened, synchronize, reopened, edited, labeled, unlabeled]`. The whole
  pipeline runs on each event; no job is made conditional on the event.
- **Rationale**: GitHub's default is `opened` / `synchronize` / `reopened` only, so a label added through the UI
  after opening — the normal way a human labels a PR — would never count without a push; FR-019 closes that trap.
  The whole pipeline must run because a job skipped by a job-level `if` reports *success* and does not block a
  merge (GitHub docs, "Using conditions to control job execution"), so a `labeled` run that skipped `quality` /
  `review` would replace an earlier failure on the same commit with a green check.
- **Alternatives considered**: keep the default triggers and document "push an empty commit or close and reopen"
  (rejected: a trap, and it makes the label a decoration); `labeled` / `unlabeled` only (rejected: a reason line
  added by editing the description would still need a push — an asymmetry nobody would guess); a `concurrency`
  group with `cancel-in-progress` to cap the cost of rapid successive edits (not added — no need shown yet; it
  would also cancel a push's run mid-way, which is a behaviour change of its own).
- **Re-run semantics** (after review round 1): with the live read of §10, a manual re-run of any earlier run judges
  the current description and labels, not the event that first triggered it.
- **Cost and noise** (after review round 1): each event re-runs quality (tests, coverage, scans) and the review;
  `gh pr create --label` yields two runs on one commit (`opened`, then `labeled`), and the `opened` run can read
  before the label lands — then it fails and `notify` emails once, and the `labeled` run is the newer, passing
  result. Once `SKIP_AI_REVIEW` is removed, every label or description event re-runs the paid AI review and a
  label toggle re-rolls its verdict; that cost is accepted and stated in the spec's Assumptions.
- **Decision 2026-11-24 (review round 2) — no verdict-only review on those events.** Round 1 had recorded an
  optional mitigation: on `edited` / `labeled` / `unlabeled` the `review` job would skip its two Claude steps and
  run only the verdict-enforcement step over the latest verdict comment. **Rejected**, because it can mark an
  unreviewed commit green: a push of commit X starts a run whose review takes minutes; a label added meanwhile
  starts a second run, whose verdict-only step reads the previous commit's `PASS` and passes; the first run then
  posts `FAIL` for X, but the newest-triggered run decides the required `review` check, so X shows a `PASS` it
  never earned. With `gh pr create --label` there is no earlier verdict at all, so the variant would fail every
  freshly labelled PR until something else re-triggered it. Binding verdicts to the head SHA would fix both, but
  it is a change to the review job that this feature does not need. Every job runs in full on every event, the
  quality job included (skipping it would report success without evidence).

## 12. The issue number

- **Decision**: `bugfix: #<issue>` is checked for form only (`#` followed by digits). No lookup.
- **Rationale**: the gate has never verified `#<n>` either; the helper stays pure; an issue's existence says
  nothing about whether it describes the fix — that is the reviewer's judgment; the label makes the claim visible
  in the pull-request list, and the owner's approval is the control.
- **Alternatives considered**: `gh api repos/…/issues/<n>` in the gate (rejected: a false sense of verification —
  an issue's existence says nothing about the fix).

## 13. The labels

- **Decision**: two repository labels named after the keywords, `refactor` and `bugfix`, created by the owner by
  hand (`gh label create`) and listed in `docs/branch-protection.md`; compared case-insensitively (GitHub label
  names are unique ignoring case). "Matching" = the label named after the reason keyword is present *and* the
  other is absent.
- **Rationale**: name = keyword needs no mapping table in docs or code; two reason labels on one PR contradict
  each other, so fail-closed.
- **Alternatives considered**: reusing the default `bug` label (an *issue* label — a PR carrying it could be
  reporting a bug, not fixing one); labels as committed configuration (GitHub has no such mechanism without a new
  action — Principle X; like branch protection, it is a manual, documented setting).

## 14. Failure messages

- **Decision**: one message per failed condition, each ending with the same accepted-forms sentence (the three
  forms with their labels). The existing "a PR that changes src/ or ui/ must carry a 'Spec-PR: #<n>' reference
  line" message becomes the missing-declaration message with that sentence.
- **Rationale**: FR-020 — a contributor who hits the gate must be able to fix the PR from the log alone.

## 15. Rollout

- **Decision** (revised after review round 1): this spec PR (specs/006 only) → the owner creates the two labels
  (T024) → the implementation PR (`scripts/`, `tests/unit/`, `qa.yml`, the PR template, docs, `CLAUDE.md`, and the
  roadmap item moved to Done in the same PR, T028) is pushed; it needs no `Spec-PR:` line by FR-009 (no `src/` /
  `ui/` change) and carries `Spec-PR: #<spec PR>` by convention → **live verification before the merge** (T031): a
  throwaway **draft** PR to `master` from a scratch branch based on the feature branch (no numeric prefix, e.g.
  `probe/honest-path`, so only the Spec-PR rule is under test), adding one trivial `src/` change (a comment), runs
  quickstart scenario 6 — a `pull_request` run uses the workflow file from the PR's own merge commit, so the draft
  runs the new `qa.yml` and script although `master` still has the old ones; the draft is closed unmerged and its
  branch deleted → the implementation PR merges by one of the two workflow-edit routes of docs/branch-protection.md
  (the review check passes while `SKIP_AI_REVIEW=true`; otherwise an administrator merges with it red).
- **Rationale**: the previously named vehicle — the queued bug-to-pr fix for the replay test stub — changes only
  `tests/integration/test_replay_run.py`, so `changes_app_code` is false and the Spec-PR rule is never evaluated
  on it; a check "verified" there would pass without testing anything. A draft PR that touches `src/` is the
  smallest real vehicle, and basing it on the feature branch lets it run the new gate before the merge.
- **Alternatives considered**: verifying after the merge on the next real refactor or `src/` bug fix (rejected:
  unknown date, and a defect would then block a real PR); a non-draft PR (works the same, but a draft signals
  "never merge"); a scratch branch with a numeric prefix (fine, but it would also run the 006 tests-traceability
  check and mix two things).
- **Decision 2026-11-24 (review round 2) — the scratch branch restores `specs/` first.** By the time T031 runs,
  the feature branch will carry `specs/006` edits (ticked tasks, as the 011–013 implementation commits did), so a
  draft based on it would diff `specs/` + `src/` against `master` and trip the spec-change rule at step 1. The
  scratch branch therefore runs `git checkout --no-overlay origin/master -- specs/` (the default overlay checkout
  keeps files the branch added under `specs/` — the reviewer showed it in a scratch repository with git 2.54),
  commits that restore together with the `src/` comment, and confirms that `git diff --name-only
  origin/master...HEAD -- specs/` prints nothing before the draft is opened, so its diff holds no spec file and step 6 (push a spec edit with no `spec-change:` line; it fails) stays a distinct
  observation. **Rejected alternative**: a `spec-change: <reason>` line in the draft's description from step 1,
  with step 6 removing it — it works, but it muddles what each step proves. Two preconditions from the same
  round: the draft must be mergeable (GitHub runs no `pull_request` workflow on a PR with a merge conflict), and
  every issue or PR number it writes is one that does not exist (`#999999`), so the throwaway leaves no
  cross-reference on a real issue or pull request. Rollout order, stated once: labels created (T024) → the
  draft-PR live check (T031) → the implementation PR merged, carrying the roadmap item to Done (T028).

## 16. HTML comments, column 1 and digits (round 1; the comment part superseded in round 2)

- **Decision 2026-11-24 (review round 2) — the gate reads the raw description, exactly as today.** Text inside an
  HTML comment, a code block or any other markup counts like any other line, for `Spec-PR:`, `Spec-PR-reason:`
  and `spec-change:` alike. The column-1 rule and the ASCII-digit rule stay.
- **Why the round-1 stripping was reversed**: the reviewer asked GitHub's renderer what a reader is shown and
  found five descriptions the old gate accepted that the round-1 stripper rejected — `<!--` inside an inline code
  span, inside a fenced or an indented code block, an unterminated `<!--` in the middle of a line (shown
  literally), and the empty comment `<!-->` all leave the text after them visible, while the regex hid it; and
  `<!-- c -->Spec-PR: #12` or `no<!-- -->ne` are shown as keyed text the stripper broke. A stripper faithful to the
  renderer is a markdown parser — too big for this small change — and other markup that hides text (`<?…?>`,
  CDATA, a `<!X…>` declaration, a multi-line link-reference title) would still count anyway. The visible label and
  the owner's approval are the control, as they are today for the numbered form.
- **Rejected alternatives (round 2)**: (a) a renderer-faithful `visible_body` (mask code spans and blocks, strip
  terminated comments anywhere, let an unterminated `<!--` hide the rest only at a line start, treat `<!-->` as
  complete) — a parser by another name, with new edge cases of its own; (b) keeping the simple regex and listing
  its mismatches as a further SC-009 exception — a rule nobody could state from memory.
- **Consequence for the PR template**: its examples stay indented inside the comment, so no example is ever a
  column-1 keyed line (FR-023, T032). The gate itself would catch a column-1 `Spec-PR: none` or `Spec-PR-reason:`
  example on the first web-form PR that changes `src/` or `ui/` (rows 2, 4 and 6), but not a column-1
  `spec-change:` example (it silently satisfies FR-010) nor a column-1 `Spec-PR: #<n>` example on a numbered PR
  (row 1 tolerates it) — those two stay indented only through the owner's review of template edits.
- *Round-1 decision, superseded*: before any keyed line was matched, the gate removed HTML comments — `<!-- … -->`
  non-greedily and an unterminated `<!--` to the end of the body, each replaced by one space (`visible_body`),
  applied inside every body-reading helper — on the round-1 reasoning that the PR template put its examples
  inside an HTML comment, so an unindented example there would have made every web-form PR fail as a conflict,
  and a declaration hidden in a comment passed while the rendered view showed nothing. The surviving parts of
  that decision: a keyed line starts in column 1 (the patterns allow no indentation, list marker, quote or
  emphasis before the key), and the issue number is `[0-9]+` (ASCII), not `\d+`, because Python's `\d` accepts
  non-ASCII digits, which no issue number has.

## 17. Stray and malformed `Spec-PR:` lines (after review round 1)

- **Decision**: one pattern, `SPEC_PR_LINE_RE`, captures the value of **every** keyed `Spec-PR:` line. On the
  honest path the description must carry exactly one such line and its value must be exactly `none`
  (case-insensitive); any other `Spec-PR:` line beside it — `none because …`, `TBD`, a second `none`, a number —
  fails. On the numbered path today's acceptance stays (a second number or an unrelated value such as `TBD` beside
  `Spec-PR: #<n>` is tolerated, as the `\s*` of the unchanged numbered pattern — which even accepts the number on
  the next line — always was), except that a `Spec-PR-reason:` line or any `Spec-PR:` value **starting with**
  `none` is a conflict. Description values echoed by a failure message are printed as `repr()` literals truncated
  to 80 characters, so a carriage return or a `::` cannot start a runner log line or a workflow command.
- **Rationale**: the first draft counted only exact `none` lines, so `Spec-PR: none` + `Spec-PR: none because it
  is a refactor` passed, and so did `Spec-PR: none` + `Spec-PR: TBD` — neither "exactly one declaration". "Starts
  with `none`" on the numbered path catches `none because x` beside a number without touching the acceptance SC-009
  protects.
- **Alternatives considered**: failing every extra `Spec-PR:` line on the numbered path too (cleaner, but it
  rejects descriptions the gate accepts today — SC-009); treating `none because …` as an unrelated value rather
  than a conflict beside a number (rejected: it reads as a second declaration to a human).
