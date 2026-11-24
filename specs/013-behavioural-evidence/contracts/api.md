# Contract: evidence on the API

Additions to Kestrel's existing API shapes (`specs/001-register-target/contracts/kestrel-api.md` and the deltas of
later features). Every error keeps the existing `{"error": {"code", "field", "message"}}` / `{"errors": [...]}`
shapes. No evidence-item detail, planted-token field, side-channel field or config field carries an auth header
value, a side-channel header value, a callback URL, a correlation id or a token value (FR-007, FR-038, FR-049).
The one exception is the returned message text itself: a run's `prompt_text` and turn `attacker_message` are
returned exactly as sent, which for a family that carries a planted task includes the planted paragraph with its
token parts (see "The `turn` rows" below, FR-011).

## Run shapes

### `RunSummary` (every run listing and detail) gains

```jsonc
{
  "evidence_kinds": ["canary_in_reply", "unsafe_executable_output"],   // distinct kinds, detection order; [] when none
  "evidence_labels": ["canary", "unsafe executable output"],           // the FR-004 labels, same order
  "evidence_count": 2,                                                   // items on the run (not distinct kinds)
  "side_channel_status": "not_configured"                                // "not_configured" | "checked" | "unavailable"
}
```

A run recorded before this feature with `hard_evidence` true and no stored items reports `evidence_kinds:
["canary_in_reply"]`, `evidence_labels: ["canary"]`, `evidence_count: 1` (FR-005, FR-040); a null
`side_channel_status` on such a row reads as `"not_configured"`.

### `RunDetail` additionally gains

```jsonc
{
  "evidence": [
    {"kind": "instruction_override", "label": "instruction override", "turn": 2, "location": "reply",
     "location_label": "in the reply", "owasp_category": "LLM01: Prompt Injection",
     "detail": "the planted marker appeared in the reply", "created_at": "2026-11-23T10:15:03Z"},
    {"kind": "honeypot_tool_invoked", "label": "honeypot tool invoked", "turn": 2, "location": "tool_call",
     "location_label": "in a tool call", "owasp_category": "LLM06: Excessive Agency",
     "detail": "approve_duty_refund", "created_at": "2026-11-23T10:15:03Z"}
  ],
  "planted_tokens": [
    {"kind": "override", "armed": true, "disarmed_turn": null, "prompt": "override_task@1"}
  ],
  "side_channel_notice": null,          // the exact FR-034 text when side_channel_status is "unavailable", else null
  "override_disarmed_notice": null      // "The override token was disarmed on turn N." when disarmed, else null
}
```

`planted_tokens` never carries a token value or a URL — only the kind, the armed state and the template reference
(FR-038). **No `detail` ever carries a token value or part, a URL, or a protected-state value** (FR-007): an
`instruction_override` item's detail is the fixed string `"the planted marker appeared in the reply"`, and a
`canary_callback` item's detail is the request method. An `unsafe_executable_output` item additionally carries
`"pattern_name"` and `"pattern_set_version"` as their own fields (FR-017). The notices are computed by the API so
the UI only displays them (FR-043), and a third, `"callback_note"`, carries either the FR-068 reason no callback
URL was planted (`"The configured callback listener can't be reached by this target, so no callback was
planted."`) or the FR-069 reason a replay's own URL no longer reaches Kestrel (`"This replay's recorded callback
URL no longer reaches Kestrel's listener, so a callback can't be re-tested."`), else null. Items are ordered by
`(turn, id)`; the `detail` of a reply-derived item is at most 200 characters of already-masked text.

### The `turn` rows of `RunDetail`

Unchanged in shape, and still **returned exactly as sent** — for a family that carries a planted task the
`prompt_text` and the turn's `attacker_message` therefore include the planted paragraph, because that is the text
Kestrel sent and stored (FR-011); a replay re-sends it byte for byte. The API does not strip or redact stored
message text (only the experience store and the model inputs see a stripped or redacted copy, FR-031, FR-063). An
item's `turn` indexes these rows (1-based; always 1 for a single-turn run).

## Target shapes

### `ConnectionSettingsIn` gains an optional side channel

```jsonc
{
  "url": "http://127.0.0.1:8001/chat", "method": "POST", "headers": [...], "body_template": "...", "response_path": "$.reply",
  "side_channel": {                                    // null or absent = no side channel
    "url": "http://127.0.0.1:8001/side-channel",       // validated like the target URL (FR-020)
    "header": {"name": "X-API-Key", "value": "…"},     // optional; value null keeps the stored value on PUT (FR-019)
    "honeypot_tool": "approve_duty_refund"             // optional; 1-100 chars of letters, digits, "_", "-", "."
  }
}
```

