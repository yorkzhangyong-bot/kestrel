# Quickstart: validating 014 by hand

PowerShell, from the repo root. Needs `OPENROUTER_API_KEY` only for the HS-code target's own conversational agent
(the target, not Kestrel's attacker/judge, which the offline checks below stub out).

## Part 1 — the checkpointer (User Story 1, User Story 4's part-1 half)

1. Start the API: `uv run uvicorn kestrel.api.main:create_app --factory --host 127.0.0.1 --port 8000`.
2. Register a target (or reuse one) and start an **adaptive** attack against it (checkbox left off).
3. While it is running, kill the `uvicorn` process (Ctrl-C twice, or `Stop-Process`) — do this once early (before
   turn 2) and once again on a second run after at least two turns have completed.
4. Restart the API. Confirm the start-up log shows a `run.interrupted` line for the killed run with
   `resumable: true`, and that `GET /api/runs/{id}` shows `status: "in_progress"`, `resumable: true`,
   `paused: false`.
5. Click **Resume** on that run's page. Confirm: no new attacker call was made for any turn that already has a
   `run_turns` row (check the run's own Log expander — no `model.request kind="attacker"` line for an
   already-recorded turn); the run continues and reaches a normal conclusion.
6. Start a **single-turn** run and a **replay**, kill the process mid-flight for each, restart, and confirm both are
   closed exactly as before this feature (`stopping_condition: "interrupted"`, never shown as resumable).
7. Start another adaptive run, kill the process after at least one turn, restart, and click **Stop** instead of
   Resume on that run's page. Confirm: the run finishes immediately (`stopping_condition: "stopped_by_user"`), no
   new turn is sent, its target unlocks at once (a new run against it succeeds), and `GET /api/runs/{id}` no longer
   reports it `resumable`.
8. While that run from step 4/5 is actually resuming, a second click on its own **Resume** button shows no control
   at all (a leased run displays neither Resume nor Stop) — to actually provoke the race, call
   `POST /api/runs/{id}/resume` twice back to back against the API directly. Confirm the second request gets a 409
   naming that the run is currently executing — never a second, concurrent execution.

## Part 2 — the approve node (User Story 2, User Story 3, User Story 4's part-2 half)

1. Start an adaptive attack with **"Ask before each turn"** ticked.
2. Confirm turn 1 (the library seed) is sent immediately, and the run's page then shows the pending turn-2 message
   with **Approve**, **Run to end**, and **Stop**.
3. Click **Approve**: confirm turn 2 is sent and scored, and (if the run continues) the page shows a new pending
   message for turn 3.
4. On a fresh paused run, click **Run to end**: confirm that turn is sent and the run continues, unattended, to a
   normal conclusion with no further pause.
5. On a fresh paused run, click **Stop**: confirm the run ends immediately, the pending message was never sent (no
   new `run_turns` row for it), and the run's page shows it stopped by the user.
6. Pause a run, kill the `uvicorn` process before deciding it, restart, and confirm the run's page shows the
   **identical** pending message and the same three controls; decide it and confirm the outcome matches step 3/4/5.
7. While any run from steps 2–6 sits paused, try to start a new run or a replay against the same target and
   confirm Kestrel refuses it.
8. On a fresh paused run, a second click on **Approve** once the first has already sent shows no pending turn to
   decide (the page already moved on) — to actually provoke the race, call `POST /api/runs/{id}/decision` for the
   same pending turn twice back to back against the API directly. Confirm exactly one of the two sends the message;
   the other gets a 409 saying the run is currently executing or that its pending turn has already moved on — never
   two messages sent for the one turn.

## The automated SC-010 scenarios (not this manual walkthrough)

Unlike the manual steps above (which really do start and kill a real `uvicorn` process), the offline test suite's
own part-1 SC-010 scenario cannot spawn or kill a real process in CI, and a browser-driven test cannot restart
Kestrel at all (`tests/e2e-browser/run-history.spec.ts` records that doing so is forbidden). Part 1's own automated
scenario instead builds **two separate `create_app` instances over one temporary database**, both in the same
Python process — a real process boundary is not crossed. What the scenario actually proves is a real
*application* boundary: the two instances' execution leases are independent (per-`app.state`, never module-level),
so nothing lease-related carries over; the only thing shared is the one stateless, module-level `LIVE_GRAPH`
template each instance independently builds its own checkpointed copy from, which carries nothing run-specific.
Everything that decides whether a run's own progress and lock survive the "restart" lives in the shared database
file, not in either instance's own process memory — which is what actually matters (FR-005's "rebuilt fresh").
Part 2's own scenario exercises the pending-message/three-button controls offline, or through the browser suite's
generic stub target (never "the HS-code target's stub", which does not exist as such).

## Live HS-code e2e (known blocked; do not treat as a failure of this feature)

Per CLAUDE.md's gotcha (first recorded 2026-11-21, recurred 2026-11-24): the HS-code target's own chat call
currently 502s because the OpenRouter account's guardrail no longer allows whatever model `CARGOLINT_CHAT_MODEL`
names, so **every** live e2e scenario fails at the connection-test step, not just this feature's. Confirm this is
still the case (an untouched, pre-existing e2e such as `tests/e2e/test_us1_connection.py` fails identically) before
concluding anything about this feature from a live-e2e run; rely on the offline suite and the two scenarios above
instead (SC-010).
