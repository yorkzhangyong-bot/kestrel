# Evaluation reports

Each run of the evaluation tool (`uv run pytest -m judge_eval`) writes one timestamped markdown report per
evaluation:

- `judge-eval-<YYYYmmdd-HHMMSS>.md` — the judge-accuracy evaluation against the golden set
  (`tests/eval/judge_samples.json`), named per judge prompt version, with the per-family confusion and the
  production-faithful recall gate (0.80).
- `retrieval-eval-<YYYYmmdd-HHMMSS>.md` — the retrieval (RAG) evaluation over the seeded temporary store:
  recall@k, mean distances and the floor/dedupe drops per family.

Reports are committed deliberately: they are the measurement history. They carry numbers, ids and versions only —
never attack or reply text (CLAUDE.md's hard rules).
