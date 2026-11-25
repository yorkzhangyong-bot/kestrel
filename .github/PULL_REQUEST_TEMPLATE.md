## Summary

<!-- What does this pull request do, and why? -->

<!--
PR body conventions (feature 006 — see docs/qa-pipeline.md):

- A PR that changes src/ or ui/ must declare its spec provenance on its own line, either:
    Spec-PR: #2
  or, for a behaviour-preserving refactor or a bug fix that implements no spec (carry the matching PR label too):
    Spec-PR: none
    Spec-PR-reason: refactor
  or:
    Spec-PR: none
    Spec-PR-reason: bugfix: #12
  (the bugfix: #<issue> number must be an existing issue of this repository; see docs/branch-protection.md for
  the refactor/bugfix labels).
- If this PR also edits a spec file alongside a src/ change, acknowledge it on its own line:
    spec-change: <reason>
- A PR that changes only tests/, scripts/, docs/ or specs/ needs none of the lines above.
- Spec-only PRs (changes under specs/ and docs/ only) need none of the lines above either; a code owner
  (@ilikeandroid) must approve before merge. See docs/branch-protection.md.

The gate reads this description's raw text, exactly as written: a keyed line above counts only when it starts in
column 1 (no leading spaces, bullet, quote or emphasis) — which is why every example here stays indented inside
this comment. Copying one out: start it at the very left margin of its own line.
-->
