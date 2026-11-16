# Contract: the recall@k fixture (`tests/fixtures/retrieval_recall.json`) and its check

A labelled, neutral fixture that measures whether retrieval brings back the right patterns with the controls on
(FR-014, SC-005). It holds **no attack wording**: every text is a placeholder sentence built from neutral tokens
("placeholder approach alpha step one"), exactly like the fixture library's `<placeholder … prompt N>` texts. It is
run offline with the lexical stub embedding (research D8: hashed bag of words, `crc32 % 256`, normalised), so it
states its own thresholds, and its 21-word vocabulary — `placeholder approach alpha step one variant plain again
beta two framing gamma three staged delta four opening orchestra rehearsal tuesday evening` — maps to 21 distinct
hash buckets (verified, research round 2), so every distance below is exact.

## Schema

```json
{
  "k": 3,
  "distance_floor": 0.8,
  "dedupe_threshold": 0.5,
  "min_recall": 1.0,
  "patterns": [
    {"id": "fx-001", "family": "direct_injection", "text": "placeholder approach alpha step one variant plain"},
    {"id": "fx-002", "family": "direct_injection", "text": "placeholder approach alpha step one variant plain again"},
    {"id": "fx-003", "family": "direct_injection", "text": "placeholder approach beta variant two framing"},
    {"id": "fx-004", "family": "direct_injection", "text": "placeholder approach gamma variant three staged"},
    {"id": "fx-005", "family": "system_prompt_leak", "text": "placeholder approach delta variant four opening"}
  ],
  "queries": [
    {"text": "approach alpha step one variant plain", "family": "direct_injection", "expected": ["fx-001"]},
    {"text": "approach beta variant two framing", "family": "direct_injection", "expected": ["fx-003"]},
    {"text": "approach gamma variant three staged", "family": "direct_injection", "expected": ["fx-004"]},
    {"text": "approach delta variant four opening", "family": "system_prompt_leak", "expected": ["fx-005"]},
    {"text": "orchestra rehearsal tuesday evening", "family": "direct_injection", "expected": [], "no_relevant": true}
  ],
  "duplicate_pairs": [["fx-001", "fx-002"]],
  "expected_distances": {
    "query_to_pattern": [
      [0, "fx-001", 0.1484], [0, "fx-002", 0.2679], [0, "fx-003", 1.3333], [0, "fx-004", 1.3333],
      [1, "fx-003", 0.1743], [1, "fx-004", 1.2697], [1, "fx-001", 1.3239], [1, "fx-002", 1.3675],
      [2, "fx-004", 0.1743], [2, "fx-003", 1.2697], [2, "fx-001", 1.3239], [2, "fx-002", 1.3675],
      [3, "fx-005", 0.1743],
      [4, "fx-001", 2.0], [4, "fx-002", 2.0], [4, "fx-003", 2.0], [4, "fx-004", 2.0]
    ],
    "pattern_to_pattern": [
      ["fx-001", "fx-002", 0.1292], ["fx-001", "fx-003", 1.0742], ["fx-001", "fx-004", 1.0742],
      ["fx-002", "fx-003", 1.134], ["fx-002", "fx-004", 1.134], ["fx-003", "fx-004", 1.0]
    ]
  }
}
```

## Published distances and margins

Distances are `2 − 2·cos` on the normalised bag of words (`query_to_pattern` entries are `[query index, pattern id,
distance]`, same-family pairs only; `pattern_to_pattern` entries are same-family pairs). The **floor** (0.8) is
compared with query-to-pattern distances; the **threshold** (0.5) with pattern-to-pattern distances (and, at
write-back, document-to-pattern). The two values were chosen so that **every published distance, compared or not,
lies at least 0.1 from both controls** — the smallest margin is 0.20 — so no fixture number is a boundary case for
either control:

| published distances vs control | nearest below | nearest above | margins |
|--------------------------------|---------------|---------------|---------|
| query-to-pattern vs the floor 0.8 | 0.2679 (query 0 to `fx-002`) | 1.2697 (queries 1 and 2 to the other distinct pattern) | 0.53 / 0.47 |
| pattern-to-pattern vs the threshold 0.5 | 0.1292 (`fx-001`/`fx-002`, the duplicate pair) | 1.0 (`fx-003`/`fx-004`) | 0.37 / 0.50 |
| query-to-pattern vs the threshold 0.5 (never compared) | 0.2679 | 1.2697 | 0.23 / 0.77 |
| pattern-to-pattern vs the floor 0.8 (never compared) | 0.1292 | 1.0 | 0.67 / 0.20 |

The check (T031) reproduces every published distance — the store's own value rounded to 4 decimals, as the table
publishes them — within 1e-6 and asserts that each lies at least 0.1 from both `distance_floor` and
`dedupe_threshold`, so a stub or fixture change that erodes a margin fails loudly.

Worked example: `fx-001` and `fx-002` share 7 of 8 tokens → 0.1292 (a duplicate under 0.5); query 0 shares 6 of
`fx-001`'s 7 tokens → 0.1484 (selected) and 6 of `fx-002`'s 8 → 0.2679 (within the floor, then skipped as a
duplicate of the selected hit); `fx-003` shares only "approach" and "variant" with it → 1.3333 (dropped by the floor
of 0.8); the "orchestra" query shares nothing with any pattern → 2.0 (nothing selected).

Rules:

- `patterns[].id` match the library id shape (`[a-z]{2,4}-\d{3}`) so the fixture can be seeded through
  `ExperienceStore.seed_patterns` with a duck-typed library (`version = "fixture"`, prompts with `id`, `text`,
  `family`, `owasp_category` — the category taken from `FAMILIES` by family); seeded ids are `pattern:lib:<id>`.
- `queries[].expected` lists pattern ids (without the `pattern:lib:` prefix) that must appear among the selected
  hits; `no_relevant: true` queries have an empty `expected` and must select **nothing** with the floor on.
- `duplicate_pairs` lists pairs that are near-identical under `dedupe_threshold`; for each pair the fixture holds a
  query close to both, and exactly one of the two may be selected for it (the expected id is the nearer one).
- `min_recall` is the minimum mean recall@k over queries with a non-empty `expected`; recall@k for one query is
  `|expected ∩ selected| / |expected|`.
- The check is a unit test (`tests/unit/test_retrieval_recall.py`, token `011/FR-014`, `011/SC-005`): a fresh
  temporary store, `seed_patterns(fixture_library)`, then for every query `query_patterns` + `select_patterns` with
  the fixture's `k`, `distance_floor` and `dedupe_threshold`; it asserts `mean recall >= min_recall`, zero hits for
  every `no_relevant` query, exactly one of each duplicate pair, every `expected_distances` entry reproduced (rounded
  to 4 decimals) within 1e-6, the ≥ 0.1 margins of the table above, no two vocabulary words sharing a hash bucket, and that no text in the
  file contains anything but the placeholder vocabulary (a guard against attack wording creeping in).
- Measured on the lexical stub (research D8), the shipped values would also pass this fixture, but the fixture states
  its own values so that the offline proof never depends on the shipped defaults.

## Extending the fixture

Add patterns and queries in the same shape; keep texts neutral; keep each `expected` id present in `patterns`; keep
`k` at or above the longest `expected` list; add the new distances to `expected_distances` and keep every one at
least 0.1 from the floor or threshold it is compared with; check that no new word collides with an existing bucket
(`zlib.crc32(word.encode()) % 256`). The check fails loudly on an unknown id, a missing family, a stale distance, an
eroded margin or a bucket collision.
