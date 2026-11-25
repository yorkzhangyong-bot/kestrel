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

- **Decision 2026-11-24 (owner, review of spec PR #50) — re-run only on relevant events, through a recheck workflow.**
  The owner: "re-run the pipeline only when the PR body actually changed or when the refactor or bugfix label is added
  or removed, not on every edit or label event." Design (recommended by the coordinator, taken as is):
  - `qa.yml` goes back to the default trigger types (`opened`, `synchronize`, `reopened`); its jobs stay as specified,
    live read included.
  - A new small workflow, `.github/workflows/qa-recheck.yml`, on `pull_request` types `[edited, labeled, unlabeled]`,
    `permissions: {actions: write, contents: read, pull-requests: write}` (the last for one fixed-text comment),
    `branches: [master]` like `qa.yml`, `timeout-minutes: 35` on the job, and **no** concurrency group (below).
    Its single job runs only for a relevant event — a job-level `if`: `github.event.action == 'edited'` with
    `github.event.changes.body` present, or `labeled` / `unlabeled` with `github.event.label.name` equal to `refactor`
    or `bugfix` (GitHub ignores case when comparing strings). A job-level `if` is safe **here** because this check is not
    a required one: its skipped runs change nothing (the §2 hazard applies to required checks only).
  - The job finds the newest `qa.yml` run for the pull request's current head SHA, waits for it to complete (poll,
    bounded at 30 minutes), then re-runs that run's `traceability` job through the REST API — `POST
    /repos/{owner}/{repo}/actions/jobs/{job_id}/rerun`. With the live read of §10 the re-run judges the current body
    and labels. Only `traceability` reads the body or the labels (`review` reads the verdict comments, `quality` reads
    neither), so only it is re-run; its only dependent job is `notify`, which re-runs with it and emails only on
    failure. The paid review is never re-run by a body or label change. No QA run for the SHA (a merge conflict), or
    a run that has not started for lack of approval (`action_required` / `waiting`): the recheck reports it and exits
    without re-running — there is no result to refresh.
  - **Documentation the design rests on** (fetched 2026-11-24): the endpoint's description in GitHub's OpenAPI
    description (`github/rest-api-description`, `api.github.com.json`): "Re-run a job and its dependent jobs in a
    workflow run"; the REST reference page (REST → Actions → Workflow runs, "Re-run a job from a workflow run"): the
    fine-grained token "must have the following permission set: 'Actions' repository permissions (write)" and the
    endpoint works with GitHub App installation access tokens, which is what `GITHUB_TOKEN` is; the `GITHUB_TOKEN`
    permissions table (`github/docs`, `data/reusables/actions/github-token-scope-descriptions.md`): `actions` —
    "Work with GitHub Actions. For example, `actions: write` permits an action to cancel a workflow run"; the
    no-recursion rule (`data/reusables/actions/actions-do-not-trigger-workflows.md`): "events triggered by the
    `GITHUB_TOKEN` will not create a new workflow run" except `workflow_dispatch` / `repository_dispatch` and the
    approval-required `pull_request` opened/synchronize/reopened runs — a job re-run creates no event and no new
    workflow run, it adds an attempt to an existing run, so the rule does not reach it; re-running (`content/actions/
    how-tos/manage-workflow-runs/re-run-workflows-and-jobs.md`): possible "up to 30 days after its initial run",
    "Re-runs use the privileges of the actor who initially triggered the workflow", with "the same `GITHUB_SHA` and
    `GITHUB_REF` of the original event"; the `pull_request` `edited` payload (`webhook-pull-request-edited` in the same
    OpenAPI description): `changes` carries `base`, `body` and `title`, `body.from` being "The previous version of the
    body if the action was `edited`", and `labeled` / `unlabeled` carry `label`; forks (`data/reusables/developer-site/
    pull_request_forked_repos_link.md`): "The `GITHUB_TOKEN` has read-only permissions in pull requests from forked
    repositories" — so the recheck cannot re-run for a fork pull request; it reports that and the author pushes.
    The live draft-PR check (T031) proves the re-run with `GITHUB_TOKEN` before the merge, since a `pull_request`
    workflow file comes from the pull request's merge commit.
  - **Rejected options**: (a) adding `edited` / `labeled` / `unlabeled` to `qa.yml` and skipping jobs there on
    irrelevant events — a skipped required job reports success and replaces an earlier failure (§2); (b) the first
    design below, every such event re-running the whole pipeline — the owner rejected its cost and noise; (c) a
    `workflow_dispatch` of `qa.yml` from the recheck — it creates a new run with no `pull_request` context (no
    `github.event.pull_request.number`, no base ref for `classify`); (d) re-running the whole QA run instead of the
    one job — it would re-run the paid review and the quality gate for a label toggle; (e) `concurrency` on `qa.yml`
    itself — unchanged, not needed.
- **Decision 2026-11-24 (review of the owner changes, round 1) — no concurrency group on the recheck.** The first
  draft gave the recheck one group per pull request with `cancel-in-progress`, at the workflow level. The reviewer
  showed the defect: every `edited` / `labeled` / `unlabeled` run joins the group before the job-level `if` is
  evaluated, so a later *irrelevant* event — `gh pr edit --remove-label refactor --add-label documentation`, or the
  web label picker changing two labels at once — cancels or replaces the relevant recheck and then skips its own job;
  the removed label is never re-evaluated and the required check stays green with nothing red anywhere. **Fixed by
  removing the group entirely**: an irrelevant event's run only skips its own job and can never cancel or replace a
  relevant one, whatever order GitHub evaluates `if` and `concurrency` in. Two relevant events give two rechecks;
  each waits for the QA run, requests the re-run, and on a refusal because another attempt of the same run is in
  progress goes back to waiting and retries within the same 30-minute budget; every attempt reads the live state, so
  the last attempt judges the latest change. **Rejected**: (a) the workflow-level group — the defect above; (b) a
  job-level group — a job skipped by its `if` would not join it, but it relies on GitHub evaluating the `if` before
  the group, which the documentation does not promise, and two relevant events would still cancel each other's wait;
  (c) a conditional group expression (a unique group for irrelevant events) — the same undocumented ordering plus
  an expression nobody can read at a glance. A quickstart / T031 step now swaps `refactor` for an unrelated label in
  one action and requires `traceability` to turn red.
- **Decision 2026-11-24 (review of the owner changes, round 1) — stale-result cases and the failure signal.** A
  recheck that cannot re-run leaves `traceability` with its last attempt's result, possibly green after a change that
  invalidated the declaration. The cases: a fork pull request (read-only token); GitHub's cap — "A workflow run can
  be re-run a maximum of 50 times. This limit includes both full re-runs and re-runs of a subset of jobs"
  (`content/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs.md`, the page that also states the 30
  days); a QA run that does not complete within the bound; a re-run still refused when the bound runs out. The
  non-required `recheck` check alone is no signal: the next irrelevant event's run replaces its red with "skipped".
  So the recheck, on exit 1, posts **one fixed-text pull-request comment** (reason class only, no description or label
  value) saying the result may be stale and how to refresh it — a push, or a manual re-run of `traceability` — and
  its job gets `pull-requests: write` for that; a fork pull request cannot receive the comment either (stated with
  the fork case). The owner's **merge rule**, stated in the spec's Assumptions and in the `docs/qa-pipeline.md` task:
  after a failed recheck, do not merge until a `traceability` attempt that started after that comment has passed —
  a push, a manual re-run, or a later automatic recheck re-run all count; on a fork pull request, which gets no
  comment, the rule anchors to the last body or label change instead: refresh `traceability` with a push or a
  manual re-run before merging, whatever the recheck shows. **Rejected**: `pull_request_target` for the recheck —
  it would give fork pull requests a write token and
  runs no pull-request code, but it runs `master`'s copy of the workflow, so the draft-PR check (T031) could not
  prove the recheck before the merge; fork pull requests are not expected in this repository (one author, branches
  in the repository), so `pull_request` stays.
- **Decision 2026-11-24 (review of the owner changes, round 2) — classify a refusal by the run's own status, never
  by the POST's HTTP code.** The job re-run endpoint documents exactly two responses, `201` (accepted) and `403`
  (refused) (REST → Actions → Workflow runs, "Re-run a job from a workflow run"); GitHub returns the same `403` —
  "This workflow is already running" — whether another attempt of the run is already in progress or the refusal is
  final (`cli/cli#9221`, a debug log showing that message), so the code alone never tells the two apart. **Fixed**:
  on any refusal, re-read the run (`GET /repos/{owner}/{repo}/actions/runs/{run_id}`); not `completed` means another
  attempt is now running, so retry within the budget; still `completed` means a final refusal, so post the
  stale-result comment and exit 1. A discrete-event simulation of interleaved rechecks (20,000 scenarios, 1–3 s
  between a status read and the POST) found 0 unsafe outcomes either way, but the old by-code classifier produced
  6,285 false-alarm stale-result comments against 169 for the status-based one (every one of those 169 a run that
  genuinely ran longer than the recheck's budget) — a routine overlap of two relevant events (for example
  `refactor` swapped for `bugfix` in one action) no longer posts a spurious comment. A quickstart / T031 step now
  overlaps two *relevant* events in one action and requires both rechecks to exit 0 with no stale-result comment.
  **Sources**: `https://github.com/cli/cli/issues/9221`; `https://docs.github.com/en/rest/actions/workflow-runs`.
