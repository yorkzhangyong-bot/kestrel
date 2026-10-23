# Research: Run a Multi-Turn Adaptive Attack and Judge the Result

Decisions behind [plan.md](./plan.md). Each names what was chosen, why, and what was rejected. No attack prompt text appears here; this records architecture and configuration only.

## R1. Attacker model

**Decision**: the attacker model is configuration, read from `KESTREL_ATTACKER_MODEL`, defaulting to `deepseek/deepseek-v3.2`, reached through OpenRouter.

**Rationale**: the attacker has to read a conversation and reason out a better next message, so a full chat model is wanted, not a small "flash" variant. DeepSeek's chat models are capable, inexpensive, and comparatively unrestricted, which suits a red-team attacker. Prices read from OpenRouter's public model list on 2026-10-24 (USD per 1M tokens):

| Candidate | $/M in | $/M out | Context | Note |
|---|---|---|---|---|
| `deepseek/deepseek-v3.2` | 0.28 | 0.42 | 163840 | **default**: current stable chat model, cheap output, capable |
| `deepseek/deepseek-v3.2-exp` | 0.27 | 0.41 | 163840 | experimental track; avoided as a default |
| `deepseek/deepseek-chat-v3.1` | 0.25 | 0.95 | 163840 | capable, dearer output |
| `deepseek/deepseek-v4-flash` | 0.09 | 0.18 | 1048576 | cheapest, but a smaller model, weaker at multi-turn reasoning |

A specific id is pinned rather than the moving `deepseek/deepseek-chat` alias, so a run's recorded attacker is reproducible (Principle III). Output price matters most here, because the attacker's own messages are the output and there are up to six of them per run; `v3.2` has the cheapest output among the full models.

**Alternatives considered**: a Qwen model (sound, similar profile — the clarify fallback, kept as a documented alternative); a frontier aligned model (rejected — more restricted, a weaker attacker, against the point of red-teaming); a flash model (rejected — the attacker needs reasoning, not just speed).

## R2. Judge model

**Decision**: the judge stays `google/gemini-3.8-flash`, read from the existing `KESTREL_JUDGE_MODEL`, reused from feature 002 unchanged.

**Rationale**: the judging job is the same as feature 002 — read a conversation and decide succeeded/failed/unclear — so the same judge serves. Keeping one judge env var means a run's judge is recorded and configured exactly as before.

**Alternatives considered**: a separate adaptive-judge model (rejected — needless divergence; the task is identical).

## R3. The three caps and their defaults

**Decision**: a run is bounded by three caps, whichever is reached first, all configurable:

| Cap | Env var | Default | Why this default |
|---|---|---|---|
| Turns | `KESTREL_ADAPTIVE_MAX_TURNS` | 6 | Clarified with the owner. Enough to adapt, modest cost. |
| Token budget | `KESTREL_ADAPTIVE_TOKEN_BUDGET` | 40000 | Covers six turns of growing conversation across attacker and judge calls, with headroom, while cutting a runaway model. At the chosen models that is well under five cents per run. |
| Wall-clock | `KESTREL_ADAPTIVE_TIME_LIMIT_S` | 300 | A backstop against a stalled run. Per-call timeouts (R5) are the first guard; this stops a run where calls are pathologically slow. |

**Rationale**: Principle VIII requires a hard cap on turns and token budget; a wall-clock backstop was added so a hung provider cannot hold a run open. The token budget counts only Kestrel's own calls — the attacker and the judge — not the target's tokens, which are the user's agent's cost.

**Alternatives considered**: turns-only (rejected at clarify — unbounded token cost); a per-run money ceiling (rejected — needs cost tracking this feature does not have; the token budget is the proxy).

## R4. Everything configurable through the environment

**Decision**: both models and all three caps are environment settings with defaults, mirroring feature 002's judge configuration, so feature 006's A/B experiments can vary them without code changes:

- `KESTREL_ATTACKER_MODEL`, `KESTREL_ATTACKER_API_KEY` (falling back to `OPENROUTER_API_KEY`), `KESTREL_ATTACKER_BASE_URL` (default `https://openrouter.ai/api/v1`).
- `KESTREL_JUDGE_MODEL` (existing), `KESTREL_JUDGE_API_KEY` / `OPENROUTER_API_KEY` (existing).
- `KESTREL_ADAPTIVE_MAX_TURNS`, `KESTREL_ADAPTIVE_TOKEN_BUDGET`, `KESTREL_ADAPTIVE_TIME_LIMIT_S`.

**Rationale**: the A/B harness compares attackers and budgets; reading them from the environment lets a run be configured per experiment with no redeploy. Each run records the values it used (Principle III), so an experiment's runs are self-describing.

## R5. The attacker/judge loop as a LangGraph graph

