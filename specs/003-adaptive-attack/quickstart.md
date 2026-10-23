# Quickstart: Run a Multi-Turn Adaptive Attack and Judge the Result

How to run feature 003 and prove it works. Builds on [feature 002's quickstart](../002-single-turn-attack/quickstart.md); everything there still applies. No attack prompt text appears here.

## Set up

```bash
uv sync
uv sync --project targets/hs_code      # first time only
```

Environment (all optional except a key for the models):

| Variable | For | Default |
|---|---|---|
| `OPENROUTER_API_KEY` | the attacker, the judge, and the target's own model | — |
| `KESTREL_ATTACKER_MODEL` | the attacker | `deepseek/deepseek-v3.2` |
| `KESTREL_ATTACKER_API_KEY` | the attacker key | falls back to `OPENROUTER_API_KEY` |
| `KESTREL_JUDGE_MODEL` | the judge | `google/gemini-3.8-flash` |
| `KESTREL_ADAPTIVE_MAX_TURNS` | the turn cap | `6` |
| `KESTREL_ADAPTIVE_TOKEN_BUDGET` | the token budget | `40000` |
| `KESTREL_ADAPTIVE_TIME_LIMIT_S` | the wall-clock cap | `300` |
| `HS_TARGET_API_KEY`, `HS_TARGET_CANARY` | the sacrificial target | — |

## Run it

Three terminals, as in feature 002 — the sacrificial target, the API (`KESTREL_MODE=local`, with `OPENROUTER_API_KEY` so both the attacker and judge work), and the screen. Register and save the target as before; declare `HS_TARGET_CANARY` as a canary on it.

## Manual checks

| # | Do this | Expect | Covers |
|---|---|---|---|
| 1 | Pick the target, set the mode toggle to **Adaptive**, choose a family, Run | Several turns run, then one verdict; the conversation is shown turn by turn as plain text | US1.1, SC-001 |
| 2 | Open the finished run | Each attacker message and target reply in order, then the verdict, the reason, how it ended, and the attacker and judge models | US2.1, SC-004 |
| 3 | Read the run's detail | It names the attacker model, the judge model, the turn/token/time budgets allowed, and the turns and tokens used | SC-004, Principle III |
| 4 | Run against a target whose reply reveals the declared canary at some turn | The run stops at that turn, "confirmed by canary", no judge call for that turn | US1.2, SC-003 |
| 5 | Let a run reach the turn cap without success | It ends "failed" or "unclear" and records that it stopped at the turn cap, not that the agent is safe | US1.3, SC-002 |
| 6 | Set `KESTREL_ADAPTIVE_MAX_TURNS=2` and run | The run uses at most 2 turns and records the turn cap it hit | FR-010 |
| 7 | Set `KESTREL_ADAPTIVE_TOKEN_BUDGET` very low and run | The run stops early and records the token budget as the stopping condition | FR-010 |
| 8 | Run two attacks after changing `KESTREL_ATTACKER_MODEL` | Each run names the model that drove it; the earlier run keeps its model | SC-004 |
| 9 | Restart the API, reopen the target | The adaptive runs and their full conversations are still listed | SC-010 (persistence) |
| 10 | Stop the API mid-run, start it again | The interrupted run is listed "unclear" with an interrupted reason and its turns so far; the target can run again | SC-010 |
| 11 | Delete the target | Its adaptive runs and conversations are gone | US2.4 |
| 12 | With a target saved under terms version 2, try an adaptive attack | "The terms of service have changed; read them and tick the box again", with the terms open | FR-003, R11 |
| 13 | Start the API with no attacker key; try an adaptive attack | The screen says no attacker is configured and the run cannot start | FR-016 |
| 14 | Point the target at a dead port, run adaptive | A run is stored with the failed step, no verdict, no further turns | US1.5, FR-013 |
| 15 | Have a reply carry HTML, a script, a link and an image reference, then view the run | Shown as characters; 0 outside requests | SC-007 |
| 16 | Search the stored conversation and all logs for the target's auth header value | 0 occurrences | SC-006 |
| 17 | List a target with both single-turn and adaptive runs | Each row shows its kind, verdict and when it ran, newest first | US2.2 |

Checks that depend on the target actually being compromised (4, and a judge ruling "succeeded") are model-dependent, as in feature 002: the detection mechanisms are proven deterministically in the test suites, and a positive canary hit can be shown with a target whose reply contains the declared canary.

## Tests

```bash
uv run pytest                    # unit and integration: offline, stub attacker/judge/sender, no keys
uv run pytest -m e2e             # end-to-end: needs OPENROUTER_API_KEY; one adaptive run vs the sacrificial target
uv run --directory targets/hs_code pytest   # target smoke tests, no model calls
```

The end-to-end test covers SC-009: an adaptive attack completes with a verdict, records the attacker model and the turns used, and stores the full conversation. A full `-m e2e` run makes several model calls (attacker + judge per turn), so it costs more than feature 002's — still well under the token budget's worst case.
