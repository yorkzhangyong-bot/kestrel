---

description: "Task list for feature 011 — retrieval controls for the experience store"
---

# Tasks: Retrieval Controls for the Experience Store (011)

**Input**: Design documents from `specs/011-retrieval-controls/` (plan.md, spec.md, research.md, data-model.md,
contracts/, quickstart.md)

**Tests**: REQUIRED — Principle VII (tests first, one e2e per feature). Every test carries a traceability token
`011/FR-###` / `011/SC-###` (or a module-level `FEATURE = "011"`). Tests are written FIRST and must fail before the
implementation task that satisfies them. Every store in a test is a temporary one (`tmp_path`), never the
repository's `data/chroma`; every offline test uses the lexical `StubEmbeddingFunction` of T003 and states the
floor and threshold it needs (research D8). Log assertions read the rendered JSON lines through the `json_log`
fixture, never `caplog.text`. **No attack wording anywhere** — placeholder messages, replies and pattern texts only
(the fixture included).

**Organization**: by user story. MVP = Setup + Foundational + US1 + US2 (the P1 stories: the attacker-only query
and the selective, de-duplicated selection). US3 (write-back merge) and US4 (embedding model name and distance
space) are P2 increments on the same store; US5 (the recall@k fixture) is P3 tooling. The roadmap edit (FR-019) is
the last task of all, in the Polish phase, and is never part of the spec-only pull request.

**Hard rules carried into every task**: no new dependency, required or optional (Principle X, FR-016); no target
reply, judge text, query text, message text or pattern text on any line (`010/FR-009`, FR-013); no URL, display
name or auth value in the store, its metadata, a query or a line (FR-017); hard caps, the permission gate, the
warm/cold switch, single-turn runs, memory retrieval and the hints block unchanged (FR-015); existing tests keep
their intent — the one expectation this feature changes on purpose is the feature-004 deletion test's single-turn
success, which now merges into its library seed (T025, SC-009).

## Phase 1: Setup

- [X] T001 [P] Document the two settings in `.env.example` beside `KESTREL_EXPERIENCE_PATTERN_K` /
      `KESTREL_EXPERIENCE_MEMORY_CAP`: `KESTREL_EXPERIENCE_DISTANCE_FLOOR=1.8` ("drop hits farther than this, in the
      collection's l2 distance; `off` disables") and `KESTREL_EXPERIENCE_DEDUPE_THRESHOLD=0.15` ("hits or successes
      at or below this distance are near-identical; `off` disables"), with the note that both are tuned for the
      shipped embedding model `all-MiniLM-L6-v2` and that another model needs retuned values and a rebuilt store,
      and a tuning note: the floor is a measured default, not a guarantee — a query from turn 4 on (no seed in it)
      may occasionally select nothing, visible as `pattern_count` 0 with `dropped_floor` on the `memory.retrieval`
      line; raise or lower the floor from the `distances` and `dropped_floor` those lines log (011/FR-012).
- [X] T002 [P] Unit test `tests/unit/test_support_embedding.py` for the lexical test embedding (`FEATURE = "011"`):
      identical texts embed at squared distance 0; two single-word texts whose hash buckets are first asserted to
      differ (`zlib.crc32(word.encode()) % 256`) embed at 2.0 (within 1e-9); every vector has unit length; the same
      text embeds identically across calls and across a fresh instance (a stable hash, not the per-process
      `hash()`); changing one token of a six-token sentence of collision-free words lands at `2 − 2·5/6` (≈ 0.333);
      tokenisation is lower-case alphanumeric (so `direct_injection` yields two tokens); `dim == 256`;
      `StubEmbeddingFunction.MODEL_NAME == "kestrel-lexical-stub"` and `name()` is still `kestrel_stub`;
      `build_from_config(get_config())` round-trips (011/FR-014, 011/SC-008).
- [X] T003 Re-implement `tests/support.py::StubEmbeddingFunction` as a hashed bag of words: tokens =
      lower-case runs of `[a-z0-9]`, each hashed with `zlib.crc32(token.encode()) % dim` (`dim = 256`), counted,
      then L2-normalised (an empty text → the zero vector); keep `name()` (`kestrel_stub`), `get_config()`
      (`{"dim": …}`) and `build_from_config`; add `MODEL_NAME = "kestrel-lexical-stub"`. Add
      `SpyExperienceStore(ExperienceStore)` beside it: records every `query_patterns` call as `{"family",
      "query_text", "n"}` in `self.queries` and every `write_pattern` result in `self.pattern_writes`, delegating to
      the real methods. Add the known string `PURPOSE_TEXT = "purpose placeholder 7719"` beside the other markers
      (011/FR-014, 011/FR-002).

---

## Phase 2: Foundational (Blocking Prerequisites)

**⚠️ Blocks every user story**: the settings the controls read and the catalogue fields the lines carry.

- [X] T004 [P] Extend `tests/unit/test_settings_experience.py` (it already holds five feature-004 tests; every new
      test carries a scoped `011/FR-012` token): with both variables unset, `experience_distance_floor == 1.8` and
      `experience_dedupe_threshold == 0.15`; `off`, `OFF` and `Off` → `None`; `0` → `0.0`; `0.25` → `0.25`; `-1`,
      `abc` and `on` raise `SettingsError` naming the variable; the two are parsed independently (one `off`, the
      other a number); `settings.retrieval` is a `RetrievalSettings(k=5, distance_floor=1.8, dedupe_threshold=0.15)`
      by default and reflects `off` as `None` (011/FR-012).
- [X] T005 [P] Extend `tests/integration/test_api_base.py` (the `GET /api/config` assertions): the `experience`
      object carries `distance_floor == 1.8` and `dedupe_threshold == 0.15` by default, and `null` for each when the
      corresponding setting is `off` (build the app with a `Settings` whose field is `None`) (011/FR-012).
- [X] T006 [P] Extend `tests/unit/test_events.py`: `events.memory_retrieval(pattern_ids=[...], memory_count=1, k=5,
      distance_floor=1.8, dedupe_threshold=0.15, candidate_count=4, dropped_floor=1, dropped_duplicate=1,
      distances=[0.2741, 0.9876], query_messages=2)` renders a `memory.retrieval` record carrying exactly those
      fields plus `warm`/`pattern_count`, with no `log.unknown_field` warning; `distance_floor=None` renders as
      `null`; `events.memory_writeback(written=True, pattern_written=True, pattern_outcome="merged",
      pattern_id="pattern:lib:x", hit_count=3, pattern_distance=0.0412)` renders those four fields and omits them
      when not given; `emit("experience.unavailable", reason_kind="embedding_model_mismatch", stored_model="a",
      expected_model="b", message=<the mismatch constant>)` keeps both names and the constant message, and
      `emit("experience.unavailable", reason_kind="space_mismatch", stored_space="cosine", expected_space="l2",
      message=<the space constant>)` keeps both spaces (011/FR-013).
- [X] T007 Implement the settings and the catalogue: in `src/kestrel/settings.py` add
      `DEFAULT_EXPERIENCE_DISTANCE_FLOOR = 1.8`, `DEFAULT_EXPERIENCE_DEDUPE_THRESHOLD = 0.15`, the fields
      `experience_distance_floor: float | None` and `experience_dedupe_threshold: float | None` on `Settings`, a
      `non_negative_float_or_off(name, default)` parser (unset/blank → default; `off` case-insensitive → `None`;
      otherwise `float(raw) >= 0`, else `SettingsError(f"{name} must be a non-negative number or 'off', not
      {raw!r}.")`), the frozen dataclass `RetrievalSettings(k: int, distance_floor: float | None, dedupe_threshold:
      float | None)` and a `Settings.retrieval` property building it from `experience_pattern_k`,
      `experience_distance_floor` and `experience_dedupe_threshold`; in `src/kestrel/api/schemas.py` add
      `distance_floor: float | None` and `dedupe_threshold: float | None` to `ExperienceOut` and fill them in
      `src/kestrel/api/main.py`'s config route; in `src/kestrel/events.py` extend `CATALOGUE["memory.retrieval"]`
      with `k`, `distance_floor`, `dedupe_threshold`, `candidate_count`, `dropped_floor`, `dropped_duplicate`,
      `distances`, `query_messages`, `CATALOGUE["memory.writeback"]` with `pattern_outcome`, `pattern_id`,
      `hit_count`, `pattern_distance`, `CATALOGUE["experience.unavailable"]` with `stored_model`, `expected_model`,
      `stored_space`, `expected_space`, and give `memory_retrieval(...)` / `memory_writeback(...)` the matching
      keyword arguments: `distance_floor` and `dedupe_threshold` render `null` when off; `distances` are rounded to
      4 decimals; the four write-back outcome fields are omitted when `pattern_outcome` is `None` (a non-success)
      and otherwise all present, `pattern_distance` as `null` when the family had no pattern or de-duplication is
      off (011/FR-012, 011/FR-013).
- [X] T008 Extend `specs/010-structured-logging/contracts/log-records.md` with the rows of
      `specs/011-retrieval-controls/contracts/log-records-delta.md`: the `memory.retrieval` and `memory.writeback`
      fields; on `experience.unavailable` the reason kinds `embedding_model_mismatch` and `space_mismatch`, the
      fields `stored_model`/`expected_model`/`stored_space`/`expected_space`, and the two mismatch-specific
      constant `message` texts that carry the remedy (quoted verbatim from the delta contract); the new stamp
      `message` text. Add a `spec-change: 011 extends the memory.retrieval, memory.writeback and
      experience.unavailable records` line to the implementation pull request's description (the traceability gate
      requires it when a spec file changes alongside `src/`) (011/FR-013).

