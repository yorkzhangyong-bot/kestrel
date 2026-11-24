# Contract: PR classification and implementation-PR rules

Spec-only classification and the implementation-PR rules. The pure helpers take plain arguments so they are
unit-tested without GitHub; the script wraps them with the real diff, a live read of the pull request and, on the
bugfix path, a live issue lookup.

**Amended 2026-11-24** (revised after review rounds 1–3 and the owner's review of spec PR #50): the Spec-PR rule's
scope is corrected to what the gate has enforced since 2026-11-10 (`src/` or `ui/` changes, on any branch — commit
df9a65f), and the rule gains the honest path for refactor and bug-fix PRs (FR-009 amended; FR-015–FR-020, FR-022,
FR-024 added). The gate reads the **raw** description, exactly as today: text inside an HTML comment or any other
markup counts like any other line (the round-1 comment stripping was reversed in round 2, research §16). Owner's
review of PR #50: a `bugfix: #<issue>` number must be an existing issue of this repository (FR-024), and a body or
reason-label change re-runs only the traceability job, through a recheck workflow (FR-019).

**Amended again 2026-11-24** (review of the owner changes, round 2): the recheck no longer classifies a re-run
refusal by the POST's HTTP status code — GitHub's endpoint sends the same code for "another attempt is already
running" and for a final refusal, so the recheck re-reads the run instead; the merge rule now also covers a pull
request from a fork directly; and the recheck's step machine ships as a small tested script, `scripts/qa_recheck.py`
(research §11).

**Amended again 2026-11-24** (review of the owner changes, round 3): the recheck script's API failures are
specified — every client call returns a value or raises, a transient failure is retried within the budget and
never read as "no run", a run with no `traceability` job reaches the failure signal, and `already_fresh` never
raises on a missing or malformed timestamp (research §11).

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

### Spec-PR declaration rule (FR-009, FR-015, FR-016, FR-017, FR-018, FR-020, FR-022, FR-024)

Evaluated only when the PR changes `src/` or `ui/` (`changes_app_code(changed_files)`), on **any** branch. A PR
that changes only `tests/`, `scripts/`, `docs/` or `specs/` is not evaluated: a `Spec-PR:` line on it is ignored.

#### Grammar

```text
SPEC_PR_RE        (?im)^Spec-PR:\s*#\d+                                # numbered form — unchanged
SPEC_PR_LINE_RE   (?im)^Spec-PR:[ \t]*(.*?)[ \t\r]*$                   # every keyed Spec-PR: line, value captured
REASON_LINE_RE    (?im)^Spec-PR-reason:[ \t]*(.*?)[ \t\r]*$            # every reason line, value captured
REASON_VALUE_RE   (?i)^(?:(refactor)|(bugfix):[ \t]*#([0-9]+))$        # a well-formed reason value; group 3 = the digits
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
spec_pr_rule_problems(pr_body: str | None, labels: list[str],
                      issue_exists: Callable[[str], bool]) -> list[str]      # [] == rule satisfied; pure given a pure stub
parse_pr_state(raw: str | None) -> tuple[str, list[str]]                     # (body, label names) from gh's JSON
pr_state() -> tuple[str, list[str]]                                          # the live read (subprocess); any failure -> ("", [])
parse_issue_lookup(raw: str | None, repository: str, number: str) -> bool    # True only for an issue of this repository
issue_exists_in_repo(number: str) -> bool                                    # the live lookup (subprocess); any failure -> False
pr_rule_problems(files: list[str], pr_body: str | None, labels: list[str],
                 issue_exists: Callable[[str], bool]) -> list[str]           # the pure wiring
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
| 10 | the reason is `bugfix: #<n>` and `issue_exists(n)` is `False` | fail: `#<n>` is not an issue of this repository — a pull request, a transferred or deleted issue, a number that does not exist, or a failed lookup (FR-024); `<n>` is digits only |
| 11 | otherwise | pass (FR-015) |

Row 10 is the **only** place the lookup is called: at most one call per run, none on the refactor path and none
when rows 1–9 already decided (FR-024).

The hint (FR-020), added to the row 2, 4 and 6 messages before the accepted-forms sentence, because a quoted example is
the likely cause of a second keyed line:

```text
every column-1 keyed line counts, also inside code blocks and HTML comments; indent quoted examples
```

Accepted-forms sentence (FR-020), appended to every failure of this rule:

```text
Accepted forms: 'Spec-PR: #<n>'; or 'Spec-PR: none' + 'Spec-PR-reason: refactor' + label 'refactor'; or 'Spec-PR: none' + 'Spec-PR-reason: bugfix: #<issue>' + label 'bugfix'.
```

- The number in `Spec-PR: #<n>` is never looked up (SC-009); the number in `bugfix: #<n>` is (FR-024).
- **Echoed values** (rows 3, 4, 7): a value from the description is printed as a Python literal — `repr(value)`,
  truncated to 80 characters — never raw, so a lone carriage return or a `::warning::` / `::add-mask::` prefix
  inside a value cannot start a runner log line or a workflow command. Row 10 echoes only the digits.

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
  pull-requests: read, issues: read}` (FR-018, FR-024).
- Why live and not the event payload: a manual re-run reuses the original event's snapshot, and `gh pr create
  --label` fires `opened` (no labels yet) and `labeled` on one commit; reading at evaluation time makes every
  run judge the same, current state (research §10).

#### The issue lookup (FR-024)

```text
gh api "repos/$GITHUB_REPOSITORY/issues/<n>"                                # run by issue_exists_in_repo(), timeout 30 s
```

- `parse_issue_lookup(raw, repository, number)` → `True` only when `raw` is a JSON object whose `number` equals
  `int(number)`, that carries **no** `pull_request` key (the issues endpoint returns pull requests too), and whose
  `repository_url` ends with `/repos/<repository>` compared ignoring case (an issue of another repository, or one
  transferred there — whether or not the redirect was followed — fails). `state` is ignored: open or closed both
  pass. `None`, an empty string, invalid JSON, a non-object or any missing field → `False`.
- `issue_exists_in_repo(number)`: reads `GITHUB_REPOSITORY` from the environment and calls `subprocess.run` (both
  monkeypatched in the unit tests); a non-zero `gh` exit (404 for a non-existent number or one the token cannot read, 410 Gone for a
  deleted issue, 301 for a transfer when the redirect is not followed, 403/429 for a rate limit), a `TimeoutExpired`, a `FileNotFoundError` or any other exception → `False`; a successful call →
  `parse_issue_lookup(stdout, repository, number)`. Every failure prints a one-line notice naming only the digits.
- Called by row 10 only — at most once per run, after every other condition of the honest path holds.

#### Wiring

```text
pr_rule_problems(files, pr_body, labels, issue_exists):
    if not files or is_spec_only(files): return []            # not an implementation PR (or no PR context)
    problems = spec_pr_rule_problems(pr_body, labels, issue_exists) if changes_app_code(files) else []
    if not spec_change_ok(files, pr_body): problems.append(<spec-change message>)
    return problems

