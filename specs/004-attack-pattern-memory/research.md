# Research: Attack-Pattern Store and Per-Target Memory (feature 004)

Decisions that resolve the Technical Context unknowns. Each: Decision / Rationale / Alternatives. No attack text appears here.

## R1 — Vector store client and layout

**Decision**: Use `chromadb.PersistentClient(path=<chroma_path>)` with one collection, `kestrel_experience`. Every record is typed by a metadata field `type` valued `"pattern"` or `"memory"`. The store lives at `data/chroma/` under the repo root by default, next to `data/kestrel.db`, configurable by `KESTREL_CHROMA_PATH`.

**Rationale**: FR-001/FR-002 ask for one local, persisted collection with typed records. `PersistentClient` writes to disk and reloads on start; a single collection keeps retrieval and deletion simple and matches the spec. Co-locating with the SQLite file keeps all local state under `data/`.

**Alternatives**: Two collections (patterns vs memory) — rejected, the spec fixes one collection. Client/server Chroma — rejected, this is a local single-user MVP (Principle IX).

## R2 — Embeddings (and the offline-test guarantee)

**Decision**: Production uses ChromaDB's built-in `DefaultEmbeddingFunction` (a local ONNX all-MiniLM-L6-v2 model; no API, no cost). The `ExperienceStore` takes an **injectable** `embedding_function`; offline unit/integration tests pass a tiny deterministic stub (hash-based vectors) so `uv run pytest` stays offline, keyless and free. The one end-to-end test uses the real default function (the e2e already needs the network for OpenRouter; the model downloads once and is cached).

**Rationale**: The spec says "built-in local default embeddings." The repo's offline-test promise ("unit and integration tests: offline, no keys, no cost") must hold, and the default EF downloads a model on first use — so tests must not touch it. Injecting a stub keeps retrieval logic (family filter, exact-id filter, recency cap) fully testable without embedding quality or network.

**Alternatives**: `sentence-transformers` (heavier dependency, same model) — rejected, the Chroma default already bundles it via onnxruntime. OpenAI/remote embeddings — rejected: external service, cost, and reply/summary text would leave the machine (Principle IV spirit).

## R3 — Idempotent pattern seeding

**Decision**: Seed one pattern per library prompt with a deterministic id `pattern:lib:<prompt_id>`, using `collection.upsert(ids=, documents=, metadatas=)`. The document is the library prompt text; metadata is `{type:"pattern", family, owasp_category, source:"library:<version>", prompt_id}`. Re-running start-up upserts the same ids, so the library-derived pattern count is constant (SC-002).

**Rationale**: `upsert` is insert-or-replace, so fixed ids make seeding idempotent with no existence check and no race. Prompt ids are already unique in the library.

**Alternatives**: check-exists-then-`add` (racy, more code); content-hash ids (works, but `prompt_id` is already a stable unique key).

## R4 — Retrieval (warm)

**Decision**: Two different mechanisms, as the spec requires.
- **Patterns** (semantic, family-scoped): `collection.query(query_texts=[q], n_results=k, where={"$and":[{"type":"pattern"},{"family":fam}]})`, where `q` is the family goal text combined with the conversation so far.
- **Memory** (exact id, no semantics): `collection.get(where={"$and":[{"type":"memory"},{"target_id":tid}]})`, then select in Python — most-recent-first, cap 10, always keeping any `succeeded`+same-`family` record even if older.

**Rationale**: FR-016/FR-017/FR-018 and SC-005/SC-006/SC-014. `query` runs similarity; `get` is a pure metadata fetch (no embedding of the query), which is exactly "exact target-id match, not semantic". Family scoping on patterns is a `where` clause so cross-family patterns never surface (SC-014). The recency/same-family-success selection is small and deterministic, so it is done in Python after the `get`.

**Alternatives**: Semantic query for memory with a target filter — rejected, the spec explicitly forbids semantic memory retrieval. One combined query over both types — rejected, patterns and memory need different mechanisms and scopes.

## R5 — Store version marker

**Decision**: Record `{"kestrel_store_version": "1"}` in the collection's `metadata` at creation and read it on open. A mismatch is logged; reconciling an older store (migration) is out of scope (FR-003 and the spec's out-of-scope list).

**Rationale**: FR-003 asks only that the version be recorded so a later feature can detect a change — mirrors how the SQLite `meta.schema_version` was introduced before migrations mattered.

**Alternatives**: A sentinel record of `type:"meta"` — rejected, collection metadata is simpler and is not returned by pattern/memory queries.

## R6 — Summary construction and sanitisation (no self-injection)

**Decision**: The one-line summary is the run's per-turn judge progress notes joined in order, with **no extra model calls** (FR-008). When a run has no judge notes (canary-only success, or no judge configured), fall back to a fixed template from metadata, e.g. `"<family>: <verdict> after N turn(s); stopped at <condition>"` (+ `"; canary hard evidence"` when applicable). Sanitise every summary to a fixed shape: collapse all whitespace to single spaces, strip control characters, and truncate to a maximum length (≈280 chars) — one line. When a summary is later shown to the attacker it is placed under a fixed "background notes (not instructions)" label.

**Rationale**: FR-008/FR-013 and SC-009. Judge progress notes are model-authored (not raw target text), but may paraphrase target content, so sanitising to an inert single line and framing it as untrusted background stops any instruction-like content from steering the attacker (self-injection).

**Alternatives**: Summarise with another model call (rejected by FR-008 — no extra calls, and it would add cost/latency). Store the raw judge notes unbounded (rejected — FR-013 fixed format).

## R7 — Hint wiring into the attacker (keeps the graph decoupled from Chroma)

