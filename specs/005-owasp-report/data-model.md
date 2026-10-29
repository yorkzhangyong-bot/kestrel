# Data Model: OWASP-Mapped, Fix-Ready Report (feature 005)

The report reads existing data; the only new persistence is a recommendation cache. No Chroma change (read-only).

## SQLite (schema v5, additive)

`meta.schema_version` moves `4 → 5`. Migration allows `1`/`2`/`3`/`4` → `5`; the new table is created by the schema script (`CREATE TABLE IF NOT EXISTS`), so there are no column `ALTER`s this time. An unknown version still raises `UnknownSchemaVersion`.

### `report_recommendations` — new table

One cached recommendation per run (FR-012 caching).

| Column | Type | Notes |
|---|---|---|
| `run_id` | `INTEGER PRIMARY KEY` | FK → `runs(id)` `ON DELETE CASCADE`; one recommendation per run, removed with the run/target. |
| `recommendation` | `TEXT NOT NULL` | The model's suggested fix text (shown labelled as a suggestion). |
| `model` | `TEXT` | The judge model that produced it (provenance). |
| `created_at` | `TEXT NOT NULL` | ISO-8601 UTC. |

New store methods:

- `get_recommendation(run_id) -> (recommendation, model) | None`
- `save_recommendation(run_id, *, recommendation, model) -> None` (idempotent `INSERT OR REPLACE` / `upsert` on `run_id`)

No other table changes. Everything else the report needs — targets (incl. `description`), runs (verdict, `hard_evidence`, reason, attacker/judge models, budgets, usage, stopping condition, `succeeded_turn`), `run_turns` (attacker messages, replies, judge notes), canaries — already exists from features 001–004.

## In-memory report model (`report/model.py`, pure)

`build_report(...)` returns a `ReportModel` dataclass; the renderers consume only this.

- **ReportModel**
  - `header`: target name, purpose description (or None), generation time, run count, the distinct attacker and judge models across the runs, the token budget and total tokens used.
  - `coverage`: list of **CoverageRow**.
  - `findings`: list of **Finding** (one per succeeded run; empty if none).
  - `other_runs`: list of **OtherRun** (each failed/unclear/unfinished run, one line).
  - `limitations`: the closing note text (includes the memory/pattern caveat and, when available, the experience counts).
  - `is_empty`: true when the target has no runs (drives the empty state).

- **CoverageRow**: `owasp_class` (e.g. "LLM07: System Prompt Leakage"), `families` (the family label(s)), `run_count`, `result` (e.g. "N run(s), 1 confirmed finding" / "N run(s), held" / "not run yet").

- **Finding** (per succeeded run): `family`, `owasp_class`, `winning_message` (attacker turn(s) up to and including `succeeded_turn`, or the seed prompt for a single-turn/turn-one success), `evidence` (the verbatim canary evidence) **or** `judge_note` (with a "suspected" marker), and `recommendation` (text + a suggestion label, or a "no recommendation available" note when no judge key).

- **OtherRun**: `family`, `when`, `verdict` (failed/unclear), `stopping_condition`.

- **UntestedClass** (from `owasp.py`): `owasp_class`, `reason`.

## OWASP reference data (`report/owasp.py`)

Fixed OWASP LLM Top 10 (2025). Tested classes map to families via each run's stored `owasp_category`:

| OWASP class | Families Kestrel uses |
|---|---|
| LLM01: Prompt Injection | direct injection, indirect injection |
| LLM06: Excessive Agency | tool-mediated exfiltration |
| LLM07: System Prompt Leakage | system-prompt leak |

Untested (each with a one-line reason): **LLM02** Sensitive Information Disclosure, **LLM03** Supply Chain, **LLM04** Data and Model Poisoning, **LLM05** Improper Output Handling, **LLM08** Vector and Embedding Weaknesses, **LLM09** Misinformation, **LLM10** Unbounded Consumption.

## Relationships

- A `Finding`/recommendation ↔ one `runs` row (by `run_id`); the cached recommendation is deleted with the run (cascade) and hence with the target.
- The report reads, never writes, the experience store (ChromaDB) for the memory/pattern counts in the limitations note.