_pr_rule_problems() == pr_rule_problems(changed_files(), *pr_state(), issue_exists_in_repo)
```

### Inputs from the environment

- `changed_files`: from `git diff --name-only origin/$GITHUB_BASE_REF...HEAD`.
- `PR_NUMBER` (`github.event.pull_request.number`) and `GITHUB_REPOSITORY` (set by the runner) for the live read
  and the lookup; `GH_TOKEN` = `github.token`, with the traceability job's `permissions` set to `contents: read`,
  `pull-requests: read` and `issues: read` (enough for `gh pr view` and `gh api …/issues/<n>`; the workflow-level
  `pull-requests: write` stays because `classify`, `quality` — the gitleaks action comments on PRs — and `notify`
  inherit it, while the review job declares its own permissions block).
- `PR_BODY` is **no longer read**: the event snapshot is exactly what the live read replaces.

### Workflow wiring (`qa.yml`)

- `on.pull_request` keeps GitHub's **default** activity types (`opened`, `synchronize`, `reopened`); no `types`
  list. Every job runs in full on every run; no job and no step is conditional on the event — a skipped required
  job reports success and would replace an earlier failure on the same commit (FR-006), and a verdict-only review
  job would mark an unreviewed commit green (research §11, round 2).
- The traceability job declares `permissions: {contents: read, pull-requests: read, issues: read}`; its step's
  `env` carries `PR_NUMBER: ${{ github.event.pull_request.number }}` and `GH_TOKEN: ${{ github.token }}` in place
  of `PR_BODY`.

### Recheck workflow (`qa-recheck.yml`, FR-019 — owner's review of PR #50; revised after its review round 1)

A separate, **non-required** workflow re-runs the traceability job when, and only when, a relevant event happens,
by running a small tested script, `scripts/qa_recheck.py` (below), after `actions/checkout` and `actions/setup-python`
(the same pair the traceability job itself runs before `check_traceability.py` — the interpreter is never assumed
from the runner image).

```yaml
on:
  pull_request:
    types: [edited, labeled, unlabeled]
    branches: [master]
