# Kestrel Constitution

Kestrel is a hosted red-teaming platform for tool-using AI agents.
A user registers an agent endpoint (URL plus optional headers), Kestrel runs adaptive attacks
against it, judges the outcomes with hard evidence where possible, and produces a report mapped
to the OWASP LLM Top 10 with a risk score.

Primary user: a vibe coder who built an agent with Cursor, Claude Code or Lovable and has done
no security testing.

## Core Principles

### I. Scope is security, not quality

The MVP tests whether an agent can be made to misbehave (prompt injection, tool abuse, data
exfiltration).
Quality metrics are out of scope, but the architecture must not block adding them later.

### II. Hard evidence over opinion

A finding is only "confirmed" when there is deterministic proof: a canary token in a tool
argument or response, or a forbidden tool actually invoked.
LLM-judge verdicts alone are "suspected".

### III. Every report states the attacker model

Attack success rate depends on the attacker (DeepSeek / Qwen); the report must name model,
version and budget used.

### IV. Secrets never leave the vault

Target credentials are stored encrypted, never logged, never written into reports or
vector-store metadata.

### V. Learn from every run

Each run writes back to the ChromaDB store: successes and failures, tagged by target, attack
family and OWASP category.
A run that does not write back is a bug.

### VI. OWASP-mapped, fix-ready findings

Every finding maps to the OWASP LLM Top 10 and is structured so a "fix" action can be attached
later (hardened prompt, guardrail config, re-scan).

### VII. Tests first, thin slices

Each feature ships as a vertical slice (UI → API → agent → store) with unit tests before
implementation and one end-to-end test against the HS-code sacrificial target.

### VIII. Only attack what you own or are permitted to

- Layer 1, responsibility: when registering a target the user must tick
  "I own this agent or have written permission"; the tool refuses to scan without this flag,
  and the terms of service put liability on the user.
- Layer 3, bounded harm: attacks are plain conversation only (no DoS, no load), every run has
  a hard cap on turns and token budget.
- Layer 2, ownership verification via a code placed in the target's system prompt, is phase two.

### IX. Simple enough for a vibe coder

The primary user pastes a URL and reads a report; no YAML, no CLI required for the core flow.
The MVP is single-user with no login or account system; user auth (Clerk / Supabase Auth) is
added only at public launch.

### X. Stack is fixed for the MVP

Python 3.12, FastAPI, LangGraph, ChromaDB, Streamlit, uv, pytest.
New dependencies need a one-line justification in the plan.

## Governance

Amendments require a version bump and an updated Last Amended date.
Versions follow semantic versioning (MAJOR.MINOR.PATCH):

- MAJOR: a principle or governance rule is removed, or redefined in a backward-incompatible way.
- MINOR: a principle or section is added, or existing guidance is materially expanded.
- PATCH: clarifications, wording or typo fixes that do not change meaning.

Every implementation plan checks compliance with these principles in its Constitution Check gate.

**Version**: 0.1.0 | **Ratified**: 2026-10-23 | **Last Amended**: 2026-10-23