- **Decision 2026-11-24 (review of the owner changes, round 2) — the step machine ships as a tested script.** The
  recheck's steps are `scripts/qa_recheck.py`, run by the workflow after `actions/checkout` (the PR's own copy; a
  same-repository author could already run their own workflow code with the recheck job's token, and a fork pull
  request's checkout still gets the read-only token, so nothing changes for it), with an injected API client so
  the step machine — including the refusal re-read above — is unit-tested offline (T034). Before requesting a
  re-run, `already_fresh(attempt_started_at, recheck_created_at)` skips the POST and exits 0 when the traceability
  job's latest attempt already started after this recheck run's own `created_at` (read once,
  `GET /repos/{owner}/{repo}/actions/runs/{github.run_id}` — no earlier than the triggering event, so the
  comparison is conservative): that attempt's live read already includes the change, so spending one of GitHub's 50
  re-runs on it would be wasted. A burst of relevant events on one commit can otherwise cost toward that cap (the
  round-2 review's simulation found 49,528 accepted re-runs for 51,960 events in a burst scenario) or queue later
  rechecks behind earlier ones until they time out; the skip check reduces both. Comment hygiene: the fixed text
  never contains the literal substring `VERDICT: PASS` or `VERDICT: FAIL` (the `review` job's own
  verdict-enforcement step matches the latest PR comment against that pattern); every API call carries its own
  timeout (for example 30 s), so the comment step always has time to run inside the job's `timeout-minutes: 35`;
  the comment POST is retried once.
- **Decision 2026-11-24 (review of the owner changes, round 3) — API failures fail closed.** The round-2 design left
  unspecified what a transient API failure means: the natural implementation reads a failed `get_latest_run` the
  same as a genuinely empty one (`None` → "no run", exit 0) and lets a failed poll or job lookup crash the script
  (no comment). A review simulation with each read failing independently at probability 1%/5% found 747/4,688 of
  20,000 interleavings (respectively) ending stale with no comment under that reading; fail-closed handling gave 0
  at both rates. **Fixed**: every client call returns its declared value or raises `RecheckApiError` after its own
  timeout — `None` from `get_latest_run`/`get_job` means only a genuinely empty, successful result, never a
  failure. A raised error in steps 1–3 or the post-refusal re-read is retried at the next poll within the same
  budget; a budget spent this way still reaches the stale-result comment (a third reason class, `error`, alongside
  `timeout` and `refused`), never a silent exit 0. A run found `completed` with no job named `traceability` is not
  transient (polling cannot make one appear), so it reaches the comment at once rather than spending the rest of
  the budget retrying. `already_fresh` itself never raises: a missing or unparsable `started_at`/`created_at` makes
  it return `False` — not fresh, so the re-run request is sent rather than silently skipped on bad or absent data.
  The script's own entry point wraps the whole step sequence in a catch-all, so even a bug the retry logic does not
  already turn into `"error"` still posts the comment (with its one retry) before exit 1. **Rejected**: keeping
  `None` ambiguous and documenting the risk — the whole point of rounds 1–2 was closing exactly this silent-green
  class for the refusal and the concurrency design; leaving it open for every other read would undo that. The pure
  mirror's `next_action` gains `run_status = "error"` (retried within budget, else the comment) and `run_status =
  "no_job"` (the comment at once); a `request_rerun` failure is folded into `"error"` rather than a third
  `rerun_status`, since an unanswered POST is exactly as uninformative as any other failed read — the next cycle's
  re-read settles it either way.
- **Decision 2026-11-25 (found live, T031, quickstart scenario 6 step 2e) — `"no_job"` is transient after all,
  exactly like `"error"`.** The round-3 claim above — "polling cannot make one appear" — was wrong. On the
  throwaway draft PR's QA run `45587259204`, the `refactor`-swapped-for-`bugfix` overlapping-events step produced
  two relevant rechecks on one commit: recheck A read the run completed, found attempt 6's job (`139118750129`)
  and requested its re-run at `09:50:49.20`, which GitHub accepted (a new attempt 7 was created). Recheck B, 2 s
  later at `09:50:51.17`, also read the run completed (attempt 7 already existed) but called
  `get_job(filter=latest)` before attempt 7's own `traceability` job had been created (it appeared at
  `09:50:52`, started `09:50:55`) — a genuinely empty, successful job list for an attempt that was simply still
  being set up. Recheck B's job log showed no `<method> failed` notice (ruling out a `RecheckApiError` read), then
  went straight to `"Recheck giving up (reason: error)"` and posted a stale-result comment — the false alarm
  quickstart step 2e explicitly says must not happen (both rechecks must exit 0 with no comment). **Fixed**:
  `next_action` treats `run_status = "no_job"` exactly like `"error"` — `wait` if `elapsed < budget`, the comment
  only once the budget runs out — so `_poll`'s existing retry loop (already used for every other transient read)
  simply calls `get_job` again at the next 30 s poll, by which point the new attempt's job has normally appeared.
  No orchestration change beyond `next_action` itself was needed: `fetch_job`'s own retry path was already correct
  once the classification changed. **Rejected**: leaving `"no_job"` an immediate failure and instead teaching
  `request_rerun`'s caller to wait once before the first `get_job` call after a rerun is requested — narrower than
  the general fix, and does not help the next recheck instance that independently re-reads a run mid-setup for any
  other reason (for example a slow runner picking up the new attempt).
- *First decision, superseded by the owner's*: `on.pull_request.types: [opened, synchronize, reopened, edited,
  labeled, unlabeled]` on `qa.yml`, the whole pipeline running on each event, no job conditional on the event.
- *First design's rationale (superseded)*: GitHub's default is `opened` / `synchronize` / `reopened` only, so a label
  added through the UI after opening — the normal way a human labels a PR — would never count without a push; FR-019
  closes that trap (still true: the recheck now closes it). The whole pipeline had to run because a job skipped by a job-level `if` reports *success* and does not block a
  merge (GitHub docs, "Using conditions to control job execution"), so a `labeled` run that skipped `quality` /
  `review` would replace an earlier failure on the same commit with a green check.
- *First design's alternatives (superseded)*: keep the default triggers and document "push an empty commit or close
  and reopen" (rejected then: a trap, and it makes the label a decoration — the current design keeps the default
  triggers on `qa.yml` but closes the trap with the recheck); `labeled` / `unlabeled` only (rejected: a reason line
  added by editing the description would still need a push — an asymmetry nobody would guess); a `concurrency`
  group with `cancel-in-progress` to cap the cost of rapid successive edits (not added — no need shown yet; it
  would also cancel a push's run mid-way, which is a behaviour change of its own).
- **Re-run semantics** (after review round 1): with the live read of §10, a manual re-run of any earlier run judges
  the current description and labels, not the event that first triggered it.
- **Cost and noise** (after review round 1; superseded by the owner's decision above): each event re-ran quality
  (tests, coverage, scans) and the review; `gh pr create --label` yielded two runs on one commit (`opened`, then
  `labeled`), and the `opened` run could read before the label landed — then it failed and `notify` emailed once,
  and the `labeled` run was the newer, passing result. Once `SKIP_AI_REVIEW` was removed, every label or
  description event would have re-run the paid AI review and a label toggle re-rolled its verdict. Now: only the
  traceability job re-runs, only on a relevant event; the `opened` + `labeled` case becomes one pipeline run plus
  one re-run of its traceability job; no review is re-run.
- **Decision 2026-11-24 (review round 2) — no verdict-only review on those events.** Round 1 had recorded an
  optional mitigation: on `edited` / `labeled` / `unlabeled` the `review` job would skip its two Claude steps and
  run only the verdict-enforcement step over the latest verdict comment. **Rejected**, because it can mark an
  unreviewed commit green: a push of commit X starts a run whose review takes minutes; a label added meanwhile
  starts a second run, whose verdict-only step reads the previous commit's `PASS` and passes; the first run then
  posts `FAIL` for X, but the newest-triggered run decides the required `review` check, so X shows a `PASS` it
  never earned. With `gh pr create --label` there is no earlier verdict at all, so the variant would fail every
  freshly labelled PR until something else re-triggered it. Binding verdicts to the head SHA would fix both, but
  it is a change to the review job that this feature does not need. Every job of a pipeline run runs in full; a
  body or label event re-runs only `traceability`, via the recheck.

## 12. The issue number

- **Decision 2026-11-24 (owner, review of spec PR #50) — the bugfix issue must exist in this repository.** The
  owner: "the gate checks that the issue exists in this repository and fails closed if it does not." Design: once
  every other condition of the honest path holds on the bugfix path (rows 1–9 of the contract), the job makes one
  lookup — `gh api repos/$GITHUB_REPOSITORY/issues/<n>` with the job's token (`issues: read`) — and accepts only a
  JSON object whose `number` is `<n>`, that carries no `pull_request` key (the issues endpoint returns pull requests
  too), and whose `repository_url` ends with `/repos/<this repository>` (case-insensitive), so an issue transferred
  elsewhere fails whether the redirect is followed or not. Any state, open or closed, is accepted: a fix for a closed
  issue is legitimate. A non-existent number (404), a deleted issue (410 Gone — GitHub's "Get an issue": "If the issue
  was deleted from a repository where the authenticated user has read access, the API returns a 410 Gone status"), a
  transfer (301, or the other repository's `repository_url` when followed), a rate limit (403/429), a timeout, no `gh`
  on the path, invalid JSON or any other failure fails closed with a notice naming only the number (digits). The pure rule takes an
  injected `issue_exists(number) -> bool`, so offline tests stub it; the lookup lives beside `pr_state()` in the I/O
  layer; at most one lookup per run. The row's message names the number and says it is not an issue of this
  repository, then the accepted forms (FR-020).
- **Rejected alternatives (owner review)**: accepting only open issues (a closed issue may be the one fixed; and
  the owner asked for existence, not state); accepting a pull-request number (a "bug fix for a pull request" is not
  what the reason claims); following a transfer (the reason must point at this repository's tracker); GraphQL
  (`issue(number:)` rejects pull requests natively, but adds a second client surface for one field).
- *First decision, superseded by the owner's*: `bugfix: #<issue>` checked for form only (`#` followed by digits),
  no lookup.
- **Rationale**: the gate has never verified `#<n>` either; the helper stays pure; an issue's existence says
  nothing about whether it describes the fix — that is the reviewer's judgment; the label makes the claim visible
  in the pull-request list, and the owner's approval is the control.
- **Alternatives considered** (first decision): `gh api repos/…/issues/<n>` in the gate (then rejected as a false
  sense of verification — an issue's existence says nothing about the fix; the owner's decision above accepts that
  limit: the lookup proves the number is a real issue here, and the reviewer still judges the fix).

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
  cross-reference on a real issue or pull request — relaxed at the owner's review of PR #50 (next bullet): the
  bugfix pass step now cites the closed issue `#37`. Rollout order, stated once: labels created (T024) → the
  draft-PR live check (T031) → the implementation PR merged, carrying the roadmap item to Done (T028).
- **Owner review of spec PR #50 (2026-11-24)**: the draft-PR check also proves the recheck workflow and the issue
  lookup — a label change and a body edit re-run only the traceability job (the recheck appears as its own,
  non-required check); a title edit and an unrelated label re-run nothing; the bugfix pass step now references a
  real, closed issue of this repository (`#37`), which leaves a "mentioned this" cross-reference on that issue —
  accepted, the only trace the throwaway leaves; `#999999` exercises the not-found failure and a pull-request number
  (`#49`) the pull-request failure. After the review of the owner changes: the check also swaps `refactor` for an
  unrelated label in one action and requires `traceability` to turn red (no concurrency group can cancel the
  relevant recheck). Rollout note: a pull request already open across the merge has `qa.yml` runs from the old
  workflow and script, so its recheck re-runs the old `traceability` job (event-payload body, no honest path), which
  fails closed — such a pull request needs one push.

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