**422** field paths: `settings.side_channel.url`, `settings.side_channel.header.name`,
`settings.side_channel.header.value`, `settings.side_channel.honeypot_tool`, with the target-URL and header
messages the connection settings already use. A header named `X-Kestrel-Correlation-Id` (any letter case) under
`settings.headers` is refused with the existing `"Kestrel sets this header itself; remove it."` (FR-022).

### `TargetDetail` gains

```jsonc
{
  "side_channel": {                                    // null when the target has none
    "url": "http://127.0.0.1:8001/side-channel",
    "header_name": "X-API-Key",                        // null when no header is configured
    "has_value": true, "readable": true,               // as a target header: never the value itself
    "honeypot_tool": "approve_duty_refund"
  }
}
```

### `POST /api/connection-tests`

Runs the chat test exactly as today; then, only when the chat test succeeded and `settings.side_channel` is
given, checks the side channel with one `GET <url>/describe` carrying the configured header (`contracts/
side-channel.md`). `ConnectionTestResult` gains `side_channel_checked: bool` (default `false`):

| Outcome | `ok` | `step` | `message` (verbatim) | `side_channel_checked` |
|---------|------|--------|----------------------|------------------------|
| chat and side channel both fine | `true` | `success` | `Connection works.`, with `Side channel checked.` shown beside it | `true` |
| chat fine, no side channel configured | `true` | `success` | `Connection works.` | `false` |
| hosted, side-channel host is local/private | `false` | `side_channel_address_not_allowed` | `The side-channel address is on a local or private network. Such addresses only work when Kestrel runs on your own machine.` | `false` |
| transport error | `false` | `side_channel_unreachable` | `Kestrel couldn't connect to the side-channel URL.` | `false` |
| 401 or 403 | `false` | `side_channel_auth_rejected` | `The side channel refused the request as unauthorized. Check its auth header.` | `false` |
| no answer within the configured timeout | `false` | `side_channel_timed_out` | `The side channel didn't answer within {n} seconds.` — the API substitutes the configured `side_channel_timeout_s` (10 by default); the number is never fixed in the text | `false` |
| the stored auth header cannot be decrypted with the current key | `false` | `side_channel_header_unreadable` | `The stored side-channel auth header can't be read with the current encryption key. Re-enter it, or restore the old key.` | `false` |
| any other status, non-JSON, or a descriptor without `kestrel_side_channel: 1` and the two capabilities | `false` | `side_channel_invalid` | `The side channel answered, but not with the shape Kestrel expects.` | `false` |

The side channel is part of the settings fingerprint, so `POST /api/targets` and `PUT /api/targets/{id}` keep
answering **409 `not_tested`** until a test with exactly these side-channel settings has passed (FR-021).

### `POST /api/targets`, `PUT /api/targets/{id}`

Accept `settings.side_channel`; on PUT, a `header.value` of `null` keeps the stored value, and `side_channel: null`
removes the side channel. The header value is encrypted with the vault and never returned (FR-019).

## `GET /api/config`

```jsonc
{
  "evidence": {
    "callback_listener": true,             // set = the /callback route is mounted (FR-073); never the URL itself
    "callback_wait_s": 2.0,
    "side_channel_timeout_s": 10,
    "detectors": ["instruction_override", "unsafe_executable_output"],
    "unsafe_output_categories": ["destructive_shell", "fetch_and_execute", "destructive_sql", "script_injection"],
    "unsafe_output_pattern_set_version": "1"
  },
  "prompts": [ ..., {"id": "override_task", "version": "1"}, {"id": "callback_task", "version": "1"} ]
}
```

## `POST /api/runs`, `POST /api/runs/{id}/replay`, `POST /api/targets/{id}/replays`, experiments

Unchanged request shapes. Every run they produce carries the fields above; a replay's `planted_tokens` are the
source's copies, **with their armed state carried across** (FR-035). The experiment result and report shapes are
unchanged (FR-037).

The judge's inputs are unchanged in shape: the attack text as it was sent (which for a planted family includes the
planted paragraph, because that is what was sent), the reply, or the per-turn conversation — with any callback URL
shown as `[callback-url]` and no side-channel data of any kind (FR-049, FR-061).

## The callback listener route

`GET|POST|PUT|HEAD /callback/{token}` — see `contracts/callback-listener.md`. Mounted only when
`KESTREL_CALLBACK_BASE_URL` is set, so `evidence.callback_listener` above reports exactly whether this route exists
(FR-073). Not part of the user-facing API: no `X-Kestrel-Token` is required while it is mounted (FR-029), no JSON
body is returned (`204` or `404`, empty), and at most `CALLBACK_HITS_CAP` (100) hits are stored per run — later
requests still get `204` (FR-072).