**Checkpoint**: `uv run pytest tests/unit/test_settings_experience.py tests/unit/test_events.py
tests/integration/test_api_base.py` green; nothing retrieves differently yet.

---

## Phase 3: User Story 1 — Hints come from the attacker's own words, never the target's (P1) 🎯 MVP

**Goal**: one shared retrieval path whose query is the family label plus the attacker's last two own messages —
never a reply, a judge reason or a progress note, a memory summary or the purpose description — for API-started
and experiment-executed runs alike.

**Independent Test**: two warm adaptive runs against one stub target whose purpose description carries a known
marker, whose replies carry `REPLY_TEXT`, with a stub judge whose reason and progress carry `JUDGE_REASON` /
`JUDGE_PROGRESS` (so the second run's memory summaries carry the progress marker), recording every query the store
receives through a `SpyExperienceStore`; the markers appear zero times and the label and the attacker's messages
appear every time from turn 2; the same holds for a run executed by a warm experiment arm.

### Tests for User Story 1

- [X] T009 [P] [US1] Unit test `tests/unit/test_retrieval_query.py` for `build_query(family, conversation)`
      (`FEATURE = "011"`): with `[("attacker", "<seed>")]` it returns `("<label> <seed>", 1)` where `<label>` is
      `family_label(family)`; with attacker/agent pairs the `agent` texts never appear; with three attacker messages
      only the last two appear, in order, after the label; an empty conversation returns `(label, 0)`; roles other
      than exactly `"attacker"` are ignored; `QUERY_MESSAGES == 2` (011/FR-001).
- [X] T010 [P] [US1] Integration test `tests/integration/test_retrieval_query_isolation.py`: build the app with
      `make_client(experience=SpyExperienceStore(settings.chroma_path, embedding_function=StubEmbeddingFunction()))`
      seeded from `fixture_library()`, a `StubAttacker` and a `StubJudge(verdict="failed", reason=JUDGE_REASON,
      progress=JUDGE_PROGRESS)`, and a stub target transport replying `REPLY_TEXT`; save a target whose auth header
      value is `SECRET`, URL `TARGET_URL`, name `TARGET_NAME` and purpose description `PURPOSE_TEXT`; run **two**
      warm adaptive attacks against it with `adaptive_max_turns=4` (after the first, the target's memory holds a
      summary built from the first run's judge progress, so `JUDGE_PROGRESS` is now also in the store); assert the
      spy recorded one query per turn from turn 2 of each run (six queries), that `REPLY_TEXT`, `JUDGE_REASON`,
      `JUDGE_PROGRESS`, `PURPOSE_TEXT`, `SECRET`, `TARGET_URL` and `TARGET_NAME` each appear 0 times in every query,
      that every query starts with the family label, that each run's turn-2 query ends with the seed text, the
      turn-3 query contains the seed and `<attacker turn 2>`, and the turn-4 query contains `<attacker turn 2>` and
      `<attacker turn 3>` but not the seed (the window); then run a cold attack and a single-turn attack and assert
      the spy recorded no query. Repeat the warm case through `POST /api/experiments` with one warm adaptive arm
      (`use_prior_experience` true, `reps` 1, polled to completion) and assert the same for its queries
      (011/FR-002, 011/FR-015, 011/FR-017, 011/SC-001).
- [X] T011 [P] [US1] Unit test `tests/unit/test_experience_store_controls.py` (`FEATURE = "011"`), the
      `query_patterns` part: on a temporary store seeded with `fixture_library()`, `query_patterns(family=
      "system_prompt_leak", query_text=…, n=10)` returns only that family's patterns, nearest first (distances
      non-decreasing), each `Candidate` carrying `id`, `document`, a float `distance` and a tuple `embedding` whose
      length is the stub's `dim`; `n` larger than the family's count returns the family's count; an empty family
      returns `[]` without error; memory records never appear (011/FR-003, 011/FR-005).

### Implementation for User Story 1

- [X] T012 [US1] In `src/kestrel/experience/store.py` add `Candidate` (frozen dataclass: `id`, `document`,
      `distance`, `embedding: tuple[float, ...]` — defined here, imported by `retrieval.py`) and
      `query_patterns(*, family, query_text, n) -> list[Candidate]` per `contracts/experience-store.md`: clamp `n`
      to `count("pattern", family=family)`, return `[]` for `0` without querying, otherwise one family-scoped
      `query` with `include=["documents", "distances", "embeddings"]`, candidates in the collection's order; mark
      `retrieve_patterns` / `retrieve_patterns_with_ids` as legacy (k nearest, no controls) in their docstrings
      (011/FR-003, 011/FR-005).
- [X] T013 [US1] Create `src/kestrel/experience/retrieval.py` per `contracts/retrieval.md`: `QUERY_MESSAGES = 2`,
      `CANDIDATE_MULTIPLIER = 4`, `Selection` (`selected`, `candidate_count`, `dropped_floor`, `dropped_duplicate`;
      properties `pattern_ids`, `documents`, `distances` rounded to 4 decimals), `build_query(family,
      conversation) -> (text, count)` (attacker role only, last two, label first), a first `select_patterns(
      candidates, *, k, distance_floor, dedupe_threshold) -> Selection` that takes the k nearest and keeps the count
      identity (the floor and the threshold are applied in T018), and `background_provider(experience, *,
      target_id, purpose, family, settings, use_prior_experience)` returning the per-turn callable: cold or no store
      → `format_hints(purpose=purpose, patterns=[], memory=[])`; warm → `retrieve_memory`, `build_query`, pool =
      `min(k * 4, experience.count("pattern", family=family))`, `query_patterns`, `select_patterns` with
      `settings.retrieval`, `events.memory_retrieval(...)` with every field of T007, then `format_hints(...)` with
      the selected documents in order (011/FR-001, 011/FR-002, 011/FR-013).
- [X] T014 [US1] Wire both callers: in `src/kestrel/api/main.py::start_run` replace the local `hint_provider` with
      `background_provider(experience, target_id=target.id, purpose=target.description, family=prompt.family,
      settings=settings, use_prior_experience=body.use_prior_experience)` and delete `_recent_conversation`; in
      `src/kestrel/experiments/engine.py` replace `_hint_provider(...)` with the same factory (`arm.
      use_prior_experience`, `seed.family`); `attack/graph.py` is untouched (011/FR-002, 011/FR-015).
- [X] T015 [US1] Update the engine test doubles so the shared path runs against them: `_Experience` in
      `tests/unit/test_experiment_engine.py` and `tests/unit/test_experiment_warming.py` gain `count(self, type=None,
      *, family=None, target_id=None) -> 0` and `query_patterns(self, **kw) -> []`; keep every existing assertion
      (011/FR-015, 011/SC-009).

**Checkpoint**: `uv run pytest tests/unit/test_retrieval_query.py tests/unit/test_experience_store_controls.py
tests/integration/test_retrieval_query_isolation.py tests/unit/test_experiment_engine.py
tests/unit/test_experiment_warming.py tests/integration/test_runs_experience.py` green; a warm run's hints still
hold up to k patterns (no floor yet) and no reply ever reaches a query.

---

## Phase 4: User Story 2 — Only relevant, distinct patterns reach the attacker (P1)

**Goal**: the selection drops hits beyond the floor, skips near-identical hits without spending a slot, stays
nearest first, and the retrieval line reports the settings and the counts.

**Independent Test**: a temporary store with patterns at known distances; floor and threshold set between them;
the far one is absent, one of the duplicate pair is absent, the distinct third fills the selection, the order is
nearest first; with each control off in turn it stops acting, and with both off the feature-004 selection (the k
nearest) returns; the `memory.retrieval` line's counts add up.

### Tests for User Story 2

- [X] T016 [P] [US2] Unit test `tests/unit/test_retrieval_selection.py` for `select_patterns` (`FEATURE = "011"`),
      over hand-built `Candidate`s with unit vectors (so the squared distance between two candidates is known):
      a floor between near and far candidates keeps only the near ones (fewer than k; zero when all are far);
      with the floor off alone nothing is dropped for its distance — the far candidate returns while a duplicate
      is still skipped; with the threshold off alone both of a duplicate pair return while the far candidate is
      still dropped; with both controls off the result is the k nearest; two candidates within `dedupe_threshold`
      of each other →
      the nearer is selected, the other counted in `dropped_duplicate`, and a distinct third is still selected with
      `k=2`; `dedupe_threshold=None` skips nothing; the result is nearest first; a candidate at exactly the floor is
      kept and two at exactly the threshold are duplicates; `candidate_count == dropped_floor + dropped_duplicate +
      len(selected)` on every case, including the early stop once k is selected and the "all remaining are beyond
      the floor" count; the selection is short of k only when every candidate was examined (the pool exhausted):
      a pool of 4k candidates — the first selected, the next 3k − 1 its near-duplicates, the last k distinct —
      yields exactly k selected with `candidate_count == 4k − 1` (the last candidate is never examined); a pool of
      4k − 1 candidates with only k − 1 distinct at the end yields k selected with every candidate examined
      (`candidate_count == 4k − 1`); a pool of 4k − 2 candidates with only k − 2 distinct at the end yields k − 1
      selected with every candidate examined — short of k only because the pool is exhausted; `k=0` and an empty
      candidate list return an empty
      selection (011/FR-003, 011/FR-004, 011/FR-005, 011/SC-002, 011/SC-003).
- [X] T017 [P] [US2] Integration test `tests/integration/test_retrieval_lines.py`, the retrieval part: a warm
      adaptive run through `make_client` over a store seeded with `fixture_library()` (the shipped defaults in
      `Settings`) yields one `memory.retrieval` line per turn from turn 2 carrying `k == 5`, `distance_floor == 1.8`,
      `dedupe_threshold == 0.15`, integer `candidate_count`, `dropped_floor`, `dropped_duplicate`, a `distances`
      list that is non-decreasing with every value `<= 1.8` and as long as `pattern_count`, `query_messages == 1` on
      turn 2 and `2` from turn 3, and `candidate_count == dropped_floor + dropped_duplicate + pattern_count`; with
      `experience_distance_floor=None` the line renders `"distance_floor": null`; with a floor of `0.0001` the line
      has `pattern_count == 0`, `warm` false and the run still finishes with the same verdict; across the whole
      stream the seed text, `<attacker turn 2>`, `REPLY_TEXT`, `JUDGE_REASON`, `JUDGE_PROGRESS`, every fixture
      pattern document, `SECRET`, `TARGET_URL` and `TARGET_NAME` appear 0 times (011/FR-003, 011/FR-013, 011/FR-017,
      011/SC-003, 011/SC-007).

### Implementation for User Story 2

- [X] T018 [US2] Complete `select_patterns` in `src/kestrel/experience/retrieval.py` per `contracts/retrieval.md`:
      walk nearest first; stop when k are selected; a candidate beyond `distance_floor` ends the walk and every
      candidate from it to the end counts in `dropped_floor`; a candidate whose squared Euclidean distance
      (`sum((a - b) ** 2)` over the stored embeddings, standard library only) to any selected hit is `<=
      dedupe_threshold` counts in `dropped_duplicate`; `None` switches each control off; boundaries as T016
      (011/FR-003, 011/FR-004, 011/FR-005).
- [X] T019 [P] [US2] Extend `tests/integration/test_runs_experience.py`: a warm run's hints block lists the
      selected pattern documents in the retrieval line's order under the existing "Techniques from earlier
      attempts" label; a cold run's attacker input is unchanged (hints `None` without a purpose; purpose only with
      one); a single-turn run emits no retrieval line; the same stub-driven adaptive run uses the same `turns_used`
      and `tokens_used` as before the feature (compare against the values the existing feature-010 line test asserts)
      (011/FR-005, 011/FR-015, 011/SC-009).

