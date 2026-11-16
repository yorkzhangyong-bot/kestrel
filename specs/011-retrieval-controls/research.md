# Phase 0 Research: Retrieval Controls for the Experience Store (011)

All decisions respect Principle X (no new required dependency: ChromaDB's own distances and the standard library)
and the clarifications recorded in `spec.md` (session 2026-11-16: the feature-010 unusable-store path on a model
mismatch; both controls on by default with values pinned here; same-family merge targets, library seeds eligible;
hit count recorded only; the last two attacker messages in the query; offline proof on a lexical embedding).

Code facts this builds on (verified in the worktree, ChromaDB 1.5.9):

- Two copies of the retrieval query exist today and both include target replies: `api/main.py::start_run.hint_provider`
  builds `family_label(family) + _recent_conversation(conversation)` (the last 2 turns = up to 4 messages of both
  roles), and `experiments/engine.py::_hint_provider` joins `conversation[-4:]` (both roles). The conversation the
  graph hands to the provider is a list of `(role, masked text)` with roles `attacker` and `agent`
  (`attack/graph.py::record_node`). Judge reason and progress text never reach the provider today (they live in the
  graph state and the turn rows), but nothing structural prevents it; the one shared builder of D1 makes the
  exclusion structural.
- The collection is created today with no configuration and the default embedding function (persisted in the
  collection configuration as `{"name": "default", "config": {}}` — a name that says nothing about the model). Its
  metadata holds only `kestrel_store_version`. `collection.modify(metadata=...)` replaces the whole metadata dict,
  so a stamp must carry every key along. `DefaultEmbeddingFunction` (`chromadb/api/types.py`) does not subclass
  `ONNXMiniLM_L6_V2`: it **delegates every call** to a fresh `ONNXMiniLM_L6_V2()` (whose `MODEL_NAME` is
  `all-MiniLM-L6-v2`), while its own registered `name()` is `default` and its `default_space()` is the base class's
  `l2` — `ONNXMiniLM_L6_V2.default_space()` is `cosine`. The ONNX function L2-normalises its vectors, so under `l2`
  the collection's distance is the squared Euclidean distance `2 − 2·cos` in `[0, 4]`; under `cosine` the same
  vectors would read `1 − cos`, half as much. Probe of 2026-11-16 (round 2): `DefaultEmbeddingFunction()` and
  `ONNXMiniLM_L6_V2()` embed a neutral probe identically (squared distance 0.0).
- **How a collection gets its space** (`chromadb/api/collection_configuration.py`): with no `hnsw`/`spann`
  configuration and no `hnsw:space` metadata, the space is the embedding function's `default_space()` — `l2` for the
  default function (so every feature-004 store is `l2`), `cosine` for a collection someone creates with
  `ONNXMiniLM_L6_V2` directly. An explicit `configuration={"hnsw": {"space": "l2"}}` is honoured at creation; on a
  **reopen a conflicting configuration is silently ignored** (a cosine configuration against an `l2` collection
  raises nothing and the collection stays `l2`), so the actual space must be read back from
  `collection.configuration_json["hnsw"]["space"]` rather than assumed (probe round 2).
- `collection.query(..., include=["documents", "metadatas", "distances", "embeddings"])` returns the hits' own
  embeddings (one `ndarray` per hit) and their distances; the reported distance equals the squared Euclidean
  distance computed with the standard library to four decimals (probe of 2026-11-16).
- `collection.update(ids, metadatas)` **merges** metadata keys (a record updated with `{"hit_count": 2}` keeps
  `type` and `family`), and `upsert` with a metadata dict that omits a key keeps the stored value of that key. So
  re-seeding the library each start-up does not erase a hit count as long as the seed metadata omits the key for
  ids that already exist; a key that *is* present in an upsert overwrites.
- ChromaDB itself refuses to open a collection with an embedding function of a different registered **name**
  (`Embedding function conflict: new: … vs persisted: …` — its text has no "not found", so `store_error_kind`
  classifies it as `other`) and fails with `Embedding function … not found` when the persisted name is unknown to
  the process (classified `embedding_function_mismatch`). Neither check sees the **model** behind the name. Two
  gaps follow: a store built by one model and opened under a function of the same registered name but another
  model would pass silently — that is the gap FR-009 to FR-011 close by recording and comparing the model name;
  and a change *inside* the default function (ChromaDB delegating `DefaultEmbeddingFunction` to another model while
  the derived name stays `all-MiniLM-L6-v2`) would pass the name check too — that case is caught by the FR-018
  probe, which asserts that `DefaultEmbeddingFunction()` and `ONNXMiniLM_L6_V2()` embed identically (D5, D10). No
  requirement classifies the conflict error further.
- Chroma warns on its own logger when `n_results` exceeds the index size (not part of Kestrel's stream, but noisy);
  `count("pattern", family=…)` already exists (a filtered `get` with `include=[]`), so a candidate pool can be
  clamped before querying.
- The write-back is `experience/writeback.py::write_back(experience, store, run, turns)`, called from
  `api/main.py::start_run` and `experiments/engine.py::_run_rep` inside the run scope; the pattern document is the
  joined attacker messages up to the succeeded turn (adaptive) or the seed text (single-turn), so a single-turn
  success replays its library seed verbatim (distance 0 to `pattern:lib:<id>`).
- The test stub `tests/support.py::StubEmbeddingFunction` hashes characters by position (`vector[i % 32] += …`):
  deterministic, but an inserted character shifts every later one into another slot, so it does not preserve
  lexical similarity and its distances are unbounded. Four test doubles implement the store surface:
  `_Experience` in `tests/unit/test_experiment_engine.py` and `test_experiment_warming.py` (`write_memory`,
  `write_pattern`, `retrieve_memory`, `retrieve_patterns`), `FailingExperience` in
  `tests/integration/test_writeback.py` (raising writes) and `SpyExperience` in `test_report_safety.py` (a real
  store subclass counting writes).
- `GET /api/config` already reports the retrieval bounds (`experience.pattern_k`, `memory_cap`) through
  `schemas.ExperienceOut`; the UI does not render them.
- Events: `events.CATALOGUE` is the allow-list; `memory.retrieval` carries `warm`, `pattern_count`, `memory_count`,
  `pattern_ids`; `memory.writeback` carries `written`, `pattern_written`, `error`; `experience.unavailable` carries
  `reason_kind`. A field outside the catalogue is dropped with a `log.unknown_field` warning, so every new field is
  a catalogue entry and a row in `specs/010-structured-logging/contracts/log-records.md`.
- Real-model distances, measured on the cached `all-MiniLM-L6-v2` (probe of 2026-11-16, round 1, and the round-2
  re-run of the same day after the spec review; ids and numbers only, never a prompt text). Every number that
  depends only on the library and the model was reproduced exactly by the re-run; the numbers that depend on a
  free neutral sentence are given for both sentence sets. Neutral sentence pairs: a whitespace-only edit
  0.000–0.023 (depending on the edit), a spelling change 0.004, one word changed 0.088, a paraphrase 0.253, a
  related sentence on another topic 0.978 (round 1) / 1.270 (re-run), an unrelated sentence 2.153 (round 1) /
  2.005 (re-run). Over the shipped library (16 prompts, 4 per family): same-family seeds are 0.543–1.755 apart
  (family medians 1.29–1.56); the turn-2 query as FR-001 defines it (family label + seed) lies 0.148–0.519 from its
  own seed and 0.670–1.456 from the nearest other seed of the family (medians 0.99–1.30); a turn-3 query (label +
  seed + one neutral follow-up) lies 0.20–0.83 from its own seed (the longer the follow-up, the farther: 0.20–0.52
  with the short round-1 follow-ups, 0.30–0.83 with the longer re-run ones) and 0.76–1.47 from the nearest other.
  The nearest other-family seed sits 0.88–1.18 from a family's seeds (retrieval is family-scoped, so this is
  informational).
- **Round 2 (2026-11-16, review finding 3; re-run and recorded by the spec-fix pass): queries that no longer
  contain the seed** — from turn 4 the window holds two attacker messages and the seed has left it (turn cap 6,
  `settings.DEFAULT_ADAPTIVE_MAX_TURNS`). Stand-ins, since no attack text may be fabricated: "on-theme" = the
  family label + two *other* seeds of the family in both orders (12 queries per family), measured against the
  remaining two seeds (the two stand-ins are excluded, as real turn-4 messages are not in the store); "mixed" = the
  label + one other seed + one of three neutral follow-up sentences (12 queries per family, measured against the
  other three seeds); "two neutral" = the label + two of the three neutral follow-ups in both orders (6 queries per
  family, against all four seeds); "label only" = the label alone. The neutral follow-ups are ordinary
  conversational sentences about the HS-code target's domain (thanks, a request to walk through a tableware
  classification, a request to summarise shipping rules, a request for a comparable example). Distance to the
  nearest family seed in the store (min / median / max):

  | family | on-theme | mixed | two neutral | label only |
  |--------|----------|-------|-------------|------------|
  | direct_injection | 1.076 / 1.237 / 1.398 | 1.069 / 1.250 / 1.408 | 1.445 / 1.474 / 1.536 | 1.606 |
  | system_prompt_leak | 0.779 / 1.009 / 1.261 | 0.763 / 1.022 / 1.297 | 1.367 / 1.384 / 1.432 | 1.318 |
  | tool_exfiltration | 1.226 / 1.327 / 1.428 | 1.233 / 1.386 / 1.471 | 1.473 / 1.564 / 1.714 | 1.573 |
  | indirect_injection | 0.991 / 1.276 / 1.740 | 0.945 / 1.211 / 1.395 | 1.578 / 1.656 / 1.732 | 1.561 |

  (The first round-2 pass, with shorter neutral follow-ups, measured the same on-theme maxima and label-only
  values, and lower "two neutral" drift — up to 1.548; the re-run's longer follow-ups drift farther, up to 1.732,
  and are the numbers the floor is pinned on.) Margin of each candidate floor over the worst measured seedless
  query (1.740, an on-theme `indirect_injection` query): 1.5 → −0.24, 1.6 → −0.14, 1.7 → −0.04, **1.8 → +0.06**,
  2.0 → +0.26; the unrelated sentences (2.005 and 2.153) stay beyond every candidate up to 2.0. At the first-round
  floor of 1.5 a seedless on-theme query would sometimes admit nothing (worst case 1.740) and so would neutral
  drift (up to 1.732); at 1.8 every measured seedless query — on-theme, mixed, two-neutral and even the bare label —
  still admits at least one family seed, while unrelated text and near-orthogonal success documents stay beyond
  it. The floor is therefore pinned at **1.8**, the smallest round value with a margin over the worst measured
  case (D6). It is a measured default, not a guarantee: the stand-ins approximate real attacker messages, and a
  real seedless query — especially in `indirect_injection` or `tool_exfiltration`, whose seeds sit farthest apart —
  may still select nothing, which FR-003 allows and which is visible on `memory.retrieval` as `pattern_count` 0 with
  a non-zero `dropped_floor`; what 1.8 reliably does is drop near-unrelated text (2.0 and beyond). An operator
  retunes the floor from the `distances` and `dropped_floor` the retrieval lines log (the `.env.example` note of
  T001 says so).