permissions:
  actions: write          # re-run a job of the QA run (and read runs and jobs)
  contents: read
  pull-requests: write    # the one fixed-text stale-result comment (step 5)
jobs:
  recheck:
    timeout-minutes: 35   # backstop to the 30-minute wait below
    if: >-
      (github.event.action == 'edited' && github.event.changes.body != null) ||
      ((github.event.action == 'labeled' || github.event.action == 'unlabeled') &&
       (github.event.label.name == 'refactor' || github.event.label.name == 'bugfix'))
```

- **No `concurrency` group, on purpose.** An irrelevant event's run only skips its own job and can never cancel
  or replace a relevant recheck, whatever order GitHub evaluates `if` and `concurrency` in. Two relevant events
  give two rechecks; each waits, requests the re-run, and on any refusal re-reads the run — not yet `completed`
  means another attempt is in progress, so it goes back to waiting and retries within the same bound. Every
  attempt reads the live state, so the last attempt judges the latest change (research §11, review of the owner
  changes).
- **Relevance** (a pure function of the event: `recheck_relevant(action, changes, label_name)`): `edited` is
  relevant only when the payload's `changes` carries `body` (the body changed; a title or base-branch edit does
  not); `labeled` / `unlabeled` only when `label.name` is `refactor` or `bugfix` (GitHub ignores case when comparing
  strings in expressions). Anything else: the run starts and its job is skipped — nothing re-runs. A job-level `if`
  is safe **here** because this check is not required: its skipped runs change no required result (the FR-006
  hazard concerns required checks).
- **Steps** (`GH_TOKEN: ${{ github.token }}`; `gh api`; no step reads or prints the body; every API call carries
  its own timeout, e.g. 30 s, after which it either has returned a value or raised `RecheckApiError` — never a
  silent empty/`None` standing in for a failure, see "Recheck script" below; step 5 always has time to run inside
  the job's `timeout-minutes: 35`; one 30-minute budget for steps 2–4 — the pure mirror in the reference probe and
  in `scripts/qa_recheck.py` is `next_action(run_status, rerun_status, elapsed, budget)`, where `rerun_status` is
  `None` / `"accepted"` / `"refused"`, never a literal HTTP status code, and `run_status` additionally carries
  `"error"` (a failed read: retried, or the failure signal once the budget runs out) and `"no_job"` (a completed
  run with no `traceability` job: the failure signal at once, nothing to retry toward)):
  1. `run` = the newest `qa.yml` run for the current head commit —
     `GET /repos/{owner}/{repo}/actions/workflows/qa.yml/runs?head_sha=${{ github.event.pull_request.head.sha }}&event=pull_request&per_page=1`;
     an empty, successful list (a merge conflict), or a run that has not started for lack of approval (`status`
     `action_required` or `waiting`) → print a notice, exit `0` (there is no result to refresh). A failed read
     (`RecheckApiError`) is never read as "no run": print a notice, wait, and retry at the next poll within the
     budget (`run_status = "error"`) — never exit `0` on a failure.
  2. Wait until `run.status == "completed"` (poll every 30 s; a re-run needs a completed run); a failed read is
     retried the same way, within the same budget. When the budget runs out — waiting on a slow run or retrying a
     failing read alike — → step 5 (`timeout` if the last read was a genuine, still-running status; `error` if the
     last read was a failure).
  3. `job` = the run's job named `traceability` — `GET /repos/{owner}/{repo}/actions/runs/{run_id}/jobs?filter=latest`.
     A failed read is retried like step 2's. A **successful** read that finds no job of that name is not transient
     — waiting cannot make one appear — so it goes to step 5 (`error`) at once, without spending the rest of the
     budget retrying.
  4. **Freshness check, then the re-run request.** Before requesting a re-run, `already_fresh(job.started_at,
     recheck_created_at)` (the recheck's own run `created_at`, read once via
     `GET /repos/{owner}/{repo}/actions/runs/{github.run_id}` — no earlier than the triggering event, so the
     comparison is conservative): when the job's latest attempt already started after this recheck run was
     created, its live read already includes the change — print a notice, exit `0`, no POST spent (minor-round
     fix: avoids spending one of GitHub's 50 re-runs per workflow run on an attempt that is already current). A
     failed read of `created_at` is retried like step 2's (the POST is not sent on an error — only `already_fresh`
     returning `False` sends it); `already_fresh` itself never raises — a missing or unparsable `started_at` or
     `created_at` it is given makes it return `False` (never fresh, so the POST is sent — never skipped on bad or
     absent data). Otherwise, `POST /repos/{owner}/{repo}/actions/jobs/{job_id}/rerun` — "Re-run a job and its
     dependent jobs in a workflow run" (GitHub's REST description): `traceability` and its only dependent, `notify`
     (which acts only on failure); never `quality` or `review`. The endpoint documents exactly two responses, `201`
     (accepted) and `403` (refused); GitHub returns the same `403` — "This workflow is already running"
     (`cli/cli#9221`) — whether another attempt of this run is already in progress or the refusal is final (a fork
     pull request's read-only token, the platform's cap of 50 re-runs per workflow run — full and partial both
     count — or the 30-day limit), so the status code alone never tells the two apart. Accepted → print a notice,
     exit `0`. Refused, for any reason → re-read the run (`GET /repos/{owner}/{repo}/actions/runs/{run_id}`): not
     `completed` → another attempt is now running, so back to step 2 and retry within the budget; still
     `completed` → no new attempt started, the refusal is final → step 5 (`refused`). A failed re-read is retried
     like step 2's, within the same budget — the POST itself is not re-sent until the run is confirmed `completed`
     again. The budget exhausted while waiting, erroring or retrying → step 5 (`timeout` or `error`, whichever the
     last read showed when it ran out).
  5. **Failure signal.** Post one pull-request comment with fixed text that names only the reason class
     (`timeout`, `refused` or `error`) and carries no description or label value: the traceability result on this
     commit may be stale; refresh it with a push, or a manual re-run of the `traceability` job; do not merge before
     a `traceability` attempt that started after this comment has passed — a push, a manual re-run, or a later
     automatic recheck re-run all count. The text never contains the literal substring `VERDICT: PASS` or
     `VERDICT: FAIL` (the `review` job's own verdict step matches the latest PR comment against that pattern, so
     the recheck's comment must never be mistaken for it); the POST is retried once before giving up. Then exit
     `1`. On a fork pull request the comment itself is refused too (read-only token): print the notice and exit
     `1` — refresh `traceability` with a push or a manual re-run after the last body or label change before
     merging, whatever the recheck shows (spec Assumptions). **The script's entry point wraps the whole sequence in
     a catch-all**: any exception steps 1–4 do not already turn into a retry or a `"error"`/`"no_job"` outcome (a
     bug, not a documented `RecheckApiError`) still reaches this step — the comment is attempted (with its one
     retry) before exit `1` — so a defect in the script itself can never look like a silent, uncommented exit `0`.
- The re-run attempt judges the current body and labels through the live read (FR-018) and reports under the
  required `traceability` check name on the same commit, replacing the earlier attempt's result; the quality gate
  and the review keep theirs. A later recheck run whose job is skipped shows "skipped" under the `recheck` name,
  which is why the failure of step 5 is persisted as a comment rather than left on the check alone.
- **Rollout**: a pull request already open across the merge has `qa.yml` runs from the old workflow and script;
  its recheck re-runs the old `traceability` job (event-payload body, no honest path), which fails closed — such a
  pull request needs one push. Documentation behind the design: research §11.

### Recheck script (`scripts/qa_recheck.py`, FR-019 — shipped as a tested script, not inline workflow steps)

Steps 1–5 above are one small stdlib script, run by the `recheck` job after `actions/checkout` and
`actions/setup-python` — the PR's own copy, with the recheck job's token (a same-repository author could already
run their own workflow code with that token; a fork pull request's checkout still gets the read-only token, so
every write call above still fails for it exactly as before). The script takes an injected API client (one method
per `gh`/REST call above) so its step machine, including the refusal re-read and every failure path below, is
unit-tested offline — no network, no `gh` on the test machine:

```text
get_latest_run(head_sha) -> RunInfo | None            # step 1 - None only for a genuinely empty, successful list
get_run(run_id) -> status: str                        # step 2 poll, and the post-refusal re-read of step 4
get_job(run_id, name) -> JobInfo | None                # step 3 - None only for a genuinely missing job
get_recheck_run_created_at() -> str                    # step 4's freshness pre-check: this recheck's own run
                                                        # (github.run_id), never the QA run found in step 1
request_rerun(job_id) -> Literal["accepted", "refused"]  # step 4's POST; never a literal status code
post_comment(text) -> None                             # step 5, retried once on failure
already_fresh(attempt_started_at: str, recheck_created_at: str) -> bool   # step 4's pre-check, ISO 8601 compare
```

- **Every client method above returns its declared value, or raises `RecheckApiError`, after its own per-call
  timeout (e.g. 30 s) — there is no third, silent outcome.** In particular `get_latest_run`'s `None` and
  `get_job`'s `None` each mean only a **successful** call that genuinely found nothing (an empty run list; a run
  with no `traceability` job) — never a stand-in for a failed call, which always raises instead. This is the
  fix for the class of defect where a transient failure reads as "nothing to do" and the recheck exits `0` with no
  signal: review rounds 1–2 closed that class for the refusal and the concurrency design; this closes it for every
  other read.
