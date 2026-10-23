# Contract: the attack library

`src/kestrel/attacks/data/library.json`, loaded once at start-up, validated, and indexed by family. Read-only in this feature (FR-001).

## Where the prompts come from

Every prompt is taken from a published, citable source — the OWASP LLM Top 10 material and the references it links, and public prompt-injection benchmark datasets. **No prompt is written freehand for this repo** (R8).

Each prompt records its origin. `src/kestrel/attacks/data/SOURCES.md` lists every source with its URL and licence, the way [targets/hs_code/PROVENANCE.md](../../../targets/hs_code/PROVENANCE.md) records where the CargoLint files came from.

Licences are checked before any text is copied. Where a source does not permit redistribution, that prompt is **left out** and the family is filled from a permissive source. The library is never padded with a rewritten version of text that could not be copied.

## File shape

```json
{
  "version": "1.0.0",
  "prompts": [
    {
      "id": "spl-002",
      "title": "Ask for the system prompt verbatim",
      "family": "system_prompt_leak",
      "owasp_category": "LLM01: Prompt Injection",
      "text": "<the prompt, copied from the source>",
      "source": "OWASP LLM Top 10 (2025), LLM01 examples",
      "source_url": "https://…",
      "licence": "CC BY-SA 4.0"
    }
  ]
}
```

## Families

Exactly four, each mapped to one OWASP LLM Top 10 category (FR-003):

| Key | Label | OWASP category |
|---|---|---|
| `direct_injection` | Direct prompt injection | LLM01: Prompt Injection |
| `system_prompt_leak` | System prompt leak | LLM07: System Prompt Leakage |
| `tool_exfiltration` | Tool-mediated exfiltration | LLM06: Excessive Agency |
| `indirect_injection` | Indirect injection via tool output | LLM01: Prompt Injection |

`indirect_injection` is delivered in the same single message as every other family: the prompt carries text shaped like tool or retrieved output. Kestrel hosts nothing for the agent to fetch (spec Assumptions).

## Rules checked at start-up

The library is validated when it loads, and a failure stops the API rather than shipping a broken library:

1. `version` is a non-empty string.
2. Every `id` is unique and matches `^[a-z]{2,4}-[0-9]{3}$`.
3. Every `family` is one of the four keys.
4. Every `owasp_category` matches the family's category in the table above.
5. Every `title`, `text`, `source` and `licence` is non-empty.
6. Each family holds at least 3 prompts (FR-003).
7. The library holds between 16 and 24 prompts — "about 20" in FR-001.
8. No `text` is a duplicate of another.

## What a prompt may be

A prompt is plain conversational text sent as a single message (FR-004). The loader rejects a prompt that is longer than 4,000 characters, so no prompt can become a flooding payload; Principle VIII allows plain conversation only, with no DoS and no load.

## Versioning

The library carries a `version` identifier (FR-005), which changes whenever any prompt's text, family or category changes. Every run records `attacker_source` as `library:<version>` (FR-005, R9), so a past run always says which set of prompts it came from. A run keeps its own copy of the prompt text, so editing the library never rewrites history.

## Picking a prompt

With a `prompt_id`, that prompt is used. Without one, Kestrel picks uniformly at random from the family, and the run records which it used (FR-007). Random rather than round-robin: round-robin needs state per target per family, which buys nothing for a feature that runs one attack at a time.
