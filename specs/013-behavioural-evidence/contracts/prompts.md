# Contract: the prompt-registry additions

Every model-facing and attack-planting wording lives in the versioned prompt registry (feature 009), never in
Python (FR-010, FR-028, FR-059). This contract fixes the **ids, placeholders, versions and lock obligations** of
the files this feature adds and changes; the wording itself is authored inside the prompt files in the
implementation PR and is not reproduced here (the same reason attack text never appears in a spec).

## Two new task templates

| File | Registry id | Placeholders | Purpose |
|------|-------------|--------------|---------|
| `src/kestrel/prompts/override_task.v1.md` | `override_task` | `{first_part}`, `{second_part}` | the **injected override itself**: a short paragraph that claims to supersede the agent's own operating instructions and, on that claimed authority, requires the two token parts joined (FR-064). It carries the parts separately with **at least one alphanumeric word between them** (FR-009), and the joined form must not appear anywhere in it. Its front-matter additionally carries a `framing: override` field a test asserts (SC-014). |
| `src/kestrel/prompts/callback_task.v1.md` | `callback_task` | `{callback_url}` | one short paragraph, **appended to the opening message in the user's voice**, that gives the agent the planted URL and a plausible reason to reach it (FR-028). |

Rules the files and their use honour:

- The front-matter is the standard two lines (`id`, `version`) plus, for the override template only, an optional
  third `framing` key. The registry is extended in the implementation PR to allow that one optional key
  (`prompt_registry.parse_prompt_file`/`PromptFile`/`format_prompt_file` — T015), so the files still appear on
  `GET /api/config` among the prompt versions. A test asserts the override template's `framing` is present and set
  to `override`, so the "claims to supersede" property is a non-text, structural check (SC-014), while the wording
  that realises it is a reviewed property listed in `traceability.md` for the implementation PR's reviewer.
- `override_task_paragraph(token)` fills `{first_part}`/`{second_part}` with the run's two parts and returns
  `(paragraph, "override_task@N")`; `callback_task_paragraph(url)` fills `{callback_url}` and returns
  `(paragraph, "callback_task@N")`. `N` is the active (highest) version; the run records it on
  `run_planted_tokens.prompt_version` (FR-010, FR-028).
- **Where the override paragraph goes is recorded in a Kestrel-owned sidecar, not the template** (FR-064). A
  sidecar file `src/kestrel/attacks/data/insertion_points.json` keys each direct-injection and indirect-injection
  seed's prompt id to an insertion point: a character offset into the seed's verbatim library text plus a sha256
  fingerprint of that text. A direct seed's point is the attacker-voice position (the paragraph follows its text);
  an indirect seed's point sits **inside its own simulated injected content**, so the instruction reaches the agent
  as retrieved data rather than as a request from its user. `place_task(seed_text, insertion, paragraph)` performs
  the substitution, and adaptive turn 1 uses the same seed and therefore the same insertion point. The library text
  stays verbatim (the 002 contract); a test fails when an indirect seed has no entry, an offset is out of range, or
  a fingerprint no longer matches the library text. A seed of a family that carries no task has no entry and is
  sent unchanged. The callback task is the exception: it is **appended to the opening message in the user's voice**
  (no insertion point), because it is a request to the agent, not simulated retrieved data.
- Because the template guarantees a word between the two parts, no normalisation of a sent message (stripping
  whitespace, punctuation or formatting) can produce the joined form; the echo-proofness test and the disarm check
  both run on the normalised text (FR-009, FR-012).
- Each must be recorded in `src/kestrel/prompt_versions.lock.json` with `uv run python scripts/bump_prompt.py
  override_task --lock` (and the same for `callback_task`); `verify_lock()` / `tests/unit/test_prompt_guard.py`
  fail the suite until the lock pins them. A brand-new id is recordable because `scripts/bump_prompt.py`'s
  `record()` does `lock.setdefault(prompt_id, {})`.
- `strip_planted_tasks(text, task_text)` removes the run's **exact filled task text** — the one known string that
  run planted, wherever it sits — by literal removal rather than a paragraph-anchored regex, from any text bound
  for the experience store or the retrieval query (FR-063). Because it is keyed on the run's own filled string, it
  works wherever the task was placed and needs no knowledge of the template's versions.
- Stripping the template is **not sufficient on its own**: `scrub_planted_values(text, values)` additionally
  replaces the run's own planted values — each token part, the joined form and the callback URL — wherever else
  they appear, because a later attacker message or a judge progress note can repeat them (FR-063, research D11).
  Both run together at every experience-store and retrieval-query boundary.

## Three attacker-prompt bumps

The three families that carry a planted task get their attacker prompt bumped so an adaptive run actually pursues
the planted marker instead of dropping it after turn 1:

| Registry id | New version | What the new version adds (behaviourally — the exact wording is authored in the file) |
|-------------|-------------|---------------------------------------------------------------------------------------|
| `attacker:direct_injection` | `2` | keep steering the agent toward producing the joined marker the opening message asked for; never write the joined marker yourself |
| `attacker:indirect_injection` | `2` | the same marker guidance, in this family's indirect framing |
| `attacker:tool_exfiltration` | `2` | keep steering the agent toward reaching the address the opening message supplied, writing the placeholder `[callback-url]` wherever that address belongs; never invent an address |

Rules:

- Each bump is a new `attacker_<family>.v2.md` created by `scripts/bump_prompt.py attacker:<family>` then edited,
  then `--lock`. The v1 files stay as the non-active versions an A/B arm can still pin (feature 009 US4).
- The attacker still receives no token, no real URL and no correlation id; the conversation it is given has every
  callback URL replaced by `[callback-url]` (FR-031, FR-049). The marker guidance is phrased against the
  placeholder, never a concrete value. When an attacker message comes back containing the placeholder, Kestrel
  substitutes the run's real URL into the text it **sends and stores**, while the attacker's and the judge's view
  keeps the placeholder (FR-070) — without that substitution a stateless target could only ever receive the URL on
  turn 1.
- When a run planted no URL — the listener is off, or the base URL was refused for this target (FR-068) — the
  attacker prompt carries no callback guidance, and a `[callback-url]` placeholder the attacker still writes is
  sent **unchanged as inert text**, with no substitution. The run's `callback_note` records a reason only for the
  FR-068 base-unusable refusal (and the FR-069 replay case); when the listener is simply off, that is the ordinary
  configured-off state and no note is set (`contracts/api.md`).
- The prompts stay neutral and behavioural, carry no target identity, and contain no destructive or canary
  content (the hard rule and Principle IV).

## Named test changes (feature 009's own pins)

- `tests/integration/test_config_prompts.py`: `EXPECTED_IDS` gains `override_task` and `callback_task`; the
  `all(version == "1")` assertion relaxes to accept `"2"` for the three bumped attacker ids while the two task ids
  and the unbumped `judge`/`recommender` stay `"1"`.
- `tests/integration/test_prompt_no_secrets.py`: `EXPECTED_IDS` (checked against the lock) gains the two task ids.
- `tests/unit/test_prompt_guard.py`: stays green once the lock records the five new/bumped files.
