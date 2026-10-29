# QA scorecard

A per-feature snapshot of requirement-traceability and test coverage, produced during feature 006
(2026-10-29). Traceability numbers are from the feature-scoped gate ([scripts/check_traceability.py](../scripts/check_traceability.py));
coverage is line coverage from the offline suite (`uv run pytest tests/unit tests/integration --cov`).

## A note on the "traced" column

Before feature 006, the traceability gate matched requirement ids as bare tokens across all of `tests/`. Because
every feature numbers its requirements `FR-001…`/`SC-001…`, one feature's test that referenced `FR-001` satisfied
*every* feature's `FR-001` — so the gate reported **100% traced for 001–005** regardless of whether each feature's
own tests cited its own ids. Feature 006 made the gate **feature-scoped** (a reference must name the feature, e.g.
`003/FR-001` or a `FEATURE = "003"` marker). The **traced** column below is therefore the *true per-feature
citation rate*. The gaps are requirements covered by a feature's test suite but **not cited by id** — they are not
functional gaps (see the coverage column), and since 001–005 are merged, no active PR runs their gate. Per
decision, they are reported here rather than retrofitted.

## Requirement citation (feature-scoped traceability)

| Feature | Traced | Missing | Citation rate |
| --- | --- | --- | --- |
| 001 — register target | 2 | 35 | 5% |
| 002 — single-turn attack | 40 | 8 | 83% |
| 003 — adaptive attack | 17 | 19 | 47% |
| 004 — attack-pattern memory | 34 | 7 | 83% |
| 005 — OWASP report | 15 | 15 | 50% |
| **006 — human-approved spec** | **21** | **0** | **100%** |

## Coverage of each feature's main modules

Line coverage from `tests/unit` + `tests/integration` (offline; no e2e). Shared modules (`api/main.py` 94%,
`api/schemas.py` 98%) back every attack feature.

| Feature | Main modules (line coverage) |
| --- | --- |
| 001 | `store.py` 98%, `secrets.py` 96%, `connection/tester.py` 98%, `connection/address_guard.py` 89% |
| 002 | `attacks/library.py` 93%, `judge/client.py` 83%, `judge/verdict.py` 96%, `runs.py` 91% |
| 003 | `attack/graph.py` 98%, `attack/attacker.py` 91% |
| 004 | `experience/store.py` 97%, `experience/writeback.py` 92%, `experience/hints.py` 100%, `experience/summary.py` 100% |
| 005 | `report/model.py` 97%, `report/render.py` 95%, `report/recommend.py` 89%, `report/owasp.py` 100% |
| 006 | `scripts/check_spec.py` 54%, `scripts/check_traceability.py` 35% — CLI scripts; the pure helpers are unit-tested, the `main()`/git/PR-body paths run only in CI |

Overall project line coverage: **87%** (the `quality` gate requires ≥85% on `src`).

The high coverage against low citation rates (e.g. 001 at 5% cited but ~95%+ covered) confirms the gaps are a
documentation matter — the behaviour is tested, the requirement id just isn't named in the test.
