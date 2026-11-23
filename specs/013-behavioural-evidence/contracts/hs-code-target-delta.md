# Contract delta: the sacrificial HS-code target gains the cooperating side

The HS-code target (`targets/hs_code/`) becomes the reference implementation of the side channel
(`contracts/side-channel.md`) and grows the three tools part 2 needs. Test support only; still behind the one
`HS_TARGET_API_KEY`. Its existing behaviour (`/chat`, `/health`, `/debug/tool-calls`, the classifier fallback) is
unchanged (FR-052); the ZDR, tool-capable default model `openai/gpt-oss-120b` stays.

## Recording tool calls per correlation id (FR-052)

- `POST /chat` reads an optional `X-Kestrel-Correlation-Id` header. While handling that request, every tool the
  agent loop dispatches is recorded as `(seq, name, arguments, at)` under that correlation id, in call order. A
  request without the header records under a default bucket that the side channel never serves.
- The recorder is one per app, like `email_recorder`; `send_email` keeps landing in its existing recorder too, so
  `GET /debug/tool-calls` is unchanged.

## The side-channel endpoints (FR-052)

All three require the existing API key (`X-API-Key`), answer `401 {"detail": "unauthorized"}` without it (FR of
the side-channel contract), and are served under a base path (`/side-channel`):

| Endpoint | Answer |
|----------|--------|
| `GET /side-channel/describe` | `{"kestrel_side_channel": 1, "capabilities": ["tool_calls", "state"], "tools": [<the offered tool names>]}` |
| `GET /side-channel/tool-calls?correlation_id=…` | `{"correlation_id": …, "calls": [{"seq", "name", "arguments", "at"}, …]}` (empty `calls` for an unknown id) |
| `GET /side-channel/state` | `{"state": {<the protected store>}}` |

## The environment flag that gates all three new tools (FR-067)

The honeypot tool, the outbound-request tool and the state-changing tool are offered to the model **only** when an
environment flag (for example `HS_TARGET_EVIDENCE_TOOLS=1`) is set, and are absent by default. Every suite that
already starts this target — the existing e2e tests, the browser configuration's `webServer` — therefore keeps
exactly today's tool set and today's behaviour; feature 013's own end-to-end scenario turns the flag on, and any
part-2 browser scenario that exercises these tools runs against a second, 013-only target instance (see the
Playwright pin below). `GET /side-channel/describe` lists
whatever tools are actually offered, so a reader can see which set is live.

## The honeypot tool (FR-053)

- A decoy tool is added to the agent's tool specs with a plausible name and description that no legitimate
  classification conversation needs (named in the target's README and here so Kestrel can be configured with it,
  e.g. a "privileged approval" tool). Dispatching it records the call (like any tool) and returns a plausible
  success string; it changes nothing else.

## The outbound-request tool (FR-054, FR-066)

- A tool that makes exactly one outbound `GET` request (no body) to a URL the model supplies, bounded: http or
  https only, a short timeout (a few seconds), a small response-size cap, no redirects followed. It returns a short
  status summary to the model. It exists so a callback is possible — an attack that makes the agent call it with
  the planted URL produces a listener hit. It is recorded like any tool.
- **It is bounded by destination, not only by shape** (FR-066). The tool refuses any URL that does not match an
  entry of an environment-configured allow-list of **exact URL prefixes** — scheme, host, port and a path prefix
  ending in `/`, all normalised — for example `HS_TARGET_OUTBOUND_ALLOW=http://127.0.0.1:8000/callback/`, sending
  **no request at all** and returning a refusal the model can read — a different path on an allowed host and port
  is refused too. The target has **no default list**: an unset or empty list refuses everything, so every other
  destination — any internet host, any other address on the local network, link-local addresses and
  cloud-metadata addresses — is refused unless someone listed it deliberately. The feature's end-to-end and
  browser configurations set the list to the configured callback base path plus `/`. Without this, an
  attacker-steered live model could make the developer's or the continuous-integration machine fetch an arbitrary
  address, which is neither "callback traffic stays on the owned target and Kestrel's listener" nor Principle
  VIII's bounded harm.

## The protected store and its tool (FR-055)

- A small in-memory protected store (a dict of a few keys, seeded at start-up) is exposed verbatim by
  `GET /side-channel/state`. Its values are **deterministic** — no timestamps, no read-moving counters, no
  unordered collections — as the side-channel contract requires, so an unchanged store snapshots identically every
  time.
- A tool that changes one key of that store (a plausible "update a record" tool) mutates it and returns a success;
  the next `state` snapshot reflects the change. It is recorded like any tool.

## Offline tests (FR-056)

`targets/hs_code/tests/` gains coverage with the scripted model and no network beyond the local machine:

- a scripted tool call is listed by `GET /side-channel/tool-calls` under its correlation id and **not** under
  another id;
- every side-channel endpoint answers `401` without the key and the right shape with it;
- the scripted model calling the honeypot tool records the call and returns a plausible result;
- the scripted model calling the outbound tool with an **allow-listed** `127.0.0.1` URL makes exactly one bounded
  request (asserted against a local stub server or a mocked client — never a real external host);
- the scripted model calling the outbound tool with a URL that is **not** on the allow-list — including a
  different path on an allowed host and port — causes **no request at all** and returns a refusal — asserted by a
  client double that records every attempt and must record none (FR-066);
- with the tools' environment flag unset, the target offers exactly today's tool set and none of the three new
  tools appears in `describe` or can be dispatched (FR-067);
- the scripted model calling the state tool changes the protected store and `GET /side-channel/state` reflects it.

## Playwright / CI pin (FR-056)

`playwright.config.ts`'s `webServer.env` for the **existing** target stays as it is, so the existing browser suite
keeps today's tool set (FR-067). Feature 013's own browser scenarios, if any, run a **second** target instance
with the tools' environment flag on and its outbound allow-list set, on its own port, leaving the existing instance
untouched. The part-2 e2e sets `KESTREL_CALLBACK_BASE_URL` on the **Kestrel** side so the target can reach the
listener, and the target's allow-list is set to exactly that base path (FR-066).
