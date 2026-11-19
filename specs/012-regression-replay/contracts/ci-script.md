# Contract: `scripts/check_replay.py` (the CI regression gate)

A standalone script (research D13: `httpx` + the standard library only, no import of `ui/` or `kestrel`'s
backend package) that calls a *running* Kestrel API's batch-replay endpoint for one target and turns the result
into a process exit code a CI pipeline can gate on.

## Invocation

```text
uv run python scripts/check_replay.py --target-id TARGET_ID
```

| Input | Source | Required |
|-------|--------|----------|
| `--target-id` | CLI argument, an integer | yes |
| `--timeout SECONDS` | CLI argument, a number; overrides the default below | no |
| `KESTREL_API_URL` | environment variable, same name `ui/api_client.py` reads; default `http://127.0.0.1:8000` | no |
| `KESTREL_API_TOKEN` | environment variable, same name `ui/api_client.py` reads; sent as `X-Kestrel-Token` when non-empty | no |

`--help` documents every exit code below (FR-037).

**The batch call's timeout.** The batch is synchronous and can legitimately run
for as long as `cap` replays' worth of wall-clock time, far beyond `httpx`'s 5 s default. Before calling the
batch endpoint, the script `GET`s `/api/config` and defaults its own HTTP timeout for the batch call to
`config["replay"]["max_batch_runs"] × config["replay"]["per_replay_time_limit_s"] + 60` seconds:
`per_replay_time_limit_s` is the server's own `max(adaptive time limit,
single-turn deadline)` (research D13), not the adaptive limit alone, because a batch can include single-turn
sources too, whose own 90 s deadline is otherwise invisible to this script; `--timeout SECONDS` overrides this
computed default outright.

## Behaviour

1. `GET {KESTREL_API_URL}/api/config` to read the batch cap and the per-replay time limit (for the timeout above).
2. `POST {KESTREL_API_URL}/api/targets/{target_id}/replays` with the token header when set, using that timeout.
3. On a transport failure (connection refused, DNS failure, timeout) or a non-2xx response: print one line naming
   the problem (never the raw response body, which could echo a URL or header value back) and exit `3`.
4. On success, print one line per entry — `source_run_id`, `replay_run_id`, `family`, `outcome`, and **both**
   evidence flags (not just one) — the source's own (`source_hard_evidence` →
   `canary` / `judge`) and the replay's own (`replay_hard_evidence` → `canary` / `judge`), since the two can
   legitimately differ (the judge configured today need not be the one that decided the source) — **except the
   one entry whose own replay crashed (`outcome: "inconclusive"` with
   `stop_reason: "replay_failed"` on the batch), whose replay evidence kind prints `none` instead of `judge`**:
   `replay_verdict` there is `"unclear"` with no judge call that actually concluded it, so labelling it `judge`
   would claim a verdict no judge gave — and one summary line with the three counts and whether the batch was
   complete; **never** attack text, reply text, the target's URL, or a header value (FR-035; the response body
   itself never contains any of those either, per `contracts/api.md`, so this is a belt-and-braces rule on the
   script's own formatting, not a redaction step it must perform).
5. Exit:

| Condition | Exit status |
|-----------|-------------|
| `counts.still_vulnerable > 0` (whether or not `complete`) | `1` |
| `complete` is `false` and no entry is `still_vulnerable` — **an incomplete batch could not tell, and a CI gate must fail closed on "could not tell", never pass it as if nothing happened** | `2` |
| `complete` is `true`, `counts.still_vulnerable == 0`, `counts.inconclusive > 0` | `2` |
| `complete` is `true`, `counts.still_vulnerable == 0`, `counts.inconclusive == 0` (every entry fixed, or `entries` is empty) | `0` |
| the API call itself failed, or the batch was refused (404 unknown target, 409 `permission_missing` /
  `terms_outdated` / `batch_too_large` / `run_in_progress`), or `--target-id` was missing or not an integer | `3` |

Row 1 is checked before every other row (FR-036: "still vulnerable" wins over a simultaneously present
"inconclusive" **or** an incomplete batch).

## Worked examples

```text
$ uv run python scripts/check_replay.py --target-id 3
run 12 -> replay 41: direct_injection: fixed (source: canary, replay: judge)
run 15 -> replay 42: system_prompt_leak: still_vulnerable (source: judge, replay: judge)
2 replays, complete: 1 fixed, 1 still_vulnerable, 0 inconclusive
$ echo $?
1
```

```text
$ uv run python scripts/check_replay.py --target-id 3
run 12 -> replay 41: direct_injection: fixed (source: judge, replay: judge)
batch stopped early (run_in_progress): 1 of 3 replayed, 2 not replayed (runs 19, 23)
$ echo $?
2
```

```text
$ uv run python scripts/check_replay.py --target-id 3
run 12 -> replay 41: direct_injection: fixed (source: canary, replay: judge)
run 15 -> replay 43: system_prompt_leak: inconclusive (source: judge, replay: none)
batch stopped early (replay_failed): 2 of 4 replayed, 2 not replayed (runs 19, 23)
$ echo $?
2
```

```text
$ uv run python scripts/check_replay.py --target-id 9
No target with id 9.
$ echo $?
3
```