- **Round 2, the write-back threshold at 0.15 on the real model** (the three sentences the end-to-end run writes,
  D10; reproduced exactly by the re-run): the one-word variant of a neutral document is 0.088 away (merged, margin
  0.06 below 0.15) and its paraphrase 0.253 (added, margin 0.10 above); the nearest shipped `system_prompt_leak`
  seed to that neutral document is 1.641 away, so the e2e's first write-back is `added` and never merges into a
  seed. The re-run also confirmed `DefaultEmbeddingFunction()` and `ONNXMiniLM_L6_V2()` embed a neutral probe
  identically (squared distance 0.000000) and that their `default_space()` values are `l2` and `cosine` (D5, D13).
  The recall fixture's vocabulary (21 words) has no bucket collision under `crc32 % 256` (and four collisions
  under `% 64`, the old dimension); its exact stub distances are published in `contracts/recall-fixture.md` (D8).

---

## D1 — One retrieval path: `experience/retrieval.py` builds the query and the hints for both callers

- **Decision**: a new module `src/kestrel/experience/retrieval.py` owns the query rule and the selection, and exposes
  one factory `background_provider(experience, *, target_id, purpose, family, settings, use_prior_experience)` that
  returns the per-turn callable the graph already accepts (`hint_provider(conversation)`). Both
  `api/main.py::start_run` and `experiments/engine.py::_run_rep` call the factory; their private providers and
  `main._recent_conversation` are deleted. `build_query(family, conversation)` keeps only the `attacker`-role
  messages, takes the last `QUERY_MESSAGES = 2`, and returns `(f"{family_label(family)} {' '.join(messages)}",
  count)`. Memory retrieval (`retrieve_memory`, exact target id) is unchanged and runs in the same provider.