**Checkpoint**: US1 + US2 green — the MVP: every warm run retrieves with the attacker-only query, the floor and
the de-duplication, and logs the settings.

---

## Phase 5: User Story 3 — A repeated success strengthens a pattern instead of cloning it (P2)

**Goal**: a success near-identical to an existing same-family pattern raises that pattern's hit count; a new
approach is added with hit count 1; the write-back line says which.

**Independent Test**: write back several successes into a temporary store (two near-identical to each other, one
replaying a library seed, one unlike every pattern, one near-identical only to another family's pattern) and check
the pool's count, each `hit_count`, `last_hit_run_id` and each line's outcome.

### Tests for User Story 3

- [X] T020 [P] [US3] Extend `tests/unit/test_experience_store_controls.py`, the `write_pattern` part: on a store
      seeded with `fixture_library()` and the stub's scale (`dedupe_threshold=0.3`): a document equal to a library
      seed's text → `PatternWrite("merged", "pattern:lib:<id>", 2, 0.0)`, no new record, `last_hit_run_id` set, the
      document untouched; a second merge → `hit_count 3`; a document sharing no token with any pattern →
      `PatternWrite("added", "pattern:run:<run_id>", 1, d)` with `d > 0.3` and `hit_count 1` in its metadata; a
      document near-identical only to another family's pattern → added in the run's family; two successive
      near-identical run documents → one `added` then one `merged` into `pattern:run:<first>`; `dedupe_threshold=None`
      → always `added` with `distance None`; an empty family → `added` with `distance None`; a pattern without
      `hit_count` (written directly with `collection.upsert`) merges to `2`; `seed_patterns` run again after a merge
      leaves `hit_count` and `last_hit_run_id` untouched and new seed ids get `hit_count 1`; `count("pattern")`
      after N near-identical successes equals the seeded count + 1 (011/FR-006, 011/FR-007, 011/FR-008, 011/SC-004).
- [X] T021 [P] [US3] Extend `tests/integration/test_retrieval_lines.py`, the write-back part: a single-turn run
      decided by a canary (the stub target echoes the canary) replays its seed verbatim, so its `memory.writeback`
      line carries `written` true, `pattern_written` true, `pattern_outcome == "merged"`, `pattern_id ==
      "pattern:lib:<seed id>"`, `hit_count == 2` and `pattern_distance == 0.0`; a second identical success →
      `hit_count == 3`; an adaptive run that succeeds on turn 2 (document = seed + `<attacker turn 2>`, distinct from
      the seed under the stub) → `"added"`, `pattern_id == "pattern:run:<run id>"`, `hit_count == 1`, a numeric
      `pattern_distance`; a second such run → `"merged"` into the first run's pattern with `hit_count == 2`; a
      failed run → no `pattern_outcome`, `pattern_id`, `hit_count` or `pattern_distance` field; a success with
      `experience_dedupe_threshold=None` → `"added"` and `pattern_distance` `null`; an experiment with a write-back
      arm emits the same fields on its runs' lines (the engine passes the threshold) (011/FR-008, 011/FR-013,
      011/FR-015).