**Decision**: the loop is a LangGraph `StateGraph`. The state holds the target's resolved settings, the target's canaries, the conversation so far, the running token and turn counts, the deadline, and the latest judge note. Nodes: **attacker** (produce the next message from the conversation and the last judge note), **send** (one request to the target via feature 002's tester), **evidence** (canary check), **judge** (verdict plus a "how close" note, only when no canary matched), **decide** (stop on success or a cap, else loop). The model calls inside the attacker and judge nodes are plain `httpx` calls to an OpenAI-compatible endpoint, as feature 002's judge does — LangGraph orchestrates, it does not make the calls.

**Rationale**: Principle X fixes LangGraph in the stack and the feature requires a graph; building it here sets the pattern later multi-node features extend. Keeping the model calls on `httpx` means no model SDK enters Kestrel and the attacker client mirrors the judge client exactly.

**Alternatives considered**: a plain `while` loop (rejected — diverges from the fixed stack and from the diagram, rewritten at the first branch); LangChain agent abstractions (rejected — heavier than needed; the nodes are small and explicit).

## R6. The judge's "how close" note

**Decision**: the judge's structured answer gains a short `progress` note — one line on how close the attempt came and what still blocks it. `ParsedVerdict` gains an optional `progress` field; the adaptive loop feeds the latest note to the attacker as the signal for its next turn. Single-turn runs (feature 002) ignore the field, so their behaviour is unchanged.

**Rationale**: the judge is already reading the whole conversation each turn; having it also say how close the attempt came means the call is not wasted and the attacker adapts on evidence rather than guessing. The note is capped in length like the reason, and shown as plain text.

**Alternatives considered**: a second model call for coaching (rejected — doubles cost; the judge already has the context); letting the attacker self-assess (rejected — the judge is the independent signal, and self-assessment wastes the judge call that already happened).

## R7. Enforcing the token budget

**Decision**: each attacker and judge response's `usage.total_tokens` is summed into a running total on the run. Before each turn, the loop stops if the turn cap, the token budget, or the deadline has been reached; after each call the total is updated. A run that stops this way records which cap it hit (FR-012).

**Rationale**: OpenRouter returns token usage per call, so the budget is measured, not estimated. Checking before each turn (rather than before each call) is simple and safe: the overshoot is at most one turn's calls, and the per-call token caps bound that.

**Alternatives considered**: a tokenizer estimate before each call (rejected — an extra dependency and still approximate; measured usage is exact and free).

## R8. What the attacker receives

**Decision**: the attacker model receives only the conversation so far (its own messages and the target's masked replies) and the latest judge note. It never receives the target's auth header values, URL, name or any other stored setting (Principle IV).

**Rationale**: the same secret-hygiene rule as feature 002's judge, applied to the new model on the path. The attacker needs the conversation to adapt; it needs nothing that identifies or authenticates the target.

## R9. Storage: schema version 3

**Decision**: `meta.schema_version` moves 2 → 3. `runs` gains `mode` (default `single_turn`), `attacker_model`, `token_budget`, `tokens_used`, `turn_budget`, `turns_used`, `time_limit_s`, `stopping_condition` and `succeeded_turn`. A new `run_turns` table holds the conversation: `run_id` (FK, cascade), `position`, `attacker_message`, `reply_text`, `reply_truncated`, `judge_verdict`, `judge_reason`, `judge_progress`, `created_at`. The migration is additive; existing feature-002 rows become `mode = 'single_turn'` with null adaptive fields.

**Rationale**: a child table matches the existing style (`target_headers`, `target_canaries`) and keeps turns ordered and queryable. Single-turn runs keep storing their single prompt and reply on the run row as before and write no `run_turns`; adaptive runs write one `run_turns` row per turn.

**Alternatives considered**: a JSON conversation blob on the run (rejected — harder to query and inconsistent with the table style); a separate `adaptive_runs` table (rejected — single-turn and adaptive are one kind of run listed together, so one `runs` table with a `mode` is simpler).

## R10. Masking and cutting the conversation

**Decision**: every target reply is masked for the target's auth header values and cut to the feature-002 reply length before it is stored, judged, or shown — reusing feature 002's masking and cut. Attacker messages are masked the same way before storage and display, in case a reply's masked content is quoted back.

**Rationale**: Principle IV, applied to the whole conversation. Reusing the existing masking keeps one rule and one implementation.

## R11. Terms of service version 3

**Decision**: an adaptive run sends the target's replies to the **attacker** model's provider as well as the judge's. The terms of service gain a sentence saying so, and their version becomes `3`; a target whose stored confirmation names an older version is re-confirmed before it can be attacked, exactly as feature 002 did for version 2 (feature 001's re-confirmation mechanism).

**Rationale**: feature 002's terms v2 disclosed that replies go to the judge's provider. Adaptive runs add a second provider — the attacker's — that also sees the replies. That is a material change, so honesty (and the consent model behind Principle VIII) calls for disclosing it and re-confirming, not slipping it in.

**Alternatives considered**: disclosing only in the screen (rejected — the terms are what the user accepted and would then be incomplete); reusing version 2 (rejected — it would mean users had agreed to something they were never shown).

## R12. Secret hygiene on the attacker path

**Decision**: the attacker call is built like the judge call — the key rides the `Authorization` header, never the body; the request carries only the conversation and the judge note; the run's log line names the target, mode, verdict, attacker and judge models, turns and duration, never a message, a reply, a note or a header value. A new model on the path is the one place a leak would be hardest to notice, so the T0-review task checks it explicitly.

**Rationale**: Principle IV, and the rule feature 002 already follows for the judge.

## R13. Reusing feature 002

**Decision**: the permission and terms gates, the connection tester (`run_test`, including the `prompt` parameter added in feature 002), canary matching (`match_canary`), the judge client, reply masking and cutting, run claiming/finishing, the start-up sweep, run listing and deletion, and the sacrificial HS-code target are all reused unchanged. Feature 003 adds the attacker client, the graph, the caps and the conversation storage/display on top.

**Rationale**: Principle VII (thin slice) — the new surface is only what adaptive attacks genuinely need. Everything feature 002 already proved is reused, not rebuilt.
