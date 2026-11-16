# Contract: the retrieval path (`src/kestrel/experience/retrieval.py`, new) and its settings

One module builds the query, selects the patterns and assembles the attacker's background for both callers
(`api/main.py::start_run` and `experiments/engine.py::_run_rep`). `attack/graph.py` is unchanged: it still receives a
plain `hint_provider(conversation) -> str | None` and never imports the store.

## Constants

```text
QUERY_MESSAGES = 2        # attacker messages in the query (FR-001; clarified 2026-11-16)
CANDIDATE_MULTIPLIER = 4  # candidate pool = min(k * 4, patterns in the family)
```

## `build_query(family: str, conversation: Sequence[tuple[str, str]]) -> tuple[str, int]`

- Keeps the messages whose role is exactly `"attacker"`, takes the last `QUERY_MESSAGES`, joins them with single
  spaces in conversation order, and prefixes the family label (`attacks.library.family_label(family)`, as today).
- Returns `(query_text, attacker_messages_used)`. An empty conversation yields `(label, 0)` (never reached in a run:
  the provider is first called on turn 2 with the seed already recorded).
- Accepted residual (spec assumption): an attacker message may itself echo a fragment of a reply, because the
  attacker model saw the reply; that text is the attacker's own and is not filtered.
- Never reads an `"agent"` message; no other input exists (the judge's reason and progress are not in the
  conversation list). FR-001, FR-002.

## `select_patterns(candidates, *, k, distance_floor, dedupe_threshold) -> Selection`

Pure. `candidates` are nearest first (as the store returns them).

```text
selected, dropped_floor, dropped_duplicate = [], 0, 0
for candidate in candidates:                       # nearest first
    if len(selected) == k: break                   # filled: later candidates are not examined
    if distance_floor is not None and candidate.distance > distance_floor:
        dropped_floor += number of candidates from this one to the end   # all farther: counted, walk ends
        break
    if dedupe_threshold is not None and any(sq_l2(candidate.embedding, s.embedding) <= dedupe_threshold
                                            for s in selected):
        dropped_duplicate += 1; continue
    selected.append(candidate)
candidate_count = dropped_floor + dropped_duplicate + len(selected)
```

- `sq_l2(a, b) = sum((x - y) ** 2 for x, y in zip(a, b))` — the collection's `l2` measure, standard library only.
- Guarantees (FR-003 to FR-005): at most k; every selected distance `<= distance_floor` when the floor is on; no two
  selected within `dedupe_threshold` when the threshold is on; nearest first; a skipped duplicate never consumes a
  slot; `candidate_count == dropped_floor + dropped_duplicate + len(selected)`; the selection is short of k only
  when every candidate of the pool was examined (SC-003). With both controls off and a pool of k, the selection is
  the feature-004 result.
- Boundaries: a candidate at exactly the floor is kept; two hits at exactly the threshold are duplicates.

## `background_provider(experience, *, target_id, purpose, family, settings, use_prior_experience) -> Callable[[list], str | None]`

Returns the per-turn callable the graph calls with the conversation so far.

- `not use_prior_experience` or `experience is None` → `format_hints(purpose=purpose, patterns=[], memory=[])`
  (cold: purpose only, `004/FR-015`); no retrieval line.
- Otherwise, per call:
  1. `memory = experience.retrieve_memory(target_id=…, family=…, cap=settings.experience_memory_cap)` (unchanged).
  2. `query_text, used = build_query(family, conversation)`.
  3. `pool = min(settings.experience_pattern_k * CANDIDATE_MULTIPLIER, experience.count("pattern", family=family))`;
     `candidates = experience.query_patterns(family=family, query_text=query_text, n=pool)`.
  4. `retrieval = settings.retrieval` (a `RetrievalSettings`, `src/kestrel/settings.py`);
     `selection = select_patterns(candidates, k=retrieval.k, distance_floor=retrieval.distance_floor,
     dedupe_threshold=retrieval.dedupe_threshold)`.
  5. `events.memory_retrieval(pattern_ids=selection.pattern_ids, memory_count=len(memory),
     k=…, distance_floor=…, dedupe_threshold=…, candidate_count=…, dropped_floor=…, dropped_duplicate=…,
     distances=selection.distances, query_messages=used)` — emitted whenever the store was asked, zero counts when
     nothing came back (`010/FR-016` unchanged).
  6. `return format_hints(purpose=purpose, patterns=selection.documents, memory=memory)`.
- A store failure propagates to the graph, which already treats a provider exception as best-effort
  (`memory.retrieval_failed`, the turn continues without hints).

## Settings (`src/kestrel/settings.py`, `.env.example`)

```text
KESTREL_EXPERIENCE_DISTANCE_FLOOR=1.8      # drop hits farther than this (collection l2 distance); "off" disables
KESTREL_EXPERIENCE_DEDUPE_THRESHOLD=0.15   # hits/successes at or below this distance are near-identical; "off" disables
```

- Parsing (`non_negative_float_or_off`): unset or blank → the default; `off` (any case) → `None`; otherwise a float
  `>= 0`, else `SettingsError("<NAME> must be a non-negative number or 'off', not '<raw>'.")`.
- `RetrievalSettings(k, distance_floor, dedupe_threshold)` is a frozen dataclass in `src/kestrel/settings.py`;
  `Settings.retrieval` builds it from `experience_pattern_k`, `experience_distance_floor` and
  `experience_dedupe_threshold`.
- Tuned for the shipped model `all-MiniLM-L6-v2` (research D6); the `.env.example` comment says a different
  embedding model needs retuned values and a rebuilt store.
- `GET /api/config` reports `experience.distance_floor` and `experience.dedupe_threshold` (`number | null`).

## Write-back (`src/kestrel/experience/writeback.py`)

```text
write_back(experience, store, run, turns, *, dedupe_threshold: float | None = None) -> bool
```

Unchanged flow (memory record first, then the pattern on a success, then the run flag) except that the success
path calls `experience.write_pattern(..., dedupe_threshold=dedupe_threshold)` and puts the returned `PatternWrite`
on the line: `events.memory_writeback(written=True, pattern_written=True, pattern_outcome=…, pattern_id=…,
hit_count=…, pattern_distance=…)`. A non-success emits the line exactly as today. Both callers pass
`settings.experience_dedupe_threshold`.