### Implementation for User Story 3

- [X] T022 [US3] In `src/kestrel/experience/store.py` add `PatternWrite` (`outcome`, `pattern_id`, `hit_count`,
      `distance`) and change `write_pattern(*, run_id, document, family, owasp_category, dedupe_threshold=None) ->
      PatternWrite` per `contracts/experience-store.md` (nearest same-family pattern via one `query` of one result
      with metadata and distance; `<= threshold` → `update` with `hit_count = previous + 1` (previous = stored value,
      1 when absent) and `last_hit_run_id = run_id`; otherwise upsert `pattern:run:<run_id>` with the feature-004
      metadata plus `hit_count: 1`); make `seed_patterns` read the existing seed ids first and upsert existing ids
      without the `hit_count` key, new ids with `hit_count: 1` (011/FR-006, 011/FR-007, 011/FR-008).
- [X] T023 [US3] In `src/kestrel/experience/writeback.py` add the keyword `dedupe_threshold: float | None = None`,
      pass it to `write_pattern`, and put the returned outcome on the line (`events.memory_writeback(written=True,
      pattern_written=True, pattern_outcome=…, pattern_id=…, hit_count=…, pattern_distance=…)`; a non-success
      keeps today's call); pass `settings.experience_dedupe_threshold` from `src/kestrel/api/main.py::start_run` and
      `src/kestrel/experiments/engine.py::_run_rep` (011/FR-006, 011/FR-013).
- [X] T024 [US3] Update the doubles: `_Experience.write_pattern` in `tests/unit/test_experiment_engine.py` and
      `tests/unit/test_experiment_warming.py` returns `PatternWrite("added", "pattern:run:0", 1, None)` (counting
      the call as before); `FailingExperience` in `tests/integration/test_writeback.py` and `SpyExperience` in
      `tests/integration/test_report_safety.py` keep working with the new keyword; every assertion in those four
      files stays as it is (011/FR-015, 011/SC-009).
- [X] T025 [US3] Update `tests/integration/test_delete_clears_memory.py` on purpose — its single-turn success
      replays its library seed verbatim, which now merges instead of adding a pattern: replace the assertion
      `patterns_before > len(fixture_library().prompts)` with `patterns_before == len(fixture_library().prompts)`
      plus an assertion that the seed's pattern (`pattern:lib:<seed id>`) carries `hit_count == 2` and
      `last_hit_run_id` equal to the run's id (read through `experience._collection.get(ids=…,
      include=["metadatas"])` or a small store accessor added in T022), keep the deletion assertions (memory gone,
      pattern count unchanged), and add the tokens `011/FR-006` and `011/FR-008` beside its feature-004 tokens;
      the docstring names the intended change (011/FR-006, 011/FR-008, 011/SC-009).

**Checkpoint**: `uv run pytest tests/unit/test_experience_store_controls.py tests/integration/test_retrieval_lines.py
tests/integration/test_writeback.py tests/integration/test_report_safety.py
tests/integration/test_delete_clears_memory.py tests/unit/test_experiment_*.py` green.

---

## Phase 6: User Story 4 — The store knows which embedding model and distance space built it (P2)

**Goal**: the collection is created with an explicit `l2` space and records the embedding model name and the
space; a mismatch of either at start-up is one named ERROR line whose constant message carries the remedy, with
both values as fields, and the store disabled for the session; a feature-004 store is stamped on first open.

**Independent Test**: create a temporary store, confirm the name and the space are recorded and the index space is
`l2`; reopen under the same name silently; reopen with `embedding_model="other-model"` and confirm
`EmbeddingModelMismatch` from `self_check` and the app's `experience.unavailable` line; open a collection created
directly with a cosine space and confirm `SpaceMismatch`; create a version-only collection directly with ChromaDB
and confirm it opens and is stamped with both keys.

### Tests for User Story 4

- [ ] T026 [P] [US4] Unit test `tests/unit/test_experience_store_model.py` (`FEATURE = "011"`): a fresh store's
      collection metadata carries `kestrel_embedding_model == "kestrel-lexical-stub"` and `kestrel_distance_space ==
      "l2"` beside `kestrel_store_version`, its `configuration_json["hnsw"]["space"]` is `l2`, and
      `store.embedding_model == store.stored_embedding_model`; reopening under the same stub emits no `message` or
      warning line and `self_check()` passes; `ExperienceStore(path, embedding_function=stub,
      embedding_model="other-model").self_check()` raises `EmbeddingModelMismatch` (an `ExperienceStoreError`) with
      `stored == "kestrel-lexical-stub"`, `expected == "other-model"`, a message naming both and the remedy, and
      writes nothing (`count()` unchanged, no probe record); a collection created directly with
      `get_or_create_collection("kestrel_experience", configuration={"hnsw": {"space": "cosine"}},
      embedding_function=stub)` opens and then raises `SpaceMismatch` from `self_check` with `stored == "cosine"`,
      `expected == "l2"`; `store_error_kind(EmbeddingModelMismatch(...)) == "embedding_model_mismatch"`,
      `store_error_kind(SpaceMismatch(...)) == "space_mismatch"` and `describe_store_error` names both values in
      each case; a collection created directly with `get_or_create_collection("kestrel_experience",
      metadata={"kestrel_store_version": "1"}, embedding_function=stub)` (a feature-004 store: no configuration, so
      the stub's `l2` default space) opens without error, is stamped with the stub's model name and `l2`, emits the
      constant stamp `message` line once, and reopens silently; a collection created directly with
      `metadata={"kestrel_store_version": "1", "kestrel_embedding_model": "other-model"}` (a model name but no
      space key) is stamped with `l2` only and keeps `other-model` — a stamp never overwrites a recorded name — so
      `self_check()` under the stub still raises `EmbeddingModelMismatch`; the cosine collection above is never
      stamped and emits no stamp `message` line; `embedding_model_name(None) == "all-MiniLM-L6-v2"`,
      `embedding_model_name(stub) == "kestrel-lexical-stub"`, and a function without `MODEL_NAME` falls back to its
      `name()` (011/FR-009, 011/FR-010, 011/FR-011, 011/SC-006).
- [ ] T027 [P] [US4] Integration test `tests/integration/test_startup_model_mismatch.py`: first create the store
      at `settings.chroma_path` under the stub (so its metadata records `kestrel-lexical-stub` and `l2`), then
      monkeypatch `kestrel.api.main.ExperienceStore` with a subclass whose `__init__(path, **kwargs)` calls
      `super().__init__(path, embedding_function=StubEmbeddingFunction(), embedding_model="other-model")` — the
      pattern `tests/integration/test_startup_events.py` already uses — and call `create_app(settings,
      library=fixture_library())` with no injected store, so the app builds its own and runs `self_check`; assert
      exactly one ERROR `experience.unavailable` line with `exc_type == "EmbeddingModelMismatch"`, `reason_kind ==
      "embedding_model_mismatch"`, `stored_model == "kestrel-lexical-stub"`, `expected_model == "other-model"` and
      `message` equal to the mismatch constant of `contracts/log-records-delta.md` (it names the remedy); that the
      exception's own text appears nowhere on the stream; no `experience.seed_failed` line; a warm adaptive run
      through that app completes with `memory_written` false, a `memory.writeback` line with `written` false, and
      no `memory.retrieval` line. Second case: a collection created directly with a cosine configuration at
      `settings.chroma_path` → one ERROR `experience.unavailable` with `exc_type == "SpaceMismatch"`,
      `reason_kind == "space_mismatch"`, `stored_space == "cosine"`, `expected_space == "l2"` and the space constant
      message. Third case: a feature-004 shape (a version-only collection created directly with ChromaDB under the
      stub) starts with no `experience.unavailable` line and one `message` line "Recorded the embedding model name
      and distance space on the experience store." (011/FR-010, 011/FR-011, 011/FR-017, 011/SC-006).

### Implementation for User Story 4

- [ ] T028 [US4] In `src/kestrel/experience/store.py` add `EMBEDDING_MODEL_KEY = "kestrel_embedding_model"`,
      `DISTANCE_SPACE_KEY = "kestrel_distance_space"`, `DISTANCE_SPACE = "l2"`, `DEFAULT_EMBEDDING_MODEL =
      ONNXMiniLM_L6_V2.MODEL_NAME` (imported from `chromadb.utils.embedding_functions`; `DefaultEmbeddingFunction`
      delegates every call to a fresh `ONNXMiniLM_L6_V2()`, research D5), `embedding_model_name(embedding_function)`
      (`None` → the default; else `MODEL_NAME` if present, else `name()`), `EmbeddingModelMismatch` and
      `SpaceMismatch` (both `ExperienceStoreError` subclasses with `stored`/`expected` attributes), the constructor
      keyword `embedding_model: str | None = None`, creation with `configuration={"hnsw": {"space": "l2"}}` (a
      reopen ignores a conflicting configuration, so the actual space is read from
      `collection.configuration_json["hnsw"]["space"]`), the stamp on open of a missing key — only when the actual
      space is `l2` (`collection.modify(metadata={VERSION_KEY: <stored version>, EMBEDDING_MODEL_KEY: <the stored
      name when present, else expected>, DISTANCE_SPACE_KEY: "l2"})` plus the constant stamp `message` line; a
      stored name is never overwritten, so a store missing only the space key still fails `self_check` on a model
      mismatch, and a non-`l2` store is never stamped and never logs the stamp line — `self_check` fails it) and
      the attributes
      `embedding_model` / `stored_embedding_model` / `distance_space` (the actual index space); make `self_check()`
      compare the space, then the model name, raising the matching mismatch before the probe; extend
      `store_error_kind` (`EmbeddingModelMismatch` → `"embedding_model_mismatch"`, `SpaceMismatch` →
      `"space_mismatch"`) and `describe_store_error` (both values and the remedy) (011/FR-009, 011/FR-010,
      011/FR-011).
- [ ] T029 [US4] In `src/kestrel/api/main.py` extend the `experience.unavailable` emission: when the caught error
      (or its cause) is an `EmbeddingModelMismatch`, emit the line with `stored_model=error.stored,
      expected_model=error.expected` and the mismatch-specific constant `message` of
      `contracts/log-records-delta.md` (it states the remedy); when it is a `SpaceMismatch`, emit `stored_space`,
      `expected_space` and the space constant; every other cause keeps today's generic constant; the
      `experience = None` path is unchanged, so seeding, retrieval and write-back follow the existing
      unusable-store behaviour (011/FR-010).

**Checkpoint**: `uv run pytest tests/unit/test_experience_store_model.py
tests/integration/test_startup_model_mismatch.py tests/unit/test_experience_store_core.py
tests/integration/test_startup_events.py` green.

---

## Phase 7: User Story 5 — Retrieval quality is measurable (P3)

**Goal**: a labelled, neutral recall@k fixture and an offline check that scores it with the controls on.

**Independent Test**: seed a temporary store from the fixture and assert mean recall@k ≥ `min_recall`, zero hits
for the `no_relevant` query, exactly one hit per duplicate pair, and every published distance with its margin.

- [ ] T030 [P] [US5] Create `tests/fixtures/retrieval_recall.json` exactly per `contracts/recall-fixture.md`
      (`k`, `distance_floor 0.8`, `dedupe_threshold 0.5`, `min_recall 1.0`, five placeholder patterns across two
      families, five queries including one `no_relevant`, one `duplicate_pairs` entry, and the `expected_distances`
      table the contract publishes); texts are placeholder vocabulary only, never attack wording; the 21-word
      vocabulary is collision-free under `crc32 % 256` (verified in research D8) (011/FR-014).
- [ ] T031 [US5] Unit test `tests/unit/test_retrieval_recall.py` (`FEATURE = "011"`): load the fixture, build a
      duck-typed library (`version "fixture"`, prompts with `id`, `text`, `family`, `owasp_category` from
      `FAMILIES`), seed a temporary store (`StubEmbeddingFunction`), and for each query run `query_patterns` (pool
      `k * 4` clamped) + `select_patterns` with the fixture's settings; assert mean recall@k over queries with a
      non-empty `expected` is `>= min_recall`, every `no_relevant` query selects nothing, exactly one id of each
      `duplicate_pairs` entry is selected for the query that names one of them, every `expected` id exists in
      `patterns`, every distance in the fixture's `expected_distances` table is reproduced within 1e-6, every
      published distance lies at least 0.1 from both `distance_floor` and `dedupe_threshold` (the contract's margin
      table), no two vocabulary words share a hash bucket, and every text in the file is
      drawn from the vocabulary the contract lists (a guard against attack wording) (011/FR-014, 011/SC-005).

**Checkpoint**: `uv run pytest tests/unit/test_retrieval_recall.py` green.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [ ] T032 [P] End-to-end test `tests/e2e/test_us011_retrieval.py` (marker `e2e`, `FEATURE = "011"`), modelled on
      `tests/e2e/test_us2_experience.py` (in-process API, real HS-code target via `hs_target`, real judge and
      attacker, the default embedding, `chroma_path` under `tmp_path`, `adaptive_max_turns=4`,
      `adaptive_time_limit_s=120` as `tests/e2e/test_us2_experience.py` sets it so four real turns fit, the shipped
      defaults): save the target, run two warm adaptive attacks of the `system_prompt_leak` family and, while no
      run has reached turn 4 (a run ends early on `succeeded`, `attacker_failed`, `send_failed`, `token_budget` or
      `time_limit` alike, and then never issues a seedless query), up to two more — four at most; read the lines of
      every run (the first is warm on the library seeds too) through `GET /api/runs/{id}/log`; **first assert that
      at least one `memory.retrieval` line exists** (a run that ends on turn 1 fails the test loudly rather than
      passing vacuously), then assert every such line
      carries `k == 5`, `distance_floor == 1.8`, `dedupe_threshold == 0.15`, `candidate_count == dropped_floor +
      dropped_duplicate + pattern_count`, `pattern_count >= 1` and every value of `distances <= 1.8`, and that at
      least one line with `query_messages == 2` on turn 4 — a query without the seed — has `pattern_count >= 1`,
      **failing the test if no run produced such a line** (so the floor is confirmed on a seedless query); then, on
      the same temporary store with the real model, call `write_pattern` three times in the family with
      `dedupe_threshold=0.15` and three distinct `run_id`s that no run used (for example 900001, 900002 and 900003 —
      `pattern:run:<run_id>` is upserted, so a reused id would overwrite a run's own pattern): the neutral document "Please
      summarise the shipping rules for fragile goods in two sentences." (expected `added`), its one-word variant
      "Please summarise the shipping rules for fragile items in two sentences." (expected `merged` into the first
      with `hit_count == 2`; measured distance 0.088) and the paraphrase "In two sentences, give me a summary of how
      fragile goods must be shipped." (expected `added`; measured 0.253), asserting the three outcomes; then open
      `ExperienceStore(chroma_path)` and assert `stored_embedding_model == "all-MiniLM-L6-v2"` and `distance_space
      == "l2"`; and assert that `DefaultEmbeddingFunction()` and `ONNXMiniLM_L6_V2()` embed one neutral probe
      sentence identically (squared distance 0 within 1e-9), so a silent change of ChromaDB's default model is
      caught here; reuse `assert_no_secret_in_logs` where the fixture applies (011/FR-012, 011/FR-018, 011/SC-010).
- [ ] T033 [P] Extend `tests/unit/test_optional_extra.py`: the `[project] dependencies` list of `pyproject.toml`
      names exactly the eight packages of the fixed stack (chromadb, cryptography, fastapi, httpx, langgraph,
      markdown-it-py, streamlit, uvicorn — none other) and the `otel` extra is unchanged, so this feature adds no
      dependency (011/FR-016, 011/SC-008).
- [ ] T034 [P] Documentation: `docs/technical-design.md` (the ChromaDB section: `kestrel_embedding_model`,
      `kestrel_distance_space`, the explicit `l2` space, the `self_check` comparisons and their failure lines,
      `hit_count`/`last_hit_run_id`, the retrieval path — `experience/retrieval.py`, the attacker-only query, floor,
      de-duplication, the candidate pool — and the new `memory.retrieval`/`memory.writeback` fields in the logging
      bullet; the test-count line), `README.md` (the two settings wherever the other `KESTREL_EXPERIENCE_*`
      variables are listed), and a `CLAUDE.md` learned note (the lexical stub and its scale, the `embedding_model=`
      test seam, the metadata-merge semantics of ChromaDB upserts that keep `hit_count`, the measured real-model
      distances behind the defaults, ChromaDB ignoring a conflicting space on reopen) (011/FR-009, 011/FR-012,
      011/FR-013).
- [ ] T035 Write `specs/011-retrieval-controls/traceability.md` (the id → tests table in the feature-010 shape;
      "Untraced ids: none") and run `uv run python scripts/check_traceability.py` until every `011/FR-###` and
      `011/SC-###` is traced (011/SC-008).
