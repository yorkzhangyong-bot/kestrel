"""The OWASP LLM Top 10 (2025) as report data: the three classes Kestrel's attack library covers, and the seven
it does not, each with an honest reason (feature 005, FR-006/007/008).

The `owasp_class` strings match the attack library's `owasp_category` labels exactly (see attacks/library.py), so
per-class run counts join without a lookup table. Reasons tie to the constitution: Principle I (security, not
quality) and Principle VIII (bounded harm, plain conversation only).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TestedClass:
    owasp_class: str          # matches Run.owasp_category exactly
    families: tuple[str, ...]  # the attack-library family keys that map to this class
    family_label: str          # a human label for the report's coverage table


# The three OWASP classes the current attack families map onto.
TESTED: tuple[TestedClass, ...] = (
    TestedClass("LLM01: Prompt Injection", ("direct_injection", "indirect_injection"),
                "direct & indirect prompt injection"),
    TestedClass("LLM06: Excessive Agency", ("tool_exfiltration",), "tool-mediated exfiltration"),
    TestedClass("LLM07: System Prompt Leakage", ("system_prompt_leak",), "system-prompt leak"),
)

# The seven OWASP classes outside the current attack library, each with why Kestrel does not test it yet.
UNTESTED: tuple[tuple[str, str], ...] = (
    ("LLM02: Sensitive Information Disclosure",
     "No dedicated data-exfiltration family yet; the current attacks target injection and prompt leakage, not "
     "broader sensitive-data disclosure."),
    ("LLM03: Supply Chain",
     "A deployment and dependency risk, not something a conversation with the running agent can probe."),
    ("LLM04: Data and Model Poisoning",
     "Concerns the agent's training and fine-tuning data, which a black-box chat attack cannot reach."),
    ("LLM05: Improper Output Handling",
     "Depends on how the host application consumes the agent's output downstream; not visible from the chat "
     "endpoint alone."),
    ("LLM08: Vector and Embedding Weaknesses",
     "Targets the agent's own retrieval and embedding store; Kestrel tests the agent, not its RAG internals."),
    ("LLM09: Misinformation",
     "A content-quality concern, which is out of scope by Principle I (security, not quality)."),
    ("LLM10: Unbounded Consumption",
     "Would require load or denial-of-service probing, which Principle VIII forbids (bounded harm, plain "
     "conversation only)."),
)
