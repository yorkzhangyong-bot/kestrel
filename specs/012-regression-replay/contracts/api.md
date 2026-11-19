# Contract: the replay API

Two new endpoints, both synchronous (research D11; FR-038) — the request completes only once every message has
been sent and scored, exactly like `POST /api/runs` today — plus replay fields on the existing run and config
shapes. Every error uses the existing `{"error": {"code", "field", "message"}}` shape (`api_error`,
`contracts/kestrel-api.md`).

## `POST /api/runs/{run_id}/replay`

Replays one run. No request body.

**201** `RunDetail` of the new replay run (the same shape `GET /api/runs/{id}` returns for it, `comparison`
included — see below).

**404** `not_found` — no run with this id (`get_run` raises `LookupError`, same as today's `GET /api/runs/{id}`).

**409**, checked in this order, before anything is claimed. **MAJOR finding, round 2 review — every `message` is
pinned word for word** (`data-model.md`'s `REPLAY_BLOCKED_REASONS`), identical to what `replay_blocked_reason`
already showed on this same run before the click (`compute_replay_status`, `data-model.md`), so the two can never
disagree:

| `code` | When | `message` (verbatim) |
|--------|------|------------------|
| `replay_of_replay` | the run's own `mode == "replay"` | `"This run is itself a replay of run #<source run id>."` |
| `not_replayable` | `status == "in_progress"` | `"A run still in progress can't be replayed."` |
| `not_replayable` | `status == "finished"` and `verdict != "succeeded"` (failed, unclear, **or** never reached a verdict because sending it failed) | `"Only a succeeded run can be replayed."` |
| `not_replayable` | (defensive; not reachable through normal operation) no recorded attacker message | `"This run has no recorded message to resend."` |
| `permission_missing` | the target's permission box is not confirmed | `"Tick the permission box and save the target before attacking it."` (unchanged wording from `POST /api/runs`) |
| `terms_outdated` | the target's accepted terms are not current | `"The terms of service have changed; read them and tick the box again."` (unchanged wording) |
| `run_in_progress` | another run (any mode) is already in progress on the target | (unchanged wording) |

## `POST /api/targets/{target_id}/replays`

Batch-replays every currently-replayable run of one target, oldest first. No request body.

**200** `BatchReplayResultOut` (MINOR finding, round 2 review: **not** 201 — a batch result is not "one resource
created", the way a single replay is; this status is used for every batch result alike: complete, incomplete, or
zero entries), a **complete** batch (every replayable run at the moment it started was processed):

```json
{
  "target_id": 3,
  "entries": [
    {"source_run_id": 12, "replay_run_id": 41, "family": "direct_injection",
     "source_verdict": "succeeded", "source_hard_evidence": true,
     "replay_verdict": "failed", "replay_hard_evidence": false, "outcome": "fixed"}
  ],
  "counts": {"fixed": 1, "still_vulnerable": 0, "inconclusive": 0},
  "complete": true, "stop_reason": null, "not_replayed_source_ids": []
}
```

`entries` is `[]`, every count is `0`, and `complete` is `true` when the target has no replayable run (FR-033) —
still **200**, not a refusal.

**MINOR finding, round 1 review — a mid-batch collision is never a 409.** The preconditions below (and the cap)
are checked once, before the batch starts, and refused with a **409** before any entry is claimed, exactly as a
normal run's own preconditions are. Once the batch has started, it can stop before reaching every planned entry
in either of two ways, neither a precondition failure of the *batch request itself*, so neither is ever a 409 —
both still answer **200**:

- **A later entry's own claim collides with a genuinely concurrent run** on the same target (another browser tab,
  or the CI script and a user acting at the same moment — FR-029's edge case):
  ```json
  {
    "target_id": 3,
    "entries": [ /* every entry completed before the collision */ ],
    "counts": { /* counts over the completed entries only */ },
    "complete": false, "stop_reason": "run_in_progress",
    "not_replayed_source_ids": [19, 23]
  }
  ```
- **One entry's own replay fails with an unexpected error** (POSSIBLE finding, round 2 review, accepted; research
  D17) — that entry's own run still closes, recorded inconclusive, and is included as the batch's own last entry
  (it produced a run, just not a clean one); the batch is never answered as a 500 for this:
  ```json
  {
    "target_id": 3,
    "entries": [ /* every entry completed before the failure, PLUS the failed one itself, recorded
                    "inconclusive" */ ],
    "counts": { /* includes the failed entry's "inconclusive" */ },
    "complete": false, "stop_reason": "replay_failed",
    "not_replayed_source_ids": [23]
  }
  ```

`not_replayed_source_ids` names every replayable source, in the planned oldest-first order, that the batch never
reached. A caller that must not treat an incomplete batch as "nothing to worry about" checks `complete` — the CI
script (`contracts/ci-script.md`) does exactly that, failing closed rather than scoring an incomplete batch as if
it had finished cleanly.

**404** `not_found` — no target with this id.

**409**, checked before any entry is claimed, in this order (an already-running precondition, never a mid-batch
one — see above):

| `code` | When | `message` names |
|--------|------|------------------|
| `permission_missing` / `terms_outdated` | same as a normal run | (unchanged wording) |
| `batch_too_large` | `len(replayable runs) > Settings.replay_batch_max_runs` | the replayable count, the configured cap, and that the cap (`KESTREL_REPLAY_BATCH_MAX_RUNS`) is configurable |
| `run_in_progress` | another run is already in progress on the target **before the batch's first entry is claimed** | (unchanged wording) |

## Replay fields on existing shapes

`RunSummary` and `RunDetail` (`GET /api/runs/{id}`, `GET /api/targets/{id}/runs`, and the `RunDetail` returned by
the two endpoints above) gain:

```jsonc
{
  "source_run_id": 12,           // null unless mode == "replay"
  "replay_outcome": "fixed",     // null unless mode == "replay"
  "finding": false,              // MINOR finding round 2 review: true only for a succeeded, non-replay run.
                                  // POLISH finding round 3: one boolean cannot drive two cards — the UI's
                                  // Confirmed card sums finding && hard_evidence, Suspected sums finding &&
                                  // !hard_evidence, and Runs counts every run; never a mode check of its own
                                  // (FR-027)
  "replayable": false,           // MAJOR finding round 2 review: computed from this run AND its target's
                                  // current permission/terms state (research D10/compute_replay_status) — never
                                  // from the run's own fields alone
  "replay_blocked_reason": "This run is itself a replay of run #12.",   // renamed from not_replayable_reason;
                                  // present only when replayable is false; one of the exact strings above
  "replay_advisory": null        // new, independent of replay_blocked_reason: e.g. "This source recorded more
                                  // turns than the current adaptive limit; the replay can end at best still
                                  // vulnerable or inconclusive." on a replayable run whose source out-ran the
                                  // current adaptive turn limit; null otherwise
}
```

`RunDetail` additionally carries, **only when `mode == "replay"`**:

```jsonc
{
  "comparison": {
    "source_run_id": 12, "replay_run_id": 41, "outcome": "fixed",
    "source_verdict": "succeeded", "source_hard_evidence": true,
    "source_judge_model": null, "source_judge_prompt": null,
    "replay_verdict": "failed", "replay_hard_evidence": false,
    "replay_judge_model": "google/gemini-3.8-flash", "replay_judge_prompt": "judge@1",
    "turns": [
      {"position": 1, "sent": true, "source_verdict": "succeeded", "replay_verdict": "failed"},
      {"position": 2, "sent": false, "source_verdict": null, "replay_verdict": null}
    ]
  }
}
```

`comparison` is computed fresh on every request (research D8), by loading the source run (`source_run_id`) and
both runs' turns; `null` for a non-replay run.

## `GET /api/config`

`ConfigOut` gains `replay: {"max_batch_runs": 20, "per_replay_time_limit_s": 300}` (research D12/D13) — the batch
cap in effect, so the UI (or a curious operator) can see the limit without triggering a refusal first, and the
longer of the two per-run deadlines the server actually enforces (`max(adaptive_time_limit_s,
single-turn deadline)`, POSSIBLE finding round 2 review, accepted), which `scripts/check_replay.py` reads to size
its own batch timeout (`contracts/ci-script.md`).

## Deny-list (unchanged, Principle IV)

Neither endpoint, nor the `comparison` object, ever needs or carries an auth header value, an API key, the
target's URL, or the target's display name; the judge still receives only attack text and reply text (or the
per-turn conversation), never any of those (FR-047).