- [ ] T036 Gates and quickstart validation: `uv run pytest tests/unit tests/integration` (coverage ≥ 85 % on
      `src`, every pre-existing test unchanged in intent apart from T025), `uvx ruff check src ui tests` clean,
      `uv run mypy src` advisory, `git diff --stat -- pyproject.toml uv.lock` empty, and the offline sections of
      `specs/011-retrieval-controls/quickstart.md` reproduced; fix anything that fails (011/FR-016, 011/SC-008,
      011/SC-009).
- [ ] T037 LAST — Roadmap: in `docs/roadmap.md` move the "Retrieval controls" bullet out of "From reviewer
      feedback" into "Done" as **011 — Retrieval controls** (one bullet in the Done style: attacker-only query,
      distance floor, de-duplication at retrieval and at write-back with hit counts, the embedding model name and
      distance space stamped and checked, the recall@k fixture, the settings on the `memory.retrieval` line;
      "Shipped in #27/#28" — the spec PR and the implementation PR; #28 is the next number on the repository
      when this task runs (latest PR #27, no issues), so the coordinator corrects it if the implementation PR
      gets another number) and renumber the planned items to **012 — Regression replay**, **013 — Behavioural
      evidence expansion**, **014 — Community prompt feed**, changing the community-feed item's "Regression replay
      (011) is unaffected" to "(012)"; this edit belongs to the implementation pull request only (011/FR-019,
      011/SC-011).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies; T001, T002 in parallel, T003 after T002 (its test).
