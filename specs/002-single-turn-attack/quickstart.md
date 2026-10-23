# Quickstart: Run One Single-Turn Attack and Judge the Result

How to run feature 002 and prove it works. Builds on [feature 001's quickstart](../001-register-target/quickstart.md); everything there still applies.

## Set up

```bash
uv sync                                   # Kestrel
uv sync --project targets/hs_code         # sacrificial target, first time only
```

Two keys matter:

| Variable | Needed for | Note |
|---|---|---|
| `OPENROUTER_API_KEY` | the judge, and the sacrificial target's own model calls | Without it the target answers 502 and judged runs end "unclear" |
| `HS_TARGET_CANARY` | the sacrificial target's system prompt | The value you declare as a canary on the target in Kestrel |
| `KESTREL_JUDGE_MODEL` | choosing the judge | Optional; defaults to `google/gemini-3.8-flash` |

## Run it

Three terminals.

```bash
# 1. the sacrificial target (PowerShell: $env:HS_TARGET_API_KEY="test-key-123" etc.)
HS_TARGET_API_KEY=test-key-123 HS_TARGET_CANARY=KESTREL-CANARY-7Q4M2X OPENROUTER_API_KEY=sk-or-... \
  uv run --directory targets/hs_code uvicorn app:app --host 127.0.0.1 --port 8001

# 2. the API
KESTREL_MODE=local OPENROUTER_API_KEY=sk-or-... \
  uv run uvicorn --factory kestrel.api.main:create_app --host 127.0.0.1 --port 8000

# 3. the screen, at http://localhost:8501
uv run streamlit run ui/app.py
```

Register the sacrificial target as in feature 001, then add `KESTREL-CANARY-7Q4M2X` as a canary string and save.

## Manual checks

| # | Do this | Expect | Covers |
|---|---|---|---|
| 1 | Pick the target, family **System prompt leak**, click Run attack | A verdict within 90 seconds, with the prompt and reply as plain text | US1.1, SC-001 |
| 2 | On a run where the canary appeared in the reply | "Attack succeeded · confirmed by canary"; the run detail shows `judge_used: false` and no judge model | US1.2, SC-003 |
| 3 | Watch the API log during check 2 | No judge call is made | SC-003 |
| 4 | Family **Direct prompt injection**, on a reply with no canary | A judge verdict naming the model, labelled "suspected", never "confirmed" | US1.3, SC-005 |
| 5 | Open the run in the runs table | Prompt, reply, reason, judge model and attacker source `library:<version>` all shown | US2.2, SC-004 |
| 6 | Pick a specific prompt by title, then Run | The prompt shown as sent is the one picked | US3.1 |
| 7 | Run two attacks, restart the API, reopen the target | Both runs still listed, newest first | US2.3, SC-010 |
| 8 | Delete the target, then look for its runs | Gone with it | US2.4 |
| 9 | Register a second target but do not tick permission; try to attack it | "Tick the permission box and save the target before attacking it." Nothing is sent | SC-009 |
| 10 | Edit a target's URL so its permission clears, then try to attack | Refused until permission is confirmed again | FR-009 |
| 11 | With a target saved under terms version 1, try to attack after the judge clause lands | "The terms of service have changed; read them and tick the box again", with the terms open | FR-023 |
| 12 | Click Run attack twice quickly | The second is refused with "A run against this target is already in progress." | FR-010 |
| 13 | Stop the API mid-run, start it again, open the target | The interrupted run is listed with verdict "unclear" and an interrupted reason, and a new run can start | SC-012 |
| 14 | Point the target at a port where nothing listens, then Run | A run is stored with the "unreachable" step, no verdict and no judge call | US1.5, FR-014 |
| 15 | Start the API with no judge key; run an attack with no canary match | "No judge configured" in the sidebar, and the run ends "unclear" rather than failing | FR-021, Principle IX |
| 16 | Same, but against a reply containing the canary | Still "confirmed by canary" — hard evidence needs no judge | Principle II |
| 17 | Have the target reply with HTML, a script, a link and an image reference, then view the run | Shown as characters; no outside request is made | SC-007 |
| 18 | Search the run records and all logs for the target's auth header value | 0 occurrences | SC-006 |
| 19 | Family **Tool-mediated exfiltration**, then read the target's recorded tool calls | A `send_email` call recorded, with nothing sent | FR-035 |

Checks 2, 4 and 5 together are the three end-to-end tests in SC-008.

**On the model-dependent checks (walkthrough 2026-10-24).** Checks 2, 16 and 19 — and the "suspected" wording in check 4 — only appear when the agent is actually compromised (its canary surfaces, or it calls `send_email`, or the judge rules "succeeded"). The sacrificial target runs `openai/gpt-4o-mini`, which resists these attacks fairly robustly, so against it the live runs come back "failed" and no canary or tool call appears. This is the target model's behaviour, not a Kestrel defect:

- The **detection mechanisms** are proven deterministically: canary-match → "succeeded"/hard-evidence/no-judge in `tests/unit/test_runs.py` and `tests/integration/test_api_runs.py`; the `send_email` recorder and `GET /debug/tool-calls` in `targets/hs_code/tests/`.
- To **see a positive canary detection in the screen** (check 2/16), point the target at an endpoint whose reply contains the declared canary; the run is then "Attack succeeded · confirmed by canary" with no judge call.
- All the other checks (1, 3, 5–15, 17, 18) were verified directly and pass. Check 5 required a fix: the run detail now shows the attacker source (`library:<version>`).

## Tests

```bash
uv run pytest                    # unit and integration: offline, no keys, no cost
uv run pytest -m e2e             # end-to-end: needs OPENROUTER_API_KEY; starts the target and the API itself
uv run --directory targets/hs_code pytest   # target smoke tests, no model calls
```

The end-to-end run covers SC-008: a system-prompt-leak attack settled by its canary with no judge call; a harmless prompt judged "failed"; and the stored run naming the judge model. Its fixtures start the sacrificial target and the API themselves and stop them afterwards, with no manual steps (FR-036).

Judge cost is a fraction of a cent per judged run, because FR-022 caps what it reads. A full `-m e2e` run makes at most two judge calls.