- **Rationale**: FR-002 asks that the two paths cannot drift apart; one function is the structural guarantee, and
  the known-marker test (FR-002, SC-001) then proves the exclusion for both callers through the same code. Filtering
  by role is the only reliable exclusion: the judge's reason and progress never enter the conversation list, and the
  `agent` role is exactly the target's masked reply.
- **Alternatives considered**: keep two providers and test each (drift risk, the defect this feature fixes);
  filter replies by content (impossible — a reply is arbitrary text); put the query rule on the store (the store
  should not know about conversations or roles).

## D2 — Candidates from the collection, selection in Kestrel with the collection's own measure

- **Decision**: `ExperienceStore.query_patterns(*, family, query_text, n) -> list[Candidate]` runs one
  family-scoped `query` with `include=["documents", "distances", "embeddings"]` and returns
  `Candidate(id, document, distance, embedding)` nearest first (`Candidate` is defined in `store.py`, beside the
  method that builds it, and imported by `retrieval.py`); `n` is clamped to the family's pattern count (an
  empty family returns `[]` without querying). The pure function `select_patterns(candidates, *, k,
  distance_floor, dedupe_threshold) -> Selection` walks the candidates nearest first: a candidate beyond the floor
  is dropped (and, because the list is sorted, every later candidate is too — they are all counted as dropped and
  the walk ends); otherwise a candidate whose squared Euclidean distance to any already selected hit is at or below
  the threshold is skipped; otherwise it is selected; the walk ends when k hits are selected. The pairwise distance
  is `sum((a−b)²)` over the two stored embeddings — the collection's own `l2` measure, computed with the standard
  library (verified equal to the collection's reported distances). The pool is `min(k × CANDIDATE_MULTIPLIER,
  family count)` with `CANDIDATE_MULTIPLIER = 4`, so up to 3k near-duplicates can be skipped before the selection
  starves. `Selection` carries `selected`, `candidate_count` (the candidates examined, so that
  `candidate_count == dropped_floor + dropped_duplicate + len(selected)` always holds), `dropped_floor`,
  `dropped_duplicate`, and the derived `pattern_ids`, `documents`, `distances`.
- **Rationale**: FR-003 to FR-005 need the query distance (reported by the collection) and the hit-to-hit distance
  (not reported by a single query); the stored embeddings and the same formula give the latter without a second
  query per hit and without any similarity library (Principle X). Stopping at the first far candidate is exact
  because the collection returns candidates in distance order. The count identity is what FR-013 and SC-007 assert.
- **Alternatives considered**: one extra `query(query_embeddings=[hit])` per selected hit to read hit-to-hit
  distances from the collection (k extra local queries per turn; same numbers); using the query distance as a proxy
  for duplication (two hits equidistant from the query need not be alike); a cosine space (would change the stored
  index and every number — the collection stays `l2`).

## D3 — Write-back merges into the nearest same-family pattern within the threshold

- **Decision**: `ExperienceStore.write_pattern(*, run_id, document, family, owasp_category, dedupe_threshold=None)
  -> PatternWrite`. With a threshold and a non-empty family it first runs a family-scoped `query` for the single
  nearest pattern (`include=["metadatas", "distances"]`); when `distance <= dedupe_threshold` it calls
  `update(ids=[id], metadatas=[{"hit_count": previous + 1, "last_hit_run_id": run_id}])` (merge semantics keep
  the other keys) and returns `PatternWrite("merged", id, previous + 1, distance)`; otherwise it upserts
  `pattern:run:<run_id>` with the feature-004 metadata plus `hit_count: 1` and returns
  `PatternWrite("added", id, 1, distance_or_None)`. A missing `hit_count` on the nearest pattern reads as 1
  (FR-007). `write_back(experience, store, run, turns, *, dedupe_threshold=None)` passes the setting through from
  both callers and puts the outcome on the `memory.writeback` line; `pattern_written` keeps its meaning ("the
  success was recorded as a pattern" — added or merged) so feature-010 assertions hold.
- **Rationale**: the nearest-within-threshold rule is the clarified answer (same family, library seeds eligible,
  nearest wins); one query of one result is the cheapest honest implementation; the merged pattern's text stays
  the text that originally won (the document is never rewritten). The threshold is the same number retrieval uses,
  so "near-identical" means one thing (spec assumption). This amends feature 004's "every success is written; no
  de-duplication" clause on purpose (the spec's Requirements intro lists the four amended 004 statements), and the
  one existing test whose single-turn success replays its library seed verbatim —
  `tests/integration/test_delete_clears_memory.py`, which asserted a new pattern — is updated to assert the merge
  (the seed's hit count rises, no pattern is added, patterns still survive deletion; task T025).
- **Alternatives considered**: a separate write-back threshold (two knobs for one notion); rewriting the merged
  document to the latest winning text (would re-embed and move the pattern); merging across families (rejected by
  the clarification).

## D4 — Hit counts: `hit_count` and `last_hit_run_id` in pattern metadata, preserved across re-seeding

- **Decision**: a pattern's metadata gains `hit_count` (int, 1 when added) and, when merged into, `last_hit_run_id`
  (int). `seed_patterns` first reads which seed ids already exist (`get(ids=…, include=[])`) and upserts new ids
  with `hit_count: 1` and existing ids **without** the key, so the idempotent re-seed at every start-up refreshes
  the text and feature-004 metadata but never resets a count (upsert keeps an omitted key). A pattern that still
  lacks the key (written before this feature and never merged into) reads as 1 wherever the count is used.
- **Rationale**: FR-007 and SC-004; the merge semantics of `update`/`upsert` are verified, and omitting the key for
  existing ids is the only way an idempotent upsert can coexist with a counter. No ranking change (clarified).
- **Alternatives considered**: a one-off migration stamping `hit_count: 1` on every existing pattern (more writes
  at start-up for the same reads); counting hits in SQLite (splits one record over two stores).

## D5 — The embedding model name: derived from the embedding function, stamped, checked in `self_check`

- **Decision**: `experience/store.py` gains `EMBEDDING_MODEL_KEY = "kestrel_embedding_model"` and
  `embedding_model_name(embedding_function) -> str`: `None` (the shipped default, which delegates every call to
  `ONNXMiniLM_L6_V2()`) maps to `ONNXMiniLM_L6_V2.MODEL_NAME` (`all-MiniLM-L6-v2`); any other function reports
  `MODEL_NAME` when it has one, else its registered `name()`. The constructor accepts `embedding_model: str | None =
  None` (the name to compare with; derived when `None` — the test seam for a "different model"). On open: a
  collection with the key records it as `stored_embedding_model`; one lacking it or the distance-space key of D13
  is stamped — only when the actual index space is `l2` — with `collection.modify(metadata={… version key …,
  EMBEDDING_MODEL_KEY: <the stored name when present, else expected>, DISTANCE_SPACE_KEY: "l2"})`, and one
  constant `message` line says so ("Recorded the embedding model name and distance space on the experience
  store."). A stored name is never overwritten by the expected one, so a store missing only the space key keeps its
  name and still fails `self_check` on a model mismatch; a non-`l2` store is never stamped and never logs the stamp
  line — `self_check` fails it (review round 2, item E). `self_check()` compares the
  space (D13), then the model name, and raises `EmbeddingModelMismatch(ExperienceStoreError)` carrying `stored`
  and `expected` and a human-readable message, then runs the existing probe embed. `store_error_kind` returns
  `embedding_model_mismatch` for that class. `api/main.py` keeps its single `experience.unavailable` emission but,
  for a mismatch, emits the **mismatch-specific constant message** of `contracts/log-records-delta.md` (it states
  the remedy: rebuild the store directory, or run Kestrel with the model that built it) with `stored_model` and
  `expected_model` as fields; the store is set to `None` for the session exactly as for the other causes, so
  seeding, retrieval and write-back follow the feature-010 path (runs record `memory_written` false, loudly).
- **Rationale**: FR-009 to FR-011 and the clarified failure mode. Deriving the name from the function in use keeps
  the check honest for the shipped default and for the test stub alike; the constructor override lets a test
  simulate a changed model without fighting ChromaDB's own name check (which fires first when the registered name
  differs). Comparing in `self_check` keeps the constructor side-effect free apart from the stamp, and `main.py`
  already wraps both calls in the one handler. Model names are not secrets (`010/FR-009` allows identifiers), so
  the line may carry them. The remedy reaches the operator on the line itself because a line's `message` is
  constant text (as `key.mismatch` already does) — the exception's own text is still rendered as `exc_type` and
  `stack` only (review finding 1). Because the shipped function only delegates, the end-to-end run asserts that
  `DefaultEmbeddingFunction()` and `ONNXMiniLM_L6_V2()` embed a neutral probe identically, so a silent change of
  what the default delegates to is caught (review finding 8).
- **Alternatives considered**: comparing in the constructor (then a failed open would skip the stamp path and the
  version warning); hard-coding the expected name as a constant (would silently drift from the library's model);
  switching the shipped function to an explicit `ONNXMiniLM_L6_V2` (changes the persisted function name and would
  make every existing store fail ChromaDB's own name check).

## D6 — Settings: two non-negative floats with an `off` value, on by default

- **Decision**: `KESTREL_EXPERIENCE_DISTANCE_FLOOR` (default `1.8`) and `KESTREL_EXPERIENCE_DEDUPE_THRESHOLD`
  (default `0.15`), each parsed by a `non_negative_float_or_off(name, default)` helper: unset → the default; the
  literal `off` (case-insensitive) → `None` (control switched off); any other value must parse as a non-negative
  float, else `SettingsError`. `Settings` gains `experience_distance_floor: float | None` and
  `experience_dedupe_threshold: float | None`, plus the frozen dataclass `RetrievalSettings(k, distance_floor,
  dedupe_threshold)` in `settings.py` and a `Settings.retrieval` property that builds it (the one value the
  retrieval path reads); `GET /api/config` reports both beside `pattern_k` and `memory_cap` (`ExperienceOut`,
  `number | null`); `.env.example` documents the two lines, the `off` value and the note that a different embedding
  model needs retuned values. The attacker-message window (2) and the candidate multiplier (4) are module
  constants, not settings.
- **Rationale**: FR-012 and the clarified defaults. The values come from the measurements above, rounds 1 and 2. A
  floor of `1.8` (cosine ≥ 0.10): the first-round value of 1.5 was measured only on queries that still contained
  the seed (turn 2 and 3); from turn 4 the seed leaves the window, and the round-2 table shows seedless on-theme
  queries up to 1.740 and neutral drift up to 1.732 from the nearest family seed — 1.5 (and 1.6, 1.7) would then
  sometimes admit nothing, dropping the family's own techniques. At 1.8 every measured seedless query (worst 1.740)
  still admits at least one family seed, while unrelated text (2.005–2.153) and near-orthogonal success documents
  stay dropped; 1.8 is the smallest round value with a margin (0.06) over the worst measured case, and the
  end-to-end run confirms it on a seedless query (D10). A threshold of `0.15` (cosine ≥ 0.925) merges whitespace, spelling and one-word variants
  (0.004–0.088) and keeps a paraphrase (0.253) and a seed-plus-another-message document (0.2–0.5) as distinct
  approaches; no two shipped seeds of one family are within it (minimum 0.543); the end-to-end run confirms both
  outcomes (merged at 0.088, added at 0.253) on the real model (D10, FR-018).
- **Alternatives considered**: `0` as the off value (would mean "exact matches only", not off); defaults off (the
  clarification chose on); exposing the window and the multiplier as settings (two more knobs with no user need —
  Principle IX).

## D7 — Log fields: extend the three existing events, nothing new on the stream

- **Decision**: `memory.retrieval` gains `k` (int), `distance_floor` and `dedupe_threshold` (number | null when
  off), `candidate_count`, `dropped_floor`, `dropped_duplicate` (ints; the identity of D2 holds), `distances` (list
  of numbers, the selected hits' query distances rounded to 4 decimals, in selection order) and `query_messages`
  (int, attacker messages in the query); `pattern_count` stays the number selected and `warm` stays
  `pattern_count > 0`. `memory.writeback` gains, on a success only, `pattern_outcome` (`added` | `merged`),
  `pattern_id`, `hit_count` (int) and `pattern_distance` (number | null: the distance to the nearest existing
  same-family pattern, null when the family had none or de-duplication is off). `experience.unavailable` gains
  `stored_model` and `expected_model` (only on a model mismatch), `stored_space` and `expected_space` (only on a
  space mismatch, D13), the reason kinds `embedding_model_mismatch` and `space_mismatch`, and — for those two
  kinds — a mismatch-specific constant `message` that states the remedy (the generic constant stays for every
  other cause). `events.memory_retrieval(...)` and `events.memory_writeback(...)` take the new keyword arguments;
  the catalogue and `specs/010-structured-logging/contracts/log-records.md` gain the fields (the implementation PR
  carries a `spec-change:` note for that contract edit). No text field anywhere: the query, the documents and the
  messages stay off the stream (`010/FR-009`).
- **Rationale**: FR-013, SC-007 and the owner's wording ("retrieval settings are logged in the 010 memory.retrieval
  event"); the write-back outcome belongs on the line that already reports the write-back; the model names belong
  on the failure line that already names the cause. Numbers and identifiers only.
- **Alternatives considered**: a new `memory.selection` event (splits one retrieval over two lines); logging the
  pool size (derivable: `k × 4` clamped — the examined count is what the identity needs).

## D8 — Offline proof: a lexical, normalised stub embedding; the recall@k fixture states its own thresholds

- **Decision**: `tests/support.py::StubEmbeddingFunction` is re-implemented as a hashed bag of words: lower-case
  alphanumeric tokens, each hashed with `zlib.crc32` (stable across processes, unlike `hash()`) into `dim = 256`
  buckets (64 risked bucket collisions between unrelated words; 256 keeps the fixture's vocabulary collision-free,
  review finding 5), counted, then L2-normalised — so identical texts are at distance 0, texts sharing no token
  (and no bucket) at 2.0, and an edit of one token in a six-token text of distinct words at `2 − 2·5/6 ≈ 0.333`.
  Its registered `name()` (`kestrel_stub`), `get_config`
  and `build_from_config` are unchanged; it gains `MODEL_NAME = "kestrel-lexical-stub"`. Every offline test keeps
  using it (the `make_client` fixture included); the retrieval tests, the write-back tests and the fixture state the
  floor and threshold they need (the fixture: `k = 3`, floor `0.8`, threshold `0.5`, minimum recall 1.0 — values
  chosen so that every published fixture distance lies at least 0.1, in fact at least 0.2, from both) rather than
  relying on the shipped defaults. The fixture lives at `tests/fixtures/retrieval_recall.json` (schema in
  `contracts/recall-fixture.md`) with neutral placeholder sentences built from tokens like "placeholder approach
  alpha step one" — never attack wording — and is loaded into a fresh temporary store through `seed_patterns` with
  a duck-typed library (`version`, `prompts` with `id`, `text`, `family`, `owasp_category`), so the fixture goes
  through the same seeding path as the real library.
- **Rationale**: the clarified answer asks for a deterministic offline embedding that preserves lexical similarity
  with fixture-specific thresholds; a normalised bag of words puts the stub's distances in the same `[0, 2]` range
  as the real model's `[0, 4]`, so the shipped defaults also remain meaningful in the integration suite (a
  placeholder seed and its family label share most tokens with the turn-2 query). Existing tests assert on
  presence and scoping, not on the old character-hash order, so the swap itself changes no expectation; the one
  expectation this feature changes is the deletion test's merge (D3, T025), which the shipped threshold causes on
  any embedding, because the single-turn success replays its seed verbatim (distance 0). The fixture's published
  distances (`contracts/recall-fixture.md`) all lie at least 0.1 from the fixture's floor and threshold, and the
  check asserts those margins (SC-009, review finding 5).
- **Alternatives considered**: a second stub beside the old one (two scales in one suite, the app fixture keeping
  meaningless distances under the shipped floor); running the fixture on the real model in CI (needs the 80 MB model
  download — the end-to-end run already covers the real model once); a hand-written vector table (fragile).

## D9 — The known-marker proof and the test doubles

- **Decision**: a spy store (a `StubEmbeddingFunction`-backed `ExperienceStore` subclass recording every
  `query_patterns` and `write_pattern` call) is injected through `make_client(experience=…)` for the API path and
  through `create_app`'s store for the experiment path; the stub target replies with `REPLY_TEXT`, the stub judge's
  reason and progress carry `JUDGE_REASON`/`JUDGE_PROGRESS` (the known strings `tests/support.py` already defines),
  the attacker replies with its placeholder messages, and the target's purpose description carries `PURPOSE_TEXT`;
  the test drives **two** warm runs against the one target, so that on the second run the target's memory holds a
  summary built from the first run's judge progress (`writeback.py` builds summaries from those notes) — the
  realistic path by which judge text could reach a query — and asserts the markers (reply, judge reason, judge
  progress, purpose, auth value, URL, name) appear zero times in any recorded query of either run, while the family
  label and the last attacker messages do (FR-002, SC-001). The accepted residual — an attacker message may echo a
  reply fragment — is named in the spec and not asserted away. The four doubles gain what
  the new path calls: `_Experience` gets `query_patterns(**kw) -> []` and `write_pattern` returning a
  `PatternWrite("added", "pattern:run:0", 1, None)`; `FailingExperience` and `SpyExperience` need no change beyond
  the new keyword.
- **Rationale**: FR-002 demands a proof over the real request path, not a unit test of `build_query` alone; the
  known strings already exist for the feature-010 redaction tests.

## D10 — The end-to-end scenario

- **Decision**: `tests/e2e/test_us011_retrieval.py` (marker `e2e`) runs the API in-process like
  `tests/e2e/test_us2_experience.py` — real HS-code target subprocess, real judge and attacker, the real default
  embedding, `chroma_path` under `tmp_path`, `adaptive_max_turns=4`, `adaptive_time_limit_s=120` as
  `tests/e2e/test_us2_experience.py` sets it, so four real turns fit — drives two warm adaptive runs of the
  `system_prompt_leak` family (the family with the smallest seedless distances in the round-2 table) against one
  target, reads the kept lines of every run (the first run is warm on the library seeds too) through
  `GET /api/runs/{id}/log`, and asserts, in this order: at least one `memory.retrieval` line exists (a run that
  ends on turn 1 fails loudly instead of passing vacuously — review finding 7); every such line carries `k`,
  `distance_floor = 1.8`, `dedupe_threshold = 0.15`, the three counts adding up to `candidate_count`, and
  `pattern_count >= 1` with every distance `<= 1.8`; at least one line with `query_messages == 2` on turn 4 — a
  query without the seed — has `pattern_count >= 1`. A run ends before turn 4 on any stopping condition
  (`succeeded`, `attacker_failed`, `send_failed`, `token_budget`, `time_limit`) and then never issues a seedless
  query, so while no run has reached turn 4 after the second the test starts up to two more warm runs (four at
  most) and fails if no run produced a seedless turn-4 line — the seedless assertion is never skipped (review
  finding 3, round-2 item D). Then, on the same store with the real model, it calls `write_pattern` with
  `dedupe_threshold=0.15` and three distinct `run_id`s that no run used (`pattern:run:<run_id>` is upserted, so a
  reused id would overwrite a run's own pattern) for a neutral document, its one-word variant (expected `merged`,
  `hit_count == 2`; measured 0.088) and its paraphrase (expected `added`; measured 0.253) — the three sentences of
  the round-1 probe — so the shipped threshold's two outcomes are
  confirmed on the real model; asserts a fresh `ExperienceStore(chroma_path)` reports `stored_embedding_model ==
  "all-MiniLM-L6-v2"` and `distance_space == "l2"`; and asserts `DefaultEmbeddingFunction()` and
  `ONNXMiniLM_L6_V2()` embed one neutral probe identically (FR-018, SC-010). It does not depend on the attacker
  succeeding.
- **Rationale**: the one key-bearing test confirms the shipped defaults on the real model (D6) and the real stamp.

## D11 — Documentation and the roadmap edit (implementation PR)

- **Decision**: `docs/technical-design.md` (store section: hit counts, the model-name stamp and check, the
  retrieval controls and their settings; the `memory.retrieval`/`memory.writeback` field list), `README.md` (the
  two settings where the other `KESTREL_EXPERIENCE_*` lines are documented, if listed there), `.env.example`,
  `CLAUDE.md` (a learned note), `specs/010-structured-logging/contracts/log-records.md` (the rows of D7, with the
  `spec-change:` note on the PR), and — as the last task — `docs/roadmap.md`: "Retrieval controls" moves from
  "From reviewer feedback" into "Done" as **011** (with the shipped shape: attacker-only query, floor, de-dup at
  retrieval and write-back with hit counts, model-name stamp and check, the fixture, the logged settings), and the
  planned items renumber to **012** regression replay, **013** behavioural evidence expansion, **014** community
  prompt feed, including the "Regression replay (011) is unaffected" cross-reference inside the community-feed
  item, which becomes 012 (FR-019, SC-011).

## D12 — What stays exactly as it is

- The hints block (`experience/hints.py`), memory retrieval and its recency cap, the warm/cold switch and its
  recording, single-turn runs (no retrieval), the judge, the caps, the permission and terms gates, the profile,
  deletion, the SQLite schema (v8 — no migration), the run scope and the order of lines inside it, tracing, and
  the legacy store methods `retrieve_patterns` / `retrieve_patterns_with_ids` (k nearest, no controls; kept for
  the existing feature-004 tests and marked legacy).

## D13 — The distance space is pinned to `l2` at creation, recorded, and verified at open

- **Decision**: `ExperienceStore` creates its collection with `configuration={"hnsw": {"space": "l2"}}` and
  `DISTANCE_SPACE_KEY = "kestrel_distance_space"` in the metadata beside the model name. On every open it reads the
  index's **actual** space from `collection.configuration_json["hnsw"]["space"]` (a reopen ignores a conflicting
  configuration, so the argument alone proves nothing) into `self.distance_space`, stamps the key when missing —
  only when that actual space is `l2`, so a non-`l2` index is never stamped and never logs the stamp line before
  `self_check` fails it (together with the model name, which keeps its stored value when present; one `message`
  line) — and `self_check()` raises `SpaceMismatch(ExperienceStoreError)`
  with `stored` (the actual space) and `expected` (`l2`) when they differ — before the model-name comparison and the
  probe. `store_error_kind` returns `space_mismatch`; `api/main.py` emits `experience.unavailable` with
  `reason_kind = space_mismatch`, `stored_space`, `expected_space` and the space-specific constant message (the
  remedy: rebuild the store directory), and disables the store for the session exactly as for a model mismatch.
- **Rationale**: review finding 11. The floor and the write-back use the distance ChromaDB reports, and retrieval
  de-duplication computes squared Euclidean distances from the stored embeddings (D2); the two agree only under
  `l2`. Today the space is inherited from the embedding function's `default_space()` — `l2` for the shipped default
  and the stub, but `cosine` for `ONNXMiniLM_L6_V2` used directly — so a collection built outside Kestrel, or by a
  future version with another function, would silently halve every distance. Pinning the space at creation,
  recording it and verifying the actual index space closes that gap with the same failure shape as the model check.
- **Compatibility**: every feature-004 store was created with no configuration and the default function, so its
  index is `l2` already; the first open by this version stamps the missing keys and never fails on it.
- **Alternatives considered**: trusting the creation argument (ignored on reopen); comparing only the metadata key
  (a stamp could lie about an index created elsewhere); converting the de-duplication to cosine (would make the
  two measures disagree in the other direction).
