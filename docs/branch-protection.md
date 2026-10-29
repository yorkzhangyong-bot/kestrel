# Branch protection (manual setup)

Feature 006's approval gate depends on GitHub **branch protection**, which a repository cannot configure from
committed files — the owner applies it by hand (Settings → Branches → **Add branch ruleset / rule** for `master`,
or the REST API). Apply these settings once; the repo ships only the `CODEOWNERS` file and this guide (FR-013).

## Settings for `master`

- **Require a pull request before merging.**
  - Required approvals: **1**.
  - **Require review from Code Owners.** (Works with [.github/CODEOWNERS](../.github/CODEOWNERS), which assigns
    `*` and `/specs/` to `@ilikeandroid`.)
  - Dismiss stale approvals when new commits are pushed (recommended).
- **Require status checks to pass before merging**, with **Require branches to be up to date before merging**.
  - Required checks (names must match the `qa.yml` job names **exactly**): **`traceability`**, **`quality`**,
    **`review`**. (`notify` is best-effort and is **not** required.)
- **Do not allow bypassing the above settings** (apply to administrators too).
- (Optional) Require conversation resolution before merging.

## Why the code owner differs from the PR author

Pull requests are opened by **`@yorkzhangyong-bot`**; GitHub does not count a PR author's own review toward a
Code Owners requirement. The code owner is therefore the separate human reviewer account **`@ilikeandroid`**, so
every PR genuinely requires a second person's approval.

## Order and caveats

- Apply this **after** the workflow that defines the `traceability`/`quality`/`review` jobs has merged to
  `master`, so those check names exist to be selected; otherwise protection waits on checks that never report.
- Required checks always report a result on every PR (including a `quality` job that reports success without
  running its heavy steps on a spec-only PR), so protection is never left pending (FR-006).
- **SC-004's guarantee — no change reaches `master` without a code-owner approval — holds only once these
  settings have been applied by the owner.** Until then the repo cannot enforce or verify it.