- **Foundational (Phase 2)**: T004, T005, T006 in parallel after Setup; T007 after them; T008 any time after T007.
  **Blocks every user story** (the settings and the catalogue fields).
- **US1 (Phase 3)**: after Foundational. T009–T011 in parallel; T012 → T013 → T014 → T015.
- **US2 (Phase 4)**: after US1 (it completes the selection US1 wired). T016, T017, T019 in parallel; T018 after T016.
- **US3 (Phase 5)**: after Foundational and T012 (shares `store.py`); independent of US2. T020, T021 in parallel;
  T022 → T023 → T024 → T025.
- **US4 (Phase 6)**: after Foundational; independent of US1–US3 apart from sharing `store.py` (T028 after T022 to
  avoid conflicting edits). T026, T027 in parallel; T028 → T029.
- **US5 (Phase 7)**: after US2 (it scores the finished selection). T030 → T031.
- **Polish (Phase 8)**: after every story; T032–T034 in parallel; T035 → T036 → **T037 last**.

### User Story Dependencies

- **US1 (P1)**: the shared path — foundation for US2 and the query every other story's lines report.
- **US2 (P1)**: builds on US1's `select_patterns` stub; independently testable through the pure function.
- **US3 (P2)**: independent of US2; shares the threshold setting and `store.py`.
- **US4 (P2)**: independent; `store.py` only.
- **US5 (P3)**: needs the finished selection (US2) and `query_patterns` (US1).

