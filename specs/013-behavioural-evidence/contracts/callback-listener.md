# Contract: the canary callback listener

Kestrel's own listener records requests to URLs it planted. It needs no target cooperation; it needs to be
reachable by the target (FR-027 to FR-031; research D13–D15).

## Configuration

| Variable | Meaning |
|----------|---------|
| `KESTREL_CALLBACK_BASE_URL` | The public base URL at which the listener route is reachable, **ending in the route's own prefix** — for the in-process listener, `http://<host>:<port>/callback` (for example `http://127.0.0.1:8000/callback`). Unset: the listener is disabled — the route is not mounted (FR-073) — no URL is planted, the callback check is skipped (FR-027). Must be an http or https URL without credentials, or Kestrel refuses to start. |
| `KESTREL_CALLBACK_WAIT_S` | The bounded wait after each reply of a run that planted a URL; default `2`; `0` = check once, never sleep (FR-030). Always additionally bounded by the run's remaining time. |

**The base URL must be usable for the target being attacked** (FR-068). A loopback or private-network base URL is
never planted into a run against a public target: the target would be pointed at its own loopback, or at a third
party if the base is mistyped. Kestrel checks this when the configuration loads (refusing a malformed base
loudly) and again per run; when the per-run check refuses, the run plants no callback task, records the reason
(`callback_note` on its detail, shown with its result), and every other check proceeds normally.

`GET /api/config` reports `evidence.callback_listener` (`true`/`false`) and `evidence.callback_wait_s`, never the
base URL (FR-038). The sidebar shows exactly **"Callback listener: on"** or **"Callback listener: off"** (FR-042).

## The planted URL

`<KESTREL_CALLBACK_BASE_URL>/<token>` where `<token>` is 24 lowercase hexadecimal characters (`secrets.token_hex(12)`),
generated for that one run and never generated again for another (the only run besides its own that carries it is
a replay of that run, FR-035), stored on the run (`run_planted_tokens`, kind `callback`) with the template version
that planted it (`callback_task@N`). It is planted only in runs of the tool-exfiltration family, in both modes,
placed in the opening message through the versioned `callback_task` template (`contracts/prompts.md`), and only
when the base URL is usable for that target (FR-068).

## The route

`/callback/{token}` on the Kestrel API, methods `GET`, `POST`, `PUT`, `HEAD`. **Mounted only when
`KESTREL_CALLBACK_BASE_URL` is set** (FR-073): with it unset no `/callback/` path exists — a request there gets the
application's ordinary not-found response, no store lookup, no `callback.*` line and, in hosted mode, no exemption
from the access token.

| Condition | Status | Body | Side effects |
|-----------|--------|------|--------------|
| `{token}` is carried by a run that is `in_progress` (its own planting, or the copy a replay in progress holds) and that run holds fewer than `CALLBACK_HITS_CAP` (100) hit rows | `204` | empty | one `callback_hits` row (`run_id` = that in-progress run, `method`, `received_at`); one `callback.hit` log line bound to that run |
| `{token}` is carried by a run in progress that already holds `CALLBACK_HITS_CAP` hit rows (consumed or not) | `204` | empty | **nothing stored**; one `callback.ignored` warning with `reason_kind` `hit_cap_reached`, bound to that run, once per run per process (FR-072) |
| any other token, or a token whose runs are all finished | `404` | empty | nothing recorded; one `callback.ignored` warning per `reason_kind` per process (`unknown_token` / `run_not_in_progress`) |

- The route **never reads the request body** and never echoes any part of the request (FR-029).
- The route is exempt from the hosted-mode access token (`require_token` returns early for `/callback/` paths):
  its caller is the target, not the user (FR-029).
- `{token}` must match `^[0-9a-f]{24}$`; anything else is `404` without a store lookup.

## Attribution and the bounded wait (FR-030)

After each reply of a run that planted a URL, the run's checker polls the store for unconsumed hits of its own run
id every 0.25 s until a hit appears or `min(KESTREL_CALLBACK_WAIT_S, remaining run time)` has passed; new hits are
consumed and produce **one** `canary_callback` evidence item for that turn, detail `"<METHOD>"` (or `"<METHOD>
(<n> hits)"` when several arrived, naming the first hit's method; `<n>` counts stored hits only, so it never
exceeds `CALLBACK_HITS_CAP`, FR-072), location `callback`, class LLM06. A hit that
arrives after the wait but before the run ends is picked up by the next turn's check and attributed to that turn;
a hit after the run has ended answers `404` and records nothing.

## Replay (FR-035)

A replay copies its source's planted tokens, so while the replay is `in_progress` the listener resolves the
source's token to the replay (the source itself is finished) and records the hit against the replay run. A replay
of a source that planted nothing has no callback token and skips the check (FR-036).

**When the listener can no longer receive the source's URL** — it is disabled now, or the configured base URL has
changed since the source ran, so the re-sent URL points somewhere Kestrel does not listen — the replay cannot
re-test the callback at all. Such a replay is **scored by the normal replay rule, except that a result that would
otherwise be fixed becomes inconclusive** (FR-069), carrying the reason on its own detail so the user is not left
to infer that an agent which still calls out was "fixed". Kestrel decides this by comparing the re-sent URL's base
with the currently configured base, not by waiting for a hit that can never arrive.

## Redaction (FR-031)

Every text handed to a model — the attacker's conversation, the judge's attack text, reply and conversation, the
recommender's winning message and evidence — passes through `redact_callback_urls`, which replaces every URL ending
in one of the run's planted callback tokens (or, for a replay, in its source's recorded URL) with the constant
placeholder `[callback-url]` — keyed on the token, not the configured base, so it still redacts a replay that
re-sends a source URL whose base has since changed or whose listener is now off (FR-069). Stored messages are never
redacted, so a replay re-sends the real URL.

The **reverse** direction, `restore_callback_url(text, url)`, runs on an attacker-generated message as it is sent:
because the attacker only ever sees the placeholder, it writes the placeholder where the address belongs, and
Kestrel substitutes the run's real URL into the text it sends **and stores** (FR-070). The attacker's and the
judge's view of that message keeps the placeholder. This is the one documented exception to "attacker messages are
never edited", and it keeps the stored message equal to the sent message, so feature 012's replay still re-sends
something that works. Without it, a stateless target could only ever be given the URL on turn 1.

## What the log carries (`contracts/log-records-delta.md`)

`callback.hit` carries `method` and the run's scope fields; `callback.ignored` carries `reason_kind` (`unknown_token`,
`run_not_in_progress`, or `hit_cap_reached` — the last bound to its run, once per run per process). Neither carries
the token, the URL, the caller's address or any header (FR-048).
