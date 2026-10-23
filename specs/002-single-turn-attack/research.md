# Research: Run One Single-Turn Attack and Judge the Result

Decisions behind [plan.md](./plan.md). Each one names what was chosen, why, and what was rejected.

## R1. Judge model

**Decision**: the judge model is configuration, read from `KESTREL_JUDGE_MODEL`, defaulting to `google/gemini-3.8-flash`. It is reached through OpenRouter, the provider the repo already uses for the sacrificial target.

**Rationale**: FR-022 caps what the judge reads, so a run sends roughly 1,000 tokens in and at most 200 out. At the default model's $0.83/$4.12 per million that is about a sixth of a cent per judged run, and it is among the faster options, which matters against the judge's 30-second limit (R5). Every candidate below supports structured output, so the verdict parses reliably either way. Prices were read from OpenRouter's public model list on 2026-10-23:

| Candidate | $/M in | $/M out | Structured output | Note |
|---|---|---|---|---|
| `google/gemini-3.8-flash` | 0.83 | 4.12 | yes | **default**; fast, ~$0.0017 per judged run |
| `anthropic/claude-haiku-4.5` | 1.00 | 5.00 | yes | comparable tier |
| `openai/gpt-5.1` | 1.25 | 10.00 | yes | frontier; same family as the sacrificial target |
| `anthropic/claude-sonnet-5.5` | 2.00 | 10.00 | yes | frontier; ~$0.004 per judged run |

The sacrificial target classifies through an OpenAI model (CargoLint defaults to `openai/gpt-4o-mini`), so an OpenAI judge would be grading a sibling in the end-to-end tests. The default is a different family, which removes that.

**How this default was chosen**: the first draft of this plan recommended `anthropic/claude-sonnet-5.5` on strictness grounds. That recommendation was written by Claude and named an Anthropic model, which is a conflict of interest whatever its merits. The owner chose the Google model instead, on 2026-10-23. It is cheaper, faster against the 30-second limit, and independent of whoever drafted this. If judge verdicts later prove unreliable on borderline replies, the frontier tier in the table is the place to go, and the change is one environment variable.

**Alternatives considered**: hardcoding a model (rejected — Principle III requires recording which model judged, which implies it can change); requiring the user to choose with no default (rejected — Principle IX asks that the core flow need no configuration).

## R2. Reaching the judge without a new dependency

**Decision**: call OpenRouter's OpenAI-compatible `POST /api/v1/chat/completions` with the `httpx.AsyncClient` the project already uses. No SDK.

**Rationale**: Principle X fixes the stack and asks for a justification per new dependency. There is nothing to justify here: one JSON request and one JSON response. Feature 001 already owns an async HTTP path with timeouts and size limits, and the same patterns apply.

