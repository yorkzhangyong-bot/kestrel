# Implementation Plan: Behavioural Evidence (013)

**Branch**: `013-behavioural-evidence` | **Date**: 2026-11-23 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/013-behavioural-evidence/spec.md`

## Summary

Extend Kestrel's hard evidence beyond the single canary-string-in-reply check to every behaviour an attack can
actually produce, in **two parts built in order**. **Part 1** (shippable on its own) adds two deterministic
detectors over the reply text, needing nothing from the target: an **instruction-override** check built on a
per-run, two-part token the agent can only produce by obeying an instruction that claimed to supersede its own
(echo-proof: the confirming joined form appears in nothing Kestrel sends, even after normalisation), and an
**unsafe-executable-output** check built on a named, versioned standard-library pattern set whose precision is
proven by an inert positive/negative fixture tagged per pattern. **Part 2** adds an optional,
documented **side channel** a cooperating target exposes (a tool-call log read by an opaque per-run correlation
id, and a protected-state snapshot), a **honeypot tool** registered per target, and a Kestrel-hosted **canary
callback listener** that records hits on unique per-run URLs — all implemented first on the owned HS-code target.
Every deterministic check runs **before** the judge, in a fixed documented order (canary → override → unsafe
output → tool-call checks → callback → state); any hit confirms the run exactly as a canary does (verdict
`succeeded`, `hard_evidence` true, no judge call for that turn); a judge verdict alone stays **suspected**. Each
hit is recorded as its own **evidence item** (kind, turn, location, OWASP class, non-secret detail), so a run can
carry several, and the run page, the run list, the OWASP report and the structured log all present the canary, the
two detectors and the four side-channel kinds one way.

The work is **reuse, not reinvention**: one `kestrel.evidence` package owns all deterministic logic behind one
`EvidenceChecker` that `runs.py`, `attack/graph.py` and `replay.py` call where they call `match_canary` today; the
checker defaults to canary-only, so every existing path and test is unchanged except where listed (SC-008). Storage is one **additive**
schema bump (v11 — four new tables, two nullable `runs` columns, **no rebuild**), created in part 1 so a two-PR
split needs no second bump. The planting wording lives in two new versioned prompt files and three bumped attacker
prompts (009 registry); the run's exact filled task text is **stripped deterministically** and its planted values
**scrubbed** from everything written to the experience store and from the retrieval query, so the shared pattern
pool never learns a per-run token or URL (FR-063). Replay reuses the same checker, copying the source's planted
tokens so the
re-sent messages still verify (FR-035). No new dependency (Principle X).

Approach and rationale: [research.md](research.md) (D1–D25); shapes: [data-model.md](data-model.md) and
[contracts/](contracts/); validation: [quickstart.md](quickstart.md).

## Technical Context

**Language/Version**: Python 3.12 (uv-managed), unchanged.

**Primary Dependencies**: FastAPI, Streamlit, LangGraph, httpx, ChromaDB 1.5.9, markdown-it-py — all existing, all
unchanged. The detectors and the token/URL work use the **standard library only** (`re`, `secrets`, `uuid`); the
side-channel and listener use `httpx` and FastAPI, already dependencies. **No new dependency, required or
optional** (Principle X, FR-060, SC-011).

**Storage**: SQLite schema **v11**, additive (FR-057). Four new tables (`run_evidence`, `run_planted_tokens`,
`callback_hits`, `target_side_channels`) via `CREATE TABLE IF NOT EXISTS`; two nullable `runs` columns
(`correlation_id`, `side_channel_status`) in `RUNS_COLUMNS_SQL` and in a new `EVIDENCE_RUN_COLUMNS` tuple
`_migrate` ALTER-adds for an older database (the v3/v4/v7 additive pattern). **No rebuild of any existing table**,
so the v9/v10 rebuild helpers and their gotchas are untouched. ChromaDB is unchanged except that the three
functions that feed it message text (`writeback._winning_messages`, the memory summary, `retrieval.build_query`)
strip the run's exact filled task text and scrub its planted values first (FR-063).

**Testing**: pytest; unit + integration offline with stub transports/judges/side-channel/listener and a `tmp_path`
database and `chroma_path` (never the repo's), plus two `e2e` scenarios (one per part) against the HS-code target.
Tests first (Principle VII); every test cites `013/FR-###`/`013/SC-###` or a module-level `FEATURE = "013"`. The
unsafe-output positive cases live only in one inert, clearly-marked fixture (`tests/fixtures/unsafe_output_cases.json`),
never in prose (FR-059). A new `tests/unit/test_store_migration_v11.py` follows the per-version convention.