- `already_fresh`: `True` when `attempt_started_at` is **not earlier** than `recheck_created_at` — `True` skips
  the POST (step 4) and exits `0` without spending one of GitHub's 50 re-runs per workflow run. It **never
  raises**: a missing (`None`/empty) or unparsable value for either argument makes it return `False` — not fresh,
  so the POST is sent rather than silently skipped. (This is distinct from `get_recheck_run_created_at` itself
  raising `RecheckApiError`, which is a step-4 read failure, retried like any other.)
- `next_action(run_status, rerun_status, elapsed, budget)` is the same pure function the Steps list above
  describes; `rerun_status` is `None` / `"accepted"` / `"refused"` — never `201`/`403` — because the endpoint
  returns the same `403` whether another attempt is in progress or the refusal is final (step 4).  `run_status`
  additionally carries `"error"` (a `RecheckApiError` from steps 1–3 or the post-refusal re-read of step 4: `wait`
  if `elapsed < budget`, else the failure signal with reason `error`) and `"no_job"` (step 3 found the run
  `completed` with no job named `traceability`: the failure signal with reason `error` at once, regardless of
  `elapsed` — nothing about waiting longer would make a job appear). A `request_rerun` failure is treated the same
  way as any other step-4 read failure (`run_status = "error"` for that cycle) rather than as a third `rerun_status`
  value, since an unanswered POST is exactly as uninformative about whether a re-run started as any other failed
  read — the next cycle's re-read settles it.