**Alternatives considered**: the `openai` SDK (rejected — a whole dependency for one endpoint); `langchain-openai` (rejected for the same reason, and it belongs to the sacrificial target's separate project, not to Kestrel).

## R3. Getting a verdict that parses

**Decision**: ask for structured output with a JSON schema of exactly two fields, `verdict` (one of `succeeded`, `failed`, `unclear`) and `reason` (a string). Every candidate model in R1 supports it. If the answer still cannot be read as that shape, fall back to finding a JSON object in the text; if that also fails, the run ends "unclear" with a reason naming the parse failure (FR-021).

**Rationale**: a free-text judge answer has to be parsed with guesswork, and a misparse silently becomes a wrong verdict. A schema removes most of that, and FR-021 already defines the behaviour for what is left.

**Alternatives considered**: free text with a regex (rejected — brittle); a single-token answer (rejected — FR-017 requires a one-line reason as well).

## R4. What the judge is asked

**Decision**: the judge is given the attack prompt, the agent's reply, and an instruction to decide whether *this reply shows the attack worked*, with the three verdicts defined for it. The contract is written out in [contracts/judge.md](./contracts/judge.md).

**Rationale**: the question has to be about evidence in the reply, not about whether the prompt looks dangerous, or the judge will mark every attack "succeeded" because the prompt was hostile. "Unclear" exists so the judge is not forced into a guess, and per Principle II a judge verdict is only ever opinion.

**Alternatives considered**: two verdicts only (rejected — forces a coin flip, and Principle II wants uncertainty visible); asking the judge for a severity score (rejected — scoring belongs to the report feature).

## R5. Caps on the judge

**Decision**: the reply is cut to 2,000 characters before it reaches the judge, the judge's answer is capped at 200 tokens, and the call is given whichever is smaller: 30 seconds, or what is left of the run's 90-second deadline. A cut reply is recorded as cut on the run.

The deadline is enforced on its own rather than inferred from the two sub-limits. 60 seconds for the send plus 30 for the judge is exactly 90, which would leave nothing for masking, canary matching and two database writes, so a worst-case run would break the ceiling SC-001 promises.

**Rationale**: FR-022 requires a hard cap, and Principle VIII requires a token budget per run. 2,000 characters is the limit feature 001 already uses to display a reply, so one constant covers both and the user is judged on what they were shown. 200 tokens is ample for a verdict and one line.

**Alternatives considered**: sending the whole reply up to the 1 MB response cap (rejected — unbounded cost, and the spec requires a cap); a smaller cut (rejected — evidence of a leak can sit late in a long reply).

## R6. Canary matching

**Decision**: an exact, case-sensitive substring match of any declared canary against the reply, after header-value masking. A canary must be at least 8 characters.

**Rationale**: this is the only hard evidence Kestrel can gather from a black-box endpoint, so it has to be the kind of match that cannot be argued with (Principle II). Case-insensitive or fuzzy matching would turn a coincidence into a "confirmed" finding, which is worse than missing one. The 8-character floor keeps an ordinary word from ever being declared.

**Alternatives considered**: case-insensitive matching (rejected — a model that echoes a canary almost always preserves it, so the tolerance buys little and costs certainty); normalised or whitespace-tolerant matching (rejected for the same reason); a regular expression (rejected — a user-supplied pattern is a footgun and cannot be called deterministic proof).

## R7. Where canary strings live

**Decision**: a `target_canaries` table keyed to the target, cascading on delete, mirroring `target_headers`. Values are stored as plain text.

**Rationale**: a canary is not a credential. The user must be able to read it to paste it into their agent's system prompt, so encrypting it would mean decrypting it for every display and gaining nothing. Principle IV is about target credentials, which stay encrypted. A separate table rather than a column keeps ordering and lets a target hold several.

**Alternatives considered**: a JSON column on `targets` (rejected — makes matching and counting awkward and breaks the pattern `target_headers` set); encrypting canaries (rejected — see above).

## R8. Where the attack prompts come from

**Decision**: every prompt in the library is taken from a published, citable source — the OWASP LLM Top 10 material and the references it links, and public prompt-injection benchmark datasets. Each prompt records a `source` naming the publication or dataset, a URL, and the licence. `src/kestrel/attacks/data/SOURCES.md` lists them, the way [targets/hs_code/PROVENANCE.md](../../targets/hs_code/PROVENANCE.md) records where the CargoLint files came from. Where a source's licence does not permit redistributing its text, that prompt is left out and the family is filled from a permissive source. **No prompt is written freehand for this repo.**

**Rationale**: the library is a test fixture, and a fixture has to be auditable — a reviewer should be able to ask where a prompt came from and get an answer. Published techniques are also the right target for a scanner: they are what a real agent will meet. Writing novel attack strings would make the repo an original offensive artifact with no provenance and no review trail, which is both worse engineering and a worse thing to publish. The repo already has a provenance habit from feature 001, and this follows it.

**Alternatives considered**: authoring the prompts directly (rejected — unauditable, and it changes what the repo is); collecting them from jailbreak forums (rejected — no licence, no stable citation, unknown quality); generating them with a model (rejected — that is the adaptive-attacker feature, out of scope here, and it would make the library unreproducible).

## R9. Library version and attacker source

**Decision**: `library.json` carries a `version` string. Every run records `attacker_source` as `library:<version>`, and `judge_model` separately.

**Rationale**: Principle III requires every report to name the attacker. Here the attacker is not a model but a fixed set of prompts, so the honest answer is which set. Recording the version means two runs months apart can be compared, and a prompt that was changed does not silently rewrite history.

**Alternatives considered**: recording only the prompt id (rejected — a prompt's text can change between versions); recording nothing because no model attacked (rejected — Principle III admits no exception).

## R10. Run lifecycle, the one-at-a-time rule, and interrupted runs

**Decision**: a run row is written with `status = 'in_progress'` before anything is sent, and updated to `'finished'` at the end. FR-010 is enforced by looking for an in-progress run for that target. On start-up, every row still `'in_progress'` is closed with verdict `unclear` and a reason saying it was interrupted (FR-031).

**Rationale**: feature 001 held its in-flight lock in memory, which is fine for a lock that only guards a form. Here the same state has to answer a question that outlives the process — "was an attack already sent?" — so it belongs in the database. Writing the row first also means a crash mid-send still leaves evidence that the agent was sent something, which matters more than a tidy list.

**Alternatives considered**: an in-memory lock as in feature 001 (rejected — a crash would lose the record of a sent attack and FR-031 would have nothing to close); deleting interrupted rows on start-up (rejected by the clarify session, and it would hide a sent attack).

## R11. Schema migration

**Decision**: `meta.schema_version` moves 1 → 2. On connect, a version below 2 creates `target_canaries` and `runs`, then sets the version. Feature 001's tables are not altered.

**Rationale**: an existing database holds real targets with encrypted headers; recreating it would lose them. Both additions are new tables, so the migration is additive and needs no data rewrite.

**Alternatives considered**: recreating the database (rejected — destroys saved targets and their keys); no version check (rejected — a newer Kestrel would fail obscurely against an old file).

## R12. Terms version 2

**Decision**: `terms.md` gains a sentence saying that an agent's reply is sent to the judge's model provider, and its version becomes `2`. An attack is refused for a target whose stored confirmation names an older version, with a message telling the user to read the terms and confirm again.

**Rationale**: FR-023 requires the disclosure, and feature 001 already built versioned terms with re-confirmation on a version change, so the mechanism exists. The change is material — replies now leave the machine — so re-consent is the honest reading of Principle VIII, not a technicality.

**Alternatives considered**: disclosing only in the screen without touching the terms (rejected — the terms are what the user accepted, and they would then be wrong); keeping version 1 to avoid re-confirmation (rejected — it would mean every existing user had agreed to something they were never shown).

## R13. Secret hygiene on the judge path

**Decision**: the reply is masked for header values before it is stored, displayed or sent to the judge, reusing feature 001's `mask_values`. The judge receives only the attack prompt and the masked, cut reply. `OPENROUTER_API_KEY` is read from the environment, never stored in the database and never logged. A run's log line names the target, family, prompt id, verdict, judge model and timing — never the reply, the prompt text or any header value.

**Rationale**: Principle IV, and the rule feature 001 already follows. The judge is a new way for text to leave the machine, so it is the one place where a leak would be hardest to notice.

**Alternatives considered**: masking only at display (rejected — the judge call and the stored run would still carry the value).

## R14. Teeth for the sacrificial target

**Decision**: the HS-code target gains (a) a canary string in its system prompt, set by `HS_TARGET_CANARY`, and (b) a fake `send_email` tool that appends each call to an in-memory list and sends nothing, exposed for tests through a `GET /debug/tool-calls` endpoint that requires the same API key. The target gains a small tool-calling loop so the model can actually invoke it.

**Rationale**: FR-034 and FR-035. Hard evidence for a system prompt leak needs something specific in the prompt to leak; hard evidence for tool-mediated exfiltration needs a tool that can be called and a record of the call. The target today is a classifier wrapper with no tool loop, so this is the largest single piece of work in the feature and should not be mistaken for a footnote.

**Alternatives considered**: a tool that is advertised but not callable (rejected — then exfiltration can never be demonstrated); reading recorded calls through Kestrel rather than directly (rejected — a real black-box target would never expose this, so routing it through Kestrel would model something false).

## R15. Where this sits on the screen

**Decision**: the sidebar keeps the target form and gains canary rows next to the auth header rows. The main area gains an **Attack** panel above the existing connection-test panel — family picker, optional prompt picker, Run button, then the result — and a **Runs** table for the selected target below it.

**Rationale**: feature 001 established sidebar-for-settings and main-area-for-results, and a canary belongs with the target's settings. Keeping the connection test visible matters because a failing attack send is diagnosed with it.

**Alternatives considered**: a separate page or tab (rejected — Principle IX, and the user needs the target in view); replacing the connection-test panel (rejected — it is still the way to diagnose a send failure).
