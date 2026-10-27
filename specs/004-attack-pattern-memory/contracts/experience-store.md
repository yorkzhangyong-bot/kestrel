# Contract: ExperienceStore (ChromaDB)

`src/kestrel/experience/store.py`. Wraps one ChromaDB collection. All methods are synchronous (local disk); callers run them off the request path where needed. No method ever receives or stores a target URL, display name, or auth header value (Principle IV).

## Construction

```text
ExperienceStore(path: Path, *, embedding_function=None, store_version="1")
```

- Opens/creates `PersistentClient(path=path)` and `get_or_create_collection("kestrel_experience", embedding_function=embedding_function, metadata={"kestrel_store_version": store_version})`.
- `embedding_function=None` → ChromaDB's built-in default (local ONNX). Tests pass a deterministic stub so they stay offline (R2).
- On open, reads `collection.metadata["kestrel_store_version"]`; logs a warning if it differs from `store_version` (migration is out of scope, FR-003).

## Methods

| Method | Behaviour |
|---|---|
| `seed_patterns(library) -> int` | For each library prompt, `upsert` id `pattern:lib:<prompt_id>`, document = prompt text, metadata `{type:"pattern", family, owasp_category, source:"library:<version>", prompt_id}`. Idempotent: re-running leaves the library-derived count unchanged (FR-004, SC-002). Returns the number seeded. |
| `write_memory(*, run_id, target_id, summary, family, owasp_category, verdict, hard_evidence, turns_used, stopping_condition, attacker_model) -> None` | `upsert` id `memory:run:<run_id>`, document = `summary` (already sanitised by the caller), metadata as in data-model. Exactly one record per run (FR-006, FR-007, SC-001). Raises on store failure (caller handles — see writeback). |
| `write_pattern(*, run_id, document, family, owasp_category) -> None` | `upsert` id `pattern:run:<run_id>`, document = the winning attacker message(s), metadata `{type:"pattern", family, owasp_category, source:"run:<run_id>", origin_run_id:run_id}` (FR-009). Called only for successes (SC-003). |
| `retrieve_patterns(*, family, query_text, k) -> list[str]` | `query(query_texts=[query_text], n_results=k, where={"$and":[{"type":"pattern"},{"family":family}]})`; returns the matched documents. Family-scoped (SC-014). Semantic (FR-016/FR-017). |
| `retrieve_memory(*, target_id, family, cap) -> list[MemoryRecord]` | `get(where={"$and":[{"type":"memory"},{"target_id":target_id}]})`; sort recent-first, take `cap`, then add any `succeeded` record of the same `family` not already included (FR-016). Exact id only, never semantic (FR-017/FR-018). Never returns another target's memory (SC-006). |
| `delete_target_memory(target_id) -> int` | `delete(where={"$and":[{"type":"memory"},{"target_id":target_id}]})`. Patterns untouched (FR-024/FR-025, SC-010). Returns count deleted when available. |
| `count(type=None, *, family=None, target_id=None) -> int` | Test/diagnostic helper via `get(where=...)`. |

## Invariants

- **No secrets**: every `document` and every `metadata` value is a summary, an attacker message, an internal id, or non-secret run metadata. A target's URL/name and any auth value appear 0 times (SC-004, SC-008).
- **Memory stores only the summary**, never a raw target reply (FR-011, SC-008).
- **Idempotency**: deterministic ids (`pattern:lib:*`, `pattern:run:*`, `memory:run:*`) make seeding and write-back safe to repeat.
- **Metadata is scalar only** (`str`/`int`/`float`/`bool`); no `None`, no lists (ChromaDB constraint).
