# Data Model: Register a Target Agent and Test the Connection

Phase 1 of [plan.md](./plan.md). Storage choices are explained in [research.md](./research.md) R5 to R7.

## Stored in SQLite

One file, default `data/kestrel.db` under the repo root (set `KESTREL_DB_PATH` to change it; a relative path is resolved against the repo root). The schema is created at start-up with `PRAGMA foreign_keys=ON` and `PRAGMA secure_delete=ON`.

### `targets`

| Column | Type | Rules |
|---|---|---|
| `id` | INTEGER PRIMARY KEY | |
| `name` | TEXT NOT NULL | Trimmed, 1 to 100 characters |
| `name_key` | TEXT NOT NULL UNIQUE | `name.casefold()`; makes display names unique ignoring letter case (FR-013) |
| `url` | TEXT NOT NULL | `http` or `https`; no user name or password and no credential-like query parameter (FR-004); for GET, contains `{{prompt}}` exactly once in the query string (FR-003) |
| `method` | TEXT NOT NULL | `CHECK (method IN ('POST', 'GET'))` |
| `body_template` | TEXT NOT NULL | POST: valid JSON with `{{prompt}}` exactly once inside a string value. GET: stored but not sent |
| `response_path` | TEXT NOT NULL | Syntax in research R4 |
| `permission_confirmed_at` | TEXT NOT NULL | ISO-8601 UTC. Set on first save, and again when a save changes the URL or accepts a newer terms version |
| `terms_version` | TEXT NOT NULL | Version of the terms accepted with the permission (FR-029) |
| `created_at`, `updated_at` | TEXT NOT NULL | ISO-8601 UTC |

### `target_headers`

| Column | Type | Rules |
|---|---|---|
| `id` | INTEGER PRIMARY KEY | |
| `target_id` | INTEGER NOT NULL | `REFERENCES targets(id) ON DELETE CASCADE`; deleting a target removes its headers (FR-019) |
| `position` | INTEGER NOT NULL | Order shown in the form |
| `name` | TEXT NOT NULL | HTTP token characters only. `Host`, `Content-Length`, `Transfer-Encoding` and `Connection` are not allowed |
| `value_encrypted` | TEXT NOT NULL | Fernet token of a value of at least 4 characters (FR-004). Never returned by the API (FR-020, FR-021) |

Unique index on `(target_id, lower(name))`: a header name appears at most once per target, ignoring case.

### `meta`

| Column | Type | Rules |
|---|---|---|
| `key` | TEXT PRIMARY KEY | |
| `value` | TEXT NOT NULL | Holds `schema_version = 1` |

## Held in memory by the API process

Nothing below survives a restart; a user re-runs Test connection after one.

### Form session (keyed by `form_id`)

| Field | Meaning |
|---|---|
| `form_id` | Random UUID made by the UI for each form instance |
| `in_flight` | True while a test for this form is running; a second test is refused (FR-009) |
| `last_success` | HMAC fingerprint of the connection settings of the most recent test, if it succeeded. Cleared when a test fails (FR-012) |
| `touched_at` | Last use; sessions expire after 60 minutes without use |

### Connection settings (part of test and save requests)

`url`, `method`, `headers` (each a `name` and a `value`, where `value: null` means "keep the stored value"), `body_template` and `response_path`.

The fingerprint is an HMAC-SHA256 over a canonical JSON form of these settings. Header names are lower-cased and sorted, and kept values are resolved first. The display name is not part of it, so renaming needs no new test (FR-012).

### Connection test result (API response, never stored)

`ok`, `step`, `message`, `detail`, `status_code`, `reply_text` (masked, at most 2,000 characters), `reply_truncated` and `duration_ms`. The steps are listed in [contracts/kestrel-api.md](./contracts/kestrel-api.md).

## State transitions

```text
unsaved form ──test succeeds──▶ tested (session holds the fingerprint)
tested ──connection settings change──▶ untested again (fingerprint no longer matches; save refused)
tested ──a later test fails──▶ untested (fingerprint cleared)
tested + permission ticked ──save──▶ saved target
saved ──select──▶ editing (header values hidden; kept unless replaced)
editing ──only the display name changes──▶ saved (no test needed)
editing ──connection settings change──▶ needs a successful test before saving;
                                        a URL change also clears the checkbox and renews the permission date
saved ──delete, then confirm──▶ removed (header rows cascade; secure_delete overwrites them)
saved with a header the current key can't decrypt ──re-enter the value, test, save──▶ saved and readable
```

## Requirement coverage

| Rule | Enforced by | Requirement |
|---|---|---|
| Required fields, URL scheme, no credentials in the URL, header names, header values of at least 4 characters, placeholder count, valid JSON | API validation before sending | FR-003, FR-004 |
| Unique display names, ignoring case | `name_key` UNIQUE | FR-013 |
| No save without the permission tick and the current terms version | API save rules | FR-011, FR-029 |
| No save of untested connection settings | Form session fingerprint | FR-012 |
| One test in flight per form | Form session `in_flight` | FR-009 |
| Targets survive restarts | SQLite file | FR-014 |
| Header values kept unless replaced | `value: null` resolves to the stored value | FR-017 |
| Header values encrypted, never returned | `value_encrypted`, API response models | FR-020, FR-021 |
| Delete removes the target and its values | `ON DELETE CASCADE`, `secure_delete` | FR-019 |