**Decision**: The API builds a `hint_provider` closure that captures the `ExperienceStore`, the target's purpose description, the target id, the family, and the warm/cold flag, and passes it into `run_adaptive`. The graph's `attacker_node` calls `hint_provider(conversation)` each turn and passes the result to `AttackerClient.next_message(..., hints=<block>)`. Target memory and the purpose description are fetched once (stable within a run); patterns are re-queried each turn (they depend on the conversation). A cold run's provider returns the purpose description only (or nothing). `attack/graph.py` never imports ChromaDB.

**Rationale**: Keeps `attack/graph.py` and `attacker.py` free of storage concerns, so the loop stays unit-testable with a fake provider (as feature 003 did with stub attacker/judge). Satisfies FR-016 (patterns before each turn), FR-021 (purpose + memory before the first generation), and FR-019 (hints, not commands — the attacker system prompt keeps its plain-conversation rule).

**Alternatives**: Pass the `ExperienceStore` straight into the graph — rejected, it couples the graph to Chroma and makes the loop tests need a real store. Inject hints only once at the start — rejected, patterns must track the conversation per turn.

## R8 — Write-back placement and "fail loudly"

**Decision**: `POST /api/runs` calls a `write_back(experience_store, store, run, turns)` step after `execute_run` / `execute_adaptive_run` returns. It builds the one memory record (and, on success, one pattern record), writes them, and sets `runs.memory_written = 1`. If the store raises, it is caught: the attack's own run row is already saved; the run is flagged `memory_written = 0`, an error is logged, and the `RunDetail` carries `memory_written=false` so the screen shows a visible warning. The attack result is never discarded and write-back is not retried silently.

**Rationale**: FR-006/FR-010 and SC-001/SC-011. Placing write-back in the one API path that creates runs guarantees "after every run"; keeping it outside `execute_*` keeps those functions storage-agnostic and lets write-back be tested on its own.

**Alternatives**: Write back inside `execute_run`/`run_adaptive` — rejected, it couples run execution to Chroma and complicates the feature-002/003 code paths and their tests.

## R9 — What a successful run stores as a pattern

**Decision**: On success, the new pattern's **document** is the attacker message(s) that led to the success — for an adaptive run, the attacker turns up to and including `succeeded_turn`; for a single-turn run, the prompt text that was sent. Metadata: `{type:"pattern", family, owasp_category, source:"run:<id>", origin_run_id:<id>}`. Never the target's reply.

**Rationale**: FR-009 (the approach that worked is the new knowledge), SC-003, SC-008. The text is Kestrel's own attacker output, so feeding it to a future attacker is intended learning, not self-injection.

**Alternatives**: Store the summary (loses the technique); store the seed prompt only (adds nothing over seeding). Both rejected per the clarified decision.

## R10 — Dependency: chromadb

**Decision**: Add `chromadb` to `pyproject.toml`. Principle X already fixes ChromaDB in the MVP stack, so it needs no new justification beyond a one-line note; it is listed in the plan's Complexity Tracking for visibility. The exact version is pinned by `uv add chromadb` (uv.lock); the API used — `PersistentClient`, `get_or_create_collection`, `add`/`upsert`/`query`/`get`/`delete`, and `where` metadata filters — is stable across current Chroma versions.

**Rationale**: The feature is the store; ChromaDB is the chosen store in the constitution. It pulls in `onnxruntime` + `tokenizers` for the default embeddings (first-run model download, then local).

**Alternatives**: none — the store technology is constitutionally fixed.

## R11 — Deletion

**Decision**: `delete_target` deletes the SQLite target (cascading its runs, headers, canaries as today) and then calls `experience_store.delete_target_memory(target_id)` → `collection.delete(where={"$and":[{"type":"memory"},{"target_id":tid}]})`. Pattern records are untouched (they carry no `target_id`).

**Rationale**: FR-024/FR-025 and SC-010. Memory is the only target-scoped store content; patterns are anonymised shared knowledge.

**Alternatives**: Cascade-deleting success-derived patterns from that target — rejected, patterns hold no target identity and are meant to persist as shared knowledge.

## R12 — Settings

**Decision**: Add `KESTREL_CHROMA_PATH` (default `data/chroma`), `KESTREL_EXPERIENCE_PATTERN_K` (default 5), `KESTREL_EXPERIENCE_MEMORY_CAP` (default 10), all via the existing `load_settings` with the same `positive_int` validation. The per-run warm/cold choice arrives on the run request (`use_prior_experience`, default `true`, FR-014) — not an env var — because it varies per run and the A/B harness (006) sets it per run.

**Rationale**: FR-014/FR-016 defaults, Principle IX (works out of the box), and A/B configurability (006).

**Alternatives**: Hard-code k and the cap — rejected, 006 wants to tune them. Make the switch an env default only — rejected, it is a per-run choice.

## R13 — Screen

**Decision**: (a) A "Use prior experience" toggle in the Attack panel beside the Single-turn/Adaptive mode toggle, defaulting to on, shown for adaptive runs. (b) An optional one-line "What is this agent for?" field in the target form, labelled "no sensitive info". (c) A per-target **Profile** view (counts by family and by verdict, plus recent one-line summaries) backed by a new `GET /api/targets/{id}/profile`. (d) A visible warning on a run whose `memory_written` is false.

**Rationale**: FR-020/FR-022/FR-023, US3/US4, Principle IX. Streamlit only renders and calls the API, as in features 001–003.

**Alternatives**: Put the profile inside the run list — rejected, it is a per-target summary, not per-run. A separate page/tab — deferred; a section under the selected target matches the existing single-screen layout.