- Comment hygiene: the fixed text of step 5 never contains the literal substring `VERDICT: PASS` or
  `VERDICT: FAIL` (the `review` job's own verdict-enforcement step matches the latest PR comment against that
  pattern); every API call carries its own timeout (e.g. 30 s); the comment `POST` is retried once.

#### Tests (`tests/unit/test_qa_recheck.py`, T034; 006/FR-019)

With a stub, injected API client (no network, no `gh`): waiting (`status` not `completed` → poll again);
`completed` with no re-run requested yet (request it); refused, the re-read shows the run still running (retry —
`"wait"`); refused, the re-read shows the run `completed` (the comment, exit `1` — `"fail-refused"`); the budget
exhausted while waiting or retrying (the comment, exit `1` — `"fail-timeout"`); no run for the head SHA (a
**successful** empty list), and a run in `action_required` / `waiting` (exit `0`, no comment); `already_fresh` true
(skip the POST, exit `0`, no comment, no re-run spent); the comment text itself (names only the reason class, no
body or label value, never contains `VERDICT: PASS` or `VERDICT: FAIL`). **Failure-handling rows (review round 3)**:
`get_latest_run` raises → retried at the next poll, never read as "no run" (no silent exit `0`); if the budget then
runs out while it keeps failing → the comment, exit `1`, reason `error`; `get_run` raises during the step-2 poll →
retried, the comment when the budget runs out; `get_job` raises, or returns `None` for a genuinely completed run →
the comment (the first retried like any other step-3 failure; the second — `"no_job"` — at once, no retry spent);
`get_recheck_run_created_at` raises → the POST is still sent once the retry succeeds (never skipped on an error);
`already_fresh` given a missing or unparsable timestamp → `False`, not an exception, and the POST is sent; an
uncaught exception anywhere in the step sequence → the script's entry-point catch-all still posts the comment
(with its one retry) before exit `1`.

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
006/FR-024, 006/SC-008, 006/SC-009) — the matrix over `spec_pr_rule_problems` (with a stubbed `issue_exists`),
`parse_pr_state`, `pr_state`, `parse_issue_lookup`, `issue_exists_in_repo` and `pr_rule_problems` (the reference
probe `probe_006_rule.py`, updated to this contract after each review, decides every row below exactly one way):

