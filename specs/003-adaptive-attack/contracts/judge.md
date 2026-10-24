# Contract: the judge — feature 003 extension

The judge from [feature 002](../../002-single-turn-attack/contracts/judge.md) is reused unchanged except for one addition: a short "how close" note alongside the verdict, so each judge call in an adaptive run also steers the next attacker turn (R6). Single-turn runs (feature 002) are unaffected.

## Unchanged

- Model, configuration and limits: `KESTREL_JUDGE_MODEL` (default `google/gemini-3.8-flash`), key from `KESTREL_JUDGE_API_KEY` or `OPENROUTER_API_KEY`, the reply cut and the answer-token cap, the per-call timeout.
- Consulted only when no canary matched (Principle II).
- Receives only the attack content and the masked reply — never an auth header value, URL or target name (Principle IV).
- A judge verdict is opinion; a run judged this way is never shown as confirmed (Principle II).

## Added: the "how close" note

The judge's structured answer gains a third field, `progress`: one short line on how close the attempt came and what still blocks it. The schema becomes:

```json
{"verdict": "failed", "reason": "The agent refused and restated its task.",
 "progress": "The agent acknowledged the framing but did not reveal the protected text."}
```

- `verdict`: one of `succeeded`, `failed`, `unclear` (unchanged).
- `reason`: one line, Kestrel's words about the reply (unchanged).
- `progress`: one line, at most the same length cap as `reason`; may be empty. Shown as plain text; fed to the attacker's next turn.

`ParsedVerdict` gains an optional `progress` field. Reading the answer is as feature 002 — structured result first, then the first JSON object in the text, else the run falls back as before — with `progress` optional so a judge that omits it still parses.

## In an adaptive run

Each canary-less turn: the judge reads the conversation so far, returns `verdict` + `reason` + `progress`. A `verdict` of `succeeded` stops the run; anything else records the turn's `reason` and `progress`, hands `progress` to the attacker, and the loop continues while budget remains. The judge model is recorded on every run that used it (Principle III).

## In a single-turn run

Feature 002's path ignores `progress`: it still reads `verdict` and `reason` only, and stores them as before. No behaviour changes.
