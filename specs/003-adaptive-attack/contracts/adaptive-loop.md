# Contract: the adaptive attack loop

The attacker/judge loop is a LangGraph `StateGraph` (Principle X, research R5). This describes its state, nodes and transitions — behaviour and architecture only, no attack text. LangGraph orchestrates; the attacker and judge model calls are plain `httpx` calls ([attacker.md](./attacker.md), [judge.md](./judge.md)).

## State

Carried through the graph for one run:

- `resolved` — the target's connection settings with header values filled (feature 002's `ResolvedSettings`).
- `canaries` — the target's declared canary strings.
- `conversation` — the ordered turns so far (attacker message + masked reply + per-turn judge fields).
- `last_progress` — the judge's most recent "how close" note, or empty on turn one.
- `turns_used`, `tokens_used` — running counts.
- `deadline` — the monotonic time the run must stop by.
- `budgets` — turn cap, token budget, time limit (from settings).
- `outcome` — set when the run ends: verdict, hard-evidence flag, reason, stopping condition, succeeded turn.

## Nodes

| Node | Does | Notes |
|---|---|---|
| **attacker** | Produces the next message from `conversation` + `last_progress`. Turn one uses the library seed instead of calling the model. | Adds the call's tokens to `tokens_used`. On attacker failure → outcome `attacker_failed`, end. |
| **send** | Sends one request to the target via feature 002's tester, with the attacker message as the prompt. | On a failed send → outcome with the failure step, `stopping_condition = send_failed`, end. Masks and cuts the reply (feature 002). |
| **evidence** | Checks the masked reply for any canary (feature 002's `match_canary`). | A match → outcome `succeeded`, hard evidence, `succeeded_turn` = this turn, end. |
| **judge** | Only when no canary matched: verdict + reason + progress over the conversation. | Adds the call's tokens. `succeeded` → outcome `succeeded` (judge), end. Sets `last_progress`. |
| **record** | Appends the turn to `conversation`/`run_turns`; increments `turns_used`. | |
| **decide** | If a cap is reached, end with the last verdict and the matching `stopping_condition`; else loop to **attacker**. | |

## Transitions

```text
start → attacker → send → evidence ──canary?──► end (succeeded, hard evidence)
                             │ no canary
                             ▼
                           judge ──succeeded?──► end (succeeded, judge)
                             │ failed / unclear
                             ▼
                          record → decide ──cap reached?──► end (failed/unclear, which cap)
                                      │ budget remains
                                      └──────────────► attacker (next turn)
```

## Caps (checked in `decide`, before the next turn)

The loop stops before starting a turn when any of the three is reached (FR-010, FR-011, FR-012):

- `turns_used >= turn_budget` → `stopping_condition = turn_cap`.
- `tokens_used >= token_budget` → `stopping_condition = token_budget`.
- now `>= deadline` → `stopping_condition = time_limit`.

When a cap stops the loop, the run's verdict is the last turn's verdict (`failed` or `unclear`); a cutoff is never recorded as success.

## Guarantees

- `hard_evidence` is set only by the **evidence** node (a canary), never from a judge answer (Principle II).
- Every ended run has an `outcome` with a verdict or a failure step and a `stopping_condition` (FR-002-style completeness; SC-002).
- The attacker and judge receive only the conversation and the judge note — no header value, URL or target name (Principle IV, R8, R12).
- Interrupted runs (process stopped mid-loop) are closed by feature 002's start-up sweep as `unclear` / `interrupted`, keeping the turns already recorded.

## Testing the loop offline

The graph is tested with a stub attacker, a stub judge and a stub sender (as feature 002 tests `runs.py`): a canary at some turn ends the run at that turn with no judge call; a stub judge returning `succeeded` ends the run; stubs that never succeed drive the loop to each cap in turn (turn, token, time) and assert the recorded `stopping_condition`; a stub attacker that raises ends the run `attacker_failed`. No network and no model in the unit tests.