- **pass** (row 1): `#<n>` with neither new line — with no labels, with `refactor`, with both labels; beside a
  second numbered line; beside `Spec-PR: TBD`; the number on the next line (`Spec-PR:` then `#12`, the unchanged
  `\s*`); the numbered line inside a multi-line `<!--` … `-->` block whose keyed line starts in column 1 (the raw
  description counts); `#<n>` + a one-line reason comment `<!-- Spec-PR-reason: refactor -->` (not a keyed line, so
  no conflict). The lookup stub is never called on this row.
- **pass** (row 11): `none` + `refactor` + label `refactor`, also with both lines inside a multi-line `<!--` … `-->`
  block whose keyed lines start in column 1 (raw read); `none` + `bugfix: #12` + label `bugfix` with a stub that
  answers `True`; `none` + `bugfix: #999999` + the same stub (the form is the rule's business, the lookup the
  stub's); `bugfix:#12`; `bugfix:<tab>#12`; case variants (`spec-pr: NONE`, `SPEC-PR-REASON: Refactor`, label
  `Refactor`); CRLF line endings; extra blanks around the value.
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
  `bugfix` only is row 8 (the matching label is checked first); row 10 — `none` + `bugfix: #37` + label `bugfix`
  with a stub that answers `False` (the message names `37`, digits only, and ends with the accepted forms).
- **lookup discipline** (FR-024, a stub that counts its calls): the row-11 bugfix pass makes exactly one call with
  the digits; the refactor path, every bugfix body decided by rows 1–9 (no label, both labels, a malformed number)
  and the numbered form make zero calls.
