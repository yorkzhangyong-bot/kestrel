# Contract: Kestrel API

The HTTP API the Streamlit UI calls. All rules live behind it; the UI only renders the results ([ui-form.md](./ui-form.md)).

- **Base URL**: `http://127.0.0.1:8000` locally; the UI reads it from `KESTREL_API_URL`.
- **Bodies**: JSON, UTF-8.
- **Header values**: never appear in any response body, error or log line.

## Error format

| Status | Body | When |
|---|---|---|
| 422 | `{"errors": [{"field": "settings.url", "message": "Enter a full http:// or https:// address."}]}` | Form problems (FR-004). Messages name the field and never repeat the submitted value |
| 404 | `{"error": {"code": "not_found", "message": "No target with id 7."}}` | Unknown target id |
| 409 | `{"error": {"code": "<code>", "field": "<field or null>", "message": "..."}}` | `test_in_progress` (FR-009), `not_tested` (FR-012), `name_taken` (FR-013, field `name`) |

## Shared shapes

**ConnectionSettings**

```json
{
  "url": "http://127.0.0.1:8001/chat",
  "method": "POST",
  "headers": [{"name": "X-API-Key", "value": "test-key-123"}],
  "body_template": "{\"message\": \"{{prompt}}\"}",
  "response_path": "$.reply"
}
```

`headers[].value`: a string sets a new value. `null` keeps the stored value of the header with the same name; this is only valid when a `target_id` or an edited target supplies one (FR-017).

**TargetSummary**

```json
{"id": 1, "name": "HS-code agent", "url": "http://127.0.0.1:8001/chat", "method": "POST",
 "permission_confirmed_at": "2026-10-23T14:05:00Z", "terms_version": "1"}
```

**TargetDetail**: TargetSummary plus `body_template`, `response_path` and `headers`. Each header is `{"name": "X-API-Key", "has_value": true, "readable": true}`. `readable` is false when the current key can't decrypt the value.

## Endpoints

### `GET /api/config`

Everything the UI needs to render the form without rules of its own.

```json
{"mode": "local",
 "defaults": {"method": "POST", "body_template": "{\"message\": \"{{prompt}}\"}", "response_path": "$.reply"},
 "terms": {"version": "1", "text": "..."}}
```

### `GET /api/targets`

200: list of TargetSummary, ordered by name.

### `GET /api/targets/{id}`

200: TargetDetail. 404 if the target doesn't exist.

### `POST /api/connection-tests`

Runs one test (FR-005 to FR-010, FR-028).

Request:

```text
{"form_id": "8f6c...", "target_id": null, "display_name": "HS-code agent", "settings": <ConnectionSettings>}
```

- `target_id` is set when testing a saved or edited target, so kept header values can be resolved.
- `display_name` is only used in the log line.

Responses:
- 200 ConnectionTestResult, for every outcome of a test that ran or was refused by the hosting guard.
- 422 if the form is invalid; nothing is sent.
- 409 `test_in_progress` if this form already has a test running.
- 404 if `target_id` is unknown.

```json
{"ok": true, "step": "success", "message": "Connection works.", "detail": null, "status_code": 200,
 "reply_text": "No HS-6 suggestion for \"Hello\": ...", "reply_truncated": false, "duration_ms": 3120}
```

| `step` | `ok` | `message` (Kestrel's wording) | `detail` (target text, plain) |
|---|---|---|---|
| `success` | true | Connection works. | null |
| `address_not_allowed` | false | This address is on a local or private network. Such addresses only work when Kestrel runs on your own machine. | null |
| `credentials_unreadable` | false | The stored auth headers can't be read with the current encryption key. Re-enter them, or restore the old key. | null |
| `unreachable` | false | Kestrel couldn't connect to this URL. | error kind, e.g. `certificate verify failed` |
| `timed_out` | false | The agent didn't answer within 60 seconds. | null |
| `auth_rejected` | false | The agent refused the request as unauthorized. Check the auth headers. | `Status 401` |
| `endpoint_error` | false | The endpoint answered with an error. | `Status 500`, `Status 302, redirect to <location>; Kestrel doesn't follow redirects, so use the final URL`, or `Response larger than 1 MB` |
| `non_json` | false | The endpoint answered, but not with JSON. | null |
| `path_not_found` | false | Response path not found in the agent's reply. | null |
| `not_text` | false | The response path points to something that isn't text. | `Found: list` |

- `reply_text` is masked (FR-023) and cut to 2,000 characters, with `reply_truncated: true` when cut.
- An empty reply is `""` with `ok: true`; the UI shows "(empty reply)".
- `detail` is masked too.

### `POST /api/targets`

Saves a new target.

```text
{"form_id": "8f6c...", "name": "HS-code agent", "settings": <ConnectionSettings>,
 "permission_confirmed": true, "terms_version": "1"}
```

| Status | Meaning |
|---|---|
| 201 | TargetDetail |
| 422 | Invalid form, `permission_confirmed` not true (field `permission_confirmed`), or `terms_version` not current (field `terms_version`) (FR-011, FR-029) |
| 409 `not_tested` | The most recent test in this form didn't succeed with exactly these settings (FR-012) |
| 409 `name_taken` | Another target has this name, ignoring case (FR-013) |

### `PUT /api/targets/{id}`

Saves an edit. Same body and errors as `POST /api/targets`, plus 404, with these rules:
- If the connection settings (after resolving kept header values) equal the stored ones, no test is needed. A name-only change is saved directly (FR-012).
- Otherwise the same `not_tested` rule as for a new target applies.
- A changed URL or a newer `terms_version` renews `permission_confirmed_at` (FR-018).

200: TargetDetail.

### `DELETE /api/targets/{id}`

Removes the target and its stored header values (FR-019). 204, or 404.