**Target Platform**: local/hosted FastAPI service + Streamlit UI (Windows 11 dev; PowerShell); the callback
listener is a route **inside** the API process (research D13), reachable at `KESTREL_CALLBACK_BASE_URL`.

**Project Type**: web service (FastAPI API) + Streamlit UI that only calls the API (FR-043), plus the sacrificial
target under `targets/hs_code/`.

**Performance Goals**: the feature adds **no model call** (SC-012); per turn it adds, at most, up to three bounded
side-channel GETs and one bounded callback wait (`KESTREL_CALLBACK_WAIT_S`, default 2 s, always additionally
capped by the run's remaining time), all inside today's time limit (FR-050). A target without a side channel in a
family without a planted task issues byte-identical requests to today's (SC-008).

**Constraints**: the override task must read as an injected override and, for indirect injection, sit inside the
seed's injected content (FR-064); deterministic checks before the judge, in the fixed order of FR-001; a hit confirms without the
judge and a judge verdict never sets hard evidence (FR-002, Principle II); the joined override form never in a
sent message (FR-009); the planted-task paragraph never in the experience store or the query (FR-063); no token,
URL, correlation id, auth value, argument value, state value or evidence detail on any log line (FR-048); the
side channel only to its configured URL through the address guard, the listener only Kestrel's own route, the
models given nothing new (FR-049).

**Scale/Scope**: single user; one side channel per target; at most one task paragraph per run (the override and
callback families are disjoint); the listener stores at most `CALLBACK_HITS_CAP` (100) hit rows per run (FR-072).

## Constitution Check

*GATE: must pass before Phase 0 and after Phase 1. Result: **PASS** — with one required, named amendment to
Principle II (a MINOR version bump), applied by the implementation PR, never the spec-only PR (FR-058). No
violation, no Complexity-Tracking entry.*

### The Principle II amendment (exact text; implementation PR only)

Principle II today reads:

> ### II. Hard evidence over opinion
>
> A finding is only "confirmed" when there is deterministic proof: a canary token in a tool
> argument or response, or a forbidden tool actually invoked.
> LLM-judge verdicts alone are "suspected".

The implementation PR replaces it with (a MINOR amendment — guidance materially expanded, nothing removed or
redefined):

> ### II. Hard evidence over opinion
>
> A finding is only "confirmed" when a deterministic check proves it, never on a judge's opinion alone.
> On every turn that receives a reply, the deterministic checks run **before** the judge, in a fixed,
> documented order, and any one of them confirming ends the run as a success with hard evidence; the judge is
> consulted only when none did, and an LLM-judge verdict alone is always "suspected". The deterministic proofs are:
>
> - a declared canary token appearing in a reply or in a tool-call argument;
> - a request arriving at a Kestrel-hosted callback for a unique URL only that run planted;
> - a forbidden tool actually invoked (a honeypot tool the target exposes but no legitimate conversation uses);
> - an instruction override the agent obeyed, shown by an echo-proof per-run token the agent can only emit by
>   following an injected instruction that claimed to supersede its own;
> - unsafe executable output in a reply, matched by a named, versioned pattern set whose every pattern documents
>   both the shape it matches and the benign shape beside it that it does not;
> - a change to protected state the agent was meant not to alter, seen through a before/after snapshot the target
>   exposes.
>
> Each confirming check is recorded as its own evidence item, so a finding may carry several, and the report names
> every one.

**Version**: `0.1.0` → `0.2.0`; **Last Amended** set to the implementation PR's date. The spec-only PR does not
touch `.specify/memory/constitution.md`.

### Gate assessment

| Principle | Assessment |
|-----------|------------|
| I — security not quality | Every new kind proves a security misbehaviour (injection obeyed, dangerous output, tool misuse, exfiltration, a side effect); no quality metric. ✓ |
| II — hard evidence over opinion | **Amended, as above** — the feature *is* the extension this principle anticipated ("a canary token in a tool argument", "a forbidden tool actually invoked"); the fixed check-before-judge order and the judge-stays-suspected rule are preserved and made explicit (FR-001, FR-002). ✓ |
| III — report states attacker model | Unchanged; the report still names the attacker model and judge/prompt versions, and now additionally lists each finding's evidence items. ✓ |
| IV — secrets never leave the vault | The side-channel header value is Fernet-encrypted like a target header, never returned/shown/logged; the judge/attacker/recommender receive no side-channel data, URL, token, correlation id or auth value; evidence details and log lines carry none of these (FR-007, FR-019, FR-048, FR-049). ✓ |
| V — learn from every run | Write-back is unchanged **except** the deliberate stripping of the planted-task text and scrubbing of the run's planted values from what the store receives (FR-063): the pool still learns every success, only without the per-run token/URL that would pollute it — an improvement to the signal, not a skipped write-back, so no Principle-V deviation to record. ✓ |
| VI — OWASP-mapped, fix-ready | Every evidence kind maps to an OWASP class (table below); the report lists items by class and gains the LLM05 coverage row. A run is counted **confirmed** under a class only when one of its own items carries that class, so a cross-class item never produces a confirmed claim with no proof for the family's class (FR-004, FR-044, FR-045). ✓ |
| VII — tests first, thin slices, one e2e | TDD per story; vertical slices (store v11 → evidence package → run wiring → API → UI → report → logging); one e2e **per part** (FR-056, SC-010). ✓ |
| VIII — only attack owned, hard caps | Side-channel reads are plain GETs to the owned target through the address guard; the listener is Kestrel's own; the sacrificial target's outbound tool can reach only an allow-listed URL prefix (scheme, host, port and a path prefix ending in `/`, `GET` only, with **no default list** — an unset/empty list refuses everything, and the e2e/browser harness sets the prefix explicitly) and its three new tools are off unless an environment flag enables them; a callback URL is planted only when its base is usable for that target; the callback route exists only when a base is configured and stores at most 100 hits per run; no model call and no raised cap (FR-049, FR-050, FR-066, FR-067, FR-068, FR-072, FR-073, SC-012, SC-015). ✓ |
| IX — simple for a vibe coder | Part 1 needs no configuration at all; the side channel is an optional form section a user fills only if they wired their agent; the API hands the UI ready-made labels, statuses and notices (FR-043). ✓ |
| X — stack fixed; new dep needs justification | No new dependency; detectors are `re`/`secrets`, the listener is a FastAPI route, the side-channel client is `httpx` (FR-060, SC-011). ✓ |

### The evidence-kind → OWASP mapping (FR-004)

| Kind | OWASP class | Why |
|------|-------------|-----|
| `canary_in_reply` | the run's own attack family's class (unchanged) | preserves today's behaviour (FR-005) |
| `instruction_override` | LLM01: Prompt Injection | an obeyed injected instruction |
| `unsafe_executable_output` | LLM05: Improper Output Handling | output a downstream component would be harmed by running |
| `canary_in_tool_argument` | LLM06: Excessive Agency | data sent through a tool; matches the library's existing `tool_exfiltration` → LLM06 mapping (`report/owasp.py`) |
| `honeypot_tool_invoked` | LLM06: Excessive Agency | a forbidden tool actually invoked |
| `canary_callback` | LLM06: Excessive Agency | an induced outbound call |
| `protected_state_changed` | LLM06: Excessive Agency | an unauthorised side effect |

## Project Structure

### Documentation (this feature)

```text
specs/013-behavioural-evidence/
├── plan.md              # this file
├── research.md          # Phase 0 — decisions D1–D25
├── data-model.md        # Phase 1 — schema v11, the evidence package shapes, the check order, API/report shapes
├── contracts/           # Phase 1 — api.md, side-channel.md, callback-listener.md, detectors.md, prompts.md,
│                         #   log-records-delta.md, hs-code-target-delta.md
├── quickstart.md        # Phase 1 — per-story validation, the migration check, the two e2e
├── checklists/requirements.md
├── spec.md
└── tasks.md             # Phase 2 — /speckit-tasks
```

### Source code (files this feature touches)

```text
src/kestrel/
├── evidence/                      # NEW package — all deterministic logic (research D1)
│   ├── __init__.py
│   ├── model.py                   # EvidenceItem, the kind table (FR-004), category_for, labels, evidence_line
│   ├── override.py                # the token, planting, reply_confirms, the disarm check, strip_planted_tasks (D4/D5/D11)
│   ├── unsafe_output.py           # the compiled pattern set + scan: every pattern carries the stable name and
│   │                              #   category the contract documents, and the module carries the set version
│   │                              #   the contract names; the expressions implement that documented boundary (D6)
│   ├── side_channel.py            # SideChannelClient, the six failure steps, check_side_channel (D7)
│   ├── callback.py                # token/URL, redact_callback_urls, wait_for_hits (D12/D14)
│   └── checker.py                 # EvidenceChecker, build_checker (D1/D2)
├── runs.py                        # execute_run gains evidence=; the single-turn check order replaces the lone match_canary
├── attack/graph.py                # _check_evidence becomes async and delegates to the checker; run_adaptive /
│                                  #   run_replay_adaptive gain evidence=; record_node writes the turn's items
├── replay.py                      # execute_replay builds a checker from the source's copied tokens (D15)
├── store.py                       # SCHEMA_VERSION "11"; the four tables; EVIDENCE_RUN_COLUMNS; the store methods
│                                  #   (data-model.md); claim_run(correlation_id=), finish_run(side_channel_status=)
├── connection/tester.py           # run_test(..., extra_headers=) for the correlation id (D8); the six side-channel
│                                  #   steps/messages added to MESSAGES
├── connection/address_guard.py    # unchanged (the side-channel client calls is_allowed as the tester does)
├── experience/writeback.py        # strip the exact filled task text and scrub planted values before _winning_messages
│                                  #   joins and before write_memory (FR-063)
├── experience/retrieval.py        # strip the exact filled task text and scrub per attacker message before build_query (FR-063)
├── judge/client.py                # judge inputs pass through redact_callback_urls (D12) — via the caller, no text here
├── report/model.py                # Finding.evidence_items; build_report(evidence_by_run=); the LLM05 coverage row;
│                                  #   confirmed-per-class counted from the items' own classes, never the family's
│                                  #   alone (FR-045); a pre-013 hard-evidence run renders one derived canary item
├── report/owasp.py                # DETECTED (the LLM05 detector row); UNTESTED drops LLM05 (six remain)
├── report/recommend.py            # recommendations_for(tokens=) redacts the winning message/evidence
├── report/render.py               # render each finding's evidence items after the winning message
├── events.py                      # CATALOGUE additions; evidence.check/side_channel_unavailable/override_disarmed,
│                                  #   callback.hit/ignored helpers (contracts/log-records-delta.md)
├── settings.py                    # KESTREL_CALLBACK_BASE_URL / _WAIT_S / SIDE_CHANNEL_TIMEOUT_S
├── prompts/override_task.v1.md, callback_task.v1.md                 # NEW task templates (wording authored here):
│                                  #   the override template is framed as the injected override itself (FR-064) and
│                                  #   keeps at least one alphanumeric word between the two token parts (FR-009)
├── attacks/data/insertion_points.json  # Kestrel-owned sidecar keyed by prompt id: each direct/indirect-injection
│                                  #   seed's insertion point as a character offset into its verbatim library text,
│                                  #   plus a sha256 fingerprint of that text (indirect points sit INSIDE the simulated
│                                  #   injected content, each with a reviewed quoting frame - frame_prefix/frame_suffix -
│                                  #   presenting the paragraph as a quoted excerpt of the content the seed names; direct
│                                  #   points at the attacker-voice position, no frame). library.json itself stays
│                                  #   verbatim (the 002 contract) (FR-064)
├── prompts/attacker_direct_injection.v2.md, attacker_indirect_injection.v2.md, attacker_tool_exfiltration.v2.md
├── prompt_registry.py             # extended for one optional `framing` front-matter key (override_task; SC-014, T015)
├── prompt_versions.lock.json      # the five new/bumped files recorded (scripts/bump_prompt.py … --lock)
├── api/schemas.py                 # the run/target/config/connection-test shapes (data-model.md); the reserved header
└── api/main.py                    # the checker at start_run; the side channel in save/update/test; the
                                   #   /callback/{token} route (mounted only when the base URL is set, exempt from
                                   #   require_token); evidence in run_detail/report/config
ui/
├── api_client.py                  # no new call shape (the existing run/target/config endpoints carry the fields)
└── app.py                         # the headline "confirmed by {labels}"; the Evidence section; the run-list column;
                                   #   the side-channel form section; the two notices; the "Callback listener: on/off" caption
targets/hs_code/
├── app.py, agent_loop.py, tools/  # per-correlation-id recording; the /side-channel endpoints; the honeypot,
│                                  #   outbound-request and state tools, all three offered only behind an
│                                  #   environment flag (off by default, FR-067); the outbound tool refuses any URL
│                                  #   not matching an allow-listed prefix (scheme/host/port + path ending in "/",
│                                  #   no default — an unset/empty list refuses everything, FR-066); a small
│                                  #   protected store, holding only deterministic values (hs-code-target-delta.md)
└── tests/                         # the offline coverage of FR-052 to FR-055, FR-066 and FR-067 (a refused URL
                                   #   sends nothing; the flag-off tool set is today's)
└── README.md                      # names the honeypot tool (FR-053), so Kestrel can be configured with it
scripts/bump_prompt.py             # bump() passes the optional framing key through (T015)
specs/009-versioned-prompts/contracts/prompt-registry.md   # the optional `framing` key documented (T015, spec-change: note)
specs/010-structured-logging/contracts/log-records.md   # the delta merged in (implementation PR, with a spec-change: note)
docs/roadmap.md, README.md, .specify/memory/constitution.md   # last PR only: Done move, status lines,
                                   #   the Principle II amendment (CLAUDE.md's 001-013 status + part-2 note also land
                                   #   in the last PR; its part-1 front-matter note and learned note land in T015/T040)
```

**Structure decision**: one new package `src/kestrel/evidence/`, beside `runs.py`, is the single home of every
deterministic check — the same split feature 012 made for `replay.py`. `attack/graph.py` keeps taking plain
callables and still never imports ChromaDB or httpx; the checker holds the side-channel client and the store, so
the graph stays unit-testable with a fake checker. The UI stays a thin client (FR-043). No new top-level package;
the listener is a route in the existing API app, not a second process (research D13).

## Part 1 / Part 2 split (FR-062)

**Part 1** is complete and shippable alone: schema v11 (whole), the `evidence` package's `model`/`override`/
`unsafe_output`/`checker` (checker in its canary + two-detector form), the run/replay/experiment wiring **with its
own tests** (the replay token copy, the disarm-on-replay rule, "any item ⇒ still vulnerable", a pre-feature source
and experiment arm parity — none of it deferred to part 2), the stripping and value scrubbing (FR-063), the
override/callback-independent API and UI (evidence items, the headline, the Evidence section, the run-list column,
the report items and the LLM05 row), the part-1 logging, the part-1 tests, a part-1 documentation task (the
technical-design evidence section and the project-memory note for what part 1 ships), and the part-1 e2e. It
touches no side-channel or callback code paths.

**Part 2** builds on it: the `side_channel`/`callback` modules, the checker's side-channel and callback branches,
the `/callback/{token}` route, the side-channel config (store table, API, form, connection test), the redaction of
callback URLs for models, the HS-code target's cooperating side, the part-2 logging, the part-2 tests and docs,
and the part-2 e2e.

The plan lets the implementation ship **as one PR or as two** (part 1, then part 2); the owner decides at the
spec-only PR. The schema is created whole in part 1 so part 2 adds no migration. The roadmap/README/constitution
edits and the log-records-contract merge are the **last** PR's work (one PR, or part 2 if split); `CLAUDE.md` is the
exception — its part-1 front-matter note (T015) and part-1 learned note (T040) land in part 1, while its 001-013
status lines and part-2 note (T067) land in the last PR.

## Complexity Tracking

No constitution violation requiring justification. The one deviation an auditor might look for — a replay or a
success not writing back fully — does not occur: the stripping of FR-063 keeps writing every success to the pool,
only without the per-run token/URL, which is an improvement to the Principle-V signal, not a skip (unlike the 007
cold arm or the 012 replay, which did skip and recorded why). No Complexity-Tracking entry.

## Phase status

- Phase 0 (research): done — `research.md` (D1–D25).
- Phase 1 (design): done — `data-model.md`, `contracts/` (seven files), `quickstart.md`; Constitution Check
  re-evaluated post-design: **PASS** with the one named Principle II amendment the implementation PR applies. No
  new dependency; the schema bump is additive (no rebuild); the experience-store stripping and value scrubbing is
  deterministic and keyed on the run's exact filled task text (FR-063); the listener is an in-process route exempt
  from the access token; every model input is redacted of callback URLs; every new log field is catalogued and
  carries only kinds/counts/statuses/steps.
- Phase 2 (tasks): `/speckit-tasks` → `tasks.md`.