### Parallel Opportunities

- Setup: T001 ∥ T002. Foundational: T004 ∥ T005 ∥ T006.
- US1 tests T009 ∥ T010 ∥ T011; US2 tests T016 ∥ T017 ∥ T019; US3 tests T020 ∥ T021; US4 tests T026 ∥ T027.
- Across stories once Foundational is done: US4 (T026–T029) can proceed beside US1/US2 as long as `store.py` edits
  are sequenced (T012 → T022 → T028).
- Polish: T032 ∥ T033 ∥ T034.

## Parallel Example: User Story 1

```bash
# Tests first, together:
Task: "Unit test build_query in tests/unit/test_retrieval_query.py"
Task: "Integration test known markers never reach a query in tests/integration/test_retrieval_query_isolation.py"
Task: "Unit test query_patterns in tests/unit/test_experience_store_controls.py"
# Then, in order: store.query_patterns (T012) → retrieval.py (T013) → the two callers (T014) → the doubles (T015)
```

## Implementation Strategy

### MVP First (US1 + US2)

1. Setup + Foundational: the lexical stub, the two settings, the catalogue fields, the 010 contract rows.
2. US1: the shared path with the attacker-only query — the safety property, proven by the known-marker test.
3. US2: the floor and the de-duplication, proven by the pure-function test and the line test.
4. **STOP and VALIDATE**: `uv run pytest tests/unit tests/integration`; quickstart US1/US2.

### Incremental Delivery

- US3 (write-back merge, hit counts, the deletion test's intended change) → US4 (model name and space) → US5
  (fixture) → Polish (e2e, docs, traceability, gates) → the roadmap edit last.
- Each story leaves the suite green and the existing behaviour (cold runs, single-turn runs, memory, caps)
  unchanged.

## Notes

- Every test task names its traceability tokens; `scripts/check_traceability.py` (T035) is the gate.
- `[P]` = different files, no dependency on an unfinished task. The three `store.py` tasks (T012, T022, T028) are
  sequenced to avoid conflicting edits.
- The implementation pull request description carries `Spec-PR: #<n>` and the `spec-change:` line of T008.
- Never commit `.specify/feature.json`.