- **parse**: `parse_pr_state` on `{"body": "…", "labels": [{"name": "refactor"}]}` → the body and
  `["refactor"]`; `body` missing or non-string → `""`; `labels` with an element lacking a string `name`
  (`[{"name": 1}]`, `["refactor"]`), or not a list → `[]`; `None`, `""`, invalid JSON, a non-object → `("", [])`.
  `parse_issue_lookup` → `True` for an issue object of this repository (`number` matching, no `pull_request` key,
  `repository_url` ending with `/repos/<repository>` in any letter case, `state` open or closed alike); `False` for
  a `pull_request` key, a `repository_url` of another repository (a transfer), a `number` that differs, a missing
  field, a non-object, invalid JSON, `None`, `""`.
- **live read and lookup, failure path** (`pr_state` and `issue_exists_in_repo` with `os.environ` and
  `subprocess.run` monkeypatched, stdout captured): no `PR_NUMBER` → `("", [])` and `subprocess.run` never called;
  a non-zero exit → `("", [])` / `False`; `subprocess.TimeoutExpired` → `("", [])` / `False`; `FileNotFoundError`
  → `("", [])` / `False`; a successful call → `parse_pr_state` / `parse_issue_lookup` of its stdout; the notice on
  every failure carries no body or label value, and the lookup's notice names only the digits.
- **wiring**: `pr_rule_problems` (with `issue_exists` passed through) — `["src/kestrel/x.py"]` + a valid honest
  path + `["refactor"]` → `[]`; the same with `[]` labels → exactly the row-8 message; `["tests/unit/t.py"]` with
  a lone `Spec-PR: none` → `[]`; `["src/kestrel/x.py", "specs/006-x/spec.md"]` + a valid honest path with no
  `spec-change:` → exactly the spec-change problem; the same with a column-1 `spec-change:` line, outside a comment
  or inside a multi-line `<!--` … `-->` block (raw read) → `[]`; the same with only a one-line
  `<!-- spec-change: x -->` → the spec-change problem (not a keyed line).
- **recheck relevance** (FR-019; the workflow's `if` is validated by reading, T030, and live, T031 — the pure
  mirror `recheck_relevant(action, changes, label_name)` lives in the reference probe): `edited` with `changes`
  containing `body` → relevant; `edited` with `title` or `base` only → not; `labeled` / `unlabeled` with
  `refactor`, `bugfix`, `Refactor` → relevant; with `documentation` → not; `opened`, `synchronize` → not.
- **recheck steps** (FR-019; the pure mirror `next_action(run_status, rerun_status, elapsed, budget)` in the
  reference probe and in `scripts/qa_recheck.py` — `rerun_status` is `None` / `"accepted"` / `"refused"`, never a
  literal HTTP status code, and a refusal is classified by re-reading the run, never by the code, since GitHub
  returns the same `403` for both causes; the workflow is validated by reading, T030, and live, T031; the script's
  own step machine and `already_fresh` are unit-tested offline, T034): no run, or a run in `action_required` /
  `waiting` → `exit-0-no-run`; `queued` / `in_progress` within the budget → `wait`; `completed` with no re-run
  requested yet → `rerun`; accepted → `exit-0-done`; a refused re-run whose fresh re-read shows the run no longer
  `completed` (another attempt is running) → `wait` (retry); the same refusal with the re-read still `completed`
  (no new attempt; final) → `fail-refused`; the budget exhausted while waiting or retrying → `fail-timeout`;
  `run_status = "error"` (any failed read of steps 1–3 or the post-refusal re-read) → `wait` within the budget,
  else `fail-error`, never `exit-0-no-run`; `run_status = "no_job"` (a completed run with no `traceability` job) →
  `fail-error` regardless of `elapsed`.
- The spec-change rule is still required on the honest path (`spec_change_ok` with a `specs/**` + `src/**` change
  and `Spec-PR: none` in the body).
- Existing assertions (`has_spec_pr_reference`, `changes_app_code`, `is_spec_only`, spec-change) stay untouched
  (SC-009).
