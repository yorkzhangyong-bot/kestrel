# AI Agent Red-Teaming Platform: Competitive Analysis and Positioning

Capstone proposal · Yong Zhang · Turing College AI Engineering · 16 October 2026

## Project positioning

An automated red-teaming platform for **tool-using AI agents**. The user registers an agent endpoint, an attacker agent adaptively generates attacks, a judge scores the outcomes, and the platform produces an assessment report with a risk score mapped to the OWASP LLM Top 10.

Core narrative: bring the methodology of a senior test engineer (test-case management, regression suites, pass-rate trends, CI integration) into AI security. Most existing tools were built by security researchers, and this engineering discipline is exactly what they lack.

First target: the HS-code matching agent built in the Spring sprint. Second wave of targets: classmates' Capstone agents (with prior authorisation).

## Open-source tool comparison

All free, MIT or Apache licensed, installable via pip; the only cost is model API usage. GitHub stars as of 6 October 2026.

| Tool | Maintainer | Stars | Attack approach | Multi-turn adaptive | Agent / tool testing | Best for |
| --- | --- | --- | --- | --- | --- | --- |
| [promptfoo](https://www.promptfoo.dev) | OpenAI (acquired Mar 2026, still MIT) | 25,700 | Plugin-based red team, YAML assertions | Partial | Limited | Running in CI like unit tests |
| [Garak](https://github.com/NVIDIA/garak) | NVIDIA | 9,400 | Fixed probe library | Weak | None | Quick scan of a base model |
| [Giskard](https://github.com/Giskard-AI/giskard) | Giskard | 5,900 | Scan + evaluation | Weak | Limited | RAG quality and safety together |
| [PyRIT](https://github.com/Azure/PyRIT) | Microsoft | 4,600 | Composable orchestrators, PAIR/TAP/GCG | Strong | Medium | Building custom multi-turn attack flows |
| [DeepTeam](https://github.com/confident-ai/deepteam) | Confident AI | 3,000 | 40+ vulnerability types | Medium | Yes | Fast, broad-coverage scans |
| RAMPART | Microsoft (open-sourced Apr 2026) | New | Targets deployed agents | Yes | Strong: cross-prompt injection, exfiltration, behavioural regression | Agent regression testing |
| Midojo | asago-ai, Red Hat AI dev preview (Aug 2026) | New | True black-box, target unaware | Yes | Strong | Realistic black-box assessment |

Closest to this project are PyRIT (multi-turn adaptive) and RAMPART (agent regression). Recommended: install promptfoo first to feel CI-style assertions, then read the PyRIT orchestrator source.

Sources: [SecureTom comparison](https://securetom.com/blog/ai-red-teaming-tools-comparison-2026), [vdf.ai star counts](https://vdf.ai/blog/ai-red-teaming-tools/), [jailbreaks.fyi](https://jailbreaks.fyi/posts/best-ai-red-teaming-tools-for-llms/), [AI Red Teaming Guide](https://github.com/requie/AI-Red-Teaming-Guide)

## Commercial landscape

Commercial products target enterprises and sell pre-deployment assessment plus runtime protection; pricing is not public. For a Capstone their relevance is proof that real money is flowing into this direction, not competition.

| Product | Positioning | Takeaway |
| --- | --- | --- |
| [Microsoft Foundry AI Red Teaming Agent](https://learn.microsoft.com/en-us/azure/foundry/concepts/ai-red-teaming-agent) | Built-in Azure red-teaming agent; tests indirect injection via content retrieved by tools (email, documents) | Big vendors already treat tool-retrieved indirect injection as a first-class threat |
| [Mindgard](https://mindgard.ai) | Automated AI red teaming and continuous testing | Report format and risk grading worth borrowing |
| [Straiker](https://www.straiker.ai) | Agent security across three layers: application, model, tool/MCP | The three-layer model is a ready-made structure for the attack taxonomy |
| Lakera | Runtime protection plus red teaming (Lakera Red) | Protection and testing are two sides of the same market |
| Protect AI, HiddenLayer | Enterprise AI security platforms with model scanning and red teaming | Still mostly model-centric; the agent layer is thin |

An industry consensus is forming: OWASP LLM Top 10 defines *what goes wrong*, MITRE ATLAS defines *how attackers do it*, NIST AI RMF defines *how enterprises govern it*. Mapping the report to all three gives it a professional vocabulary.

Sources: [Straiker top 6 tools](https://www.straiker.ai/blog/top-6-ai-red-teaming-and-adversarial-testing-tools), [Confident AI comparison](https://www.confident-ai.com/knowledge-base/compare/best-ai-red-teaming-tools-2026), [Mindgard 41-tool list](https://mindgard.ai/blog/best-tools-for-red-teaming)

## Gaps in existing tools

Existing tools are saturated on "send prompts at a chatbot". The genuinely weak areas are agent-specific attack surfaces and test engineering.

| Gap | Current state | Why it is an opportunity |
| --- | --- | --- |
| MCP and tool-layer attacks | Tool poisoning, tool-name spoofing, privilege escalation through tool chains, tool-output injection: almost no open-source tool covers these systematically | Real agent damage happens at this layer, not when the model says something it should not |
| Deterministic verdicts | Most rely on LLM judges whose reliability is hard to verify | Plant known secrets in the target (fake API key, logged send-email tool); exfiltration success becomes exactly measurable |
| Cost and loop attacks | Driving an agent into infinite loops or runaway tool calls is essentially untested | Direct financial impact for enterprises; instantly understood |
| Regression and trends | Only RAMPART mentions regression detection; most tools are one-off scans | A test-automation background fills this gap directly |
| Judge cost | Frontier models as judges make a full assessment expensive | Replace with a fine-tuned small classifier and report "92% agreement with the frontier judge at 1/40 the cost" |
| Reports for non-security readers | Output is researcher-oriented; lacks actionable fixes for developers | QA people know how to write a defect report developers will actually read |

## Recommended positioning

One-line pitch: **a red-teaming platform built specifically for tool-using agents, with regression suites and deterministic verdicts, the way web applications are tested.** Interview comparison: "PyRIT gives you building blocks, promptfoo runs them in CI; my platform tests whether an agent can be hijacked through its tool layer, and tells you whether the score actually improved after the fix."

Three differentiating pillars, in priority order:

1. **Tool-layer attacks first**: indirect injection (via retrieved documents and tool return values), data exfiltration through tools, privilege escalation via tool chains, cost-loop attacks. Direct jailbreaks get baseline coverage only.
2. **Deterministic verdicts plus a validated judge**: canary secrets in the target, exfiltration judged by string match; the LLM judge is used only where subjective judgement is unavoidable, and its agreement rate is validated against a few hundred hand-labelled pairs.
3. **Regression and trends**: every assessment is a versioned test run; the report shows the delta against the previous run and can be wired into CI.

Directions to drop: bias detection (different evaluation paradigm, dilutes the security story) and competing on generic jailbreak corpora (Garak and DeepTeam already do this well).

Report vocabulary maps to the [OWASP LLM Top 10](https://owasp.org/www-project-top-10-for-large-language-model-applications/) (LLM01 prompt injection, LLM06 excessive agency, LLM07 system prompt leakage, etc.) and [MITRE ATLAS](https://atlas.mitre.org). Use "assessment", not "certification".

## Course coverage

Mapped against the Turing College AI Engineering outline (three sprints plus Capstone; see the [programme page](https://www.turingcollege.com/ai-engineering-bildungsgutschein)):

| Course topic | Where it appears in the project |
| --- | --- |
| Sprint 1: LLM APIs, prompt engineering, system message design | Attacker prompt generation, judge prompts, multi-provider support (OpenAI, Anthropic, Gemini) |
| Sprint 2: LangChain, RAG, ChromaDB, Streamlit/Next.js | RAG inside the vulnerable target (the indirect-injection surface); ChromaDB attack-pattern store the attacker retrieves from before mutating; Streamlit UI for launching runs and viewing scores |
| Sprint 3: LangGraph, agents, memory, MCP | Attacker/judge loop as a LangGraph graph; attacker memory across turns; the MCP/tool layer is the primary attack surface |
| LLM-as-judge evaluation (covered in sub-topics) | Judge design and validation against hand-labelled data |
| Capstone: deployed end-to-end LLM application | FastAPI service plus dashboard, hosted and documented |

Fine-tuning is not listed in the public outline, so the fine-tuned classifier is a stretch beyond the syllabus; it is included in the MVP deliberately because it produces the most resume-worthy result (agreement vs. cost chart).

## MVP scope and next steps

The MVP covers two attack families, one target, one report, an attack-pattern vector store feeding the attacker, and the judge-plus-classifier pair. Cost attacks and Langfuse tracing are phase two.

**MVP (must have)**

- Attack family 1: indirect prompt injection (via RAG documents and tool return values)
- Attack family 2: data exfiltration through tools (canary secrets in the target, deterministic verdict)
- LangGraph attacker/judge loop with multi-turn adaptation
- ChromaDB attack-pattern store: seeded from public jailbreak corpora; before each turn the attacker retrieves similar past attacks and mutates them; successful attacks are written back
- One self-built vulnerable target (HS-code agent plus a fake "send email" tool)
- Two self-hosted open-source vulnerable agents as comparison targets (legal to attack, deployed locally): [Damn Vulnerable LLM Agent](https://github.com/ReversecLabs/damn-vulnerable-llm-agent) (Reversec Labs, formerly WithSecure; a LangChain ReAct banking agent with tools, built for Thought/Action/Observation injection and tool misuse) and [AIGoat](https://github.com/AISecurityConsortium/AIGoat) (AI Security Consortium; deliberately vulnerable app with prompt injection, RAG poisoning, agent and MCP labs mapped to the OWASP LLM Top 10, runs fully locally). Enables cross-target score comparison in the report
- LLM judge validated against a few hundred hand-labelled attack/response pairs, with agreement rate reported
- Fine-tuned small classifier replacing the frontier judge, reporting agreement rate and cost ratio
- Report with OWASP mapping and risk score, including a score comparison across two runs
- Streamlit UI on top of FastAPI: register a target, launch an assessment, watch run status live, and view the score and before/after comparison between runs
- Self-protection: rate limiting, no storage of raw harmful outputs
- DeepEval benchmark for the judge: run DeepEval / DeepTeam safety metrics (jailbreak, prompt injection, OWASP mapping) on the same transcripts and report agreement with our own judge, so the judge is validated against an industry-standard framework.
- Controlled experiment for the vector store: same targets, one attacker with ChromaDB retrieval and one without; compare attack success rate and turns-to-breach to show the store's value (a standard A/B comparison).
- Long-term memory for the attacker (learns across runs): after each run, write back per-target results — which tactics worked, which failed — tagged by target traits (e.g. "has an email tool", "refuses direct requests"). At the start of the next run against a similar target, retrieve those lessons and open with the tactics that paid off. This also builds a growing per-target profile (defenses, weak OWASP categories, attack families it shrugs off). Keep it simple: no consolidation or forgetting algorithms. Measure it by running the attacker cold on a target, then again after memory has built up, and plotting the success rate climbing — turns "I used memory" into a graph.

**What goes into the ChromaDB attack-pattern store.** The store is the attacker's memory and ammunition. It holds three kinds of entries, each tagged with attack type, OWASP item and the weakness it targets:

1. Public jailbreak and prompt-injection templates (a few hundred, harvested from promptfoo, PyRIT and JailbreakBench).
2. Our own successful attacks: whenever the judge marks a turn as a breach, the conversation and the target's reaction are stored.
3. Failed attempts, annotated with why they did not work.

Before each turn the attacker embeds the target description plus the target's last reply, retrieves the most similar entries (e.g. "target has an email tool and just refused a direct request"), and rewrites them into a fresh attack. Attacks therefore get sharper over the run and transfer across targets: a tactic learned on the HS-code agent is reused against DV LLM Agent. This is RAG over attack tactics rather than documents, reusing the Sprint 2 ChromaDB work.

**Two kinds of records in one ChromaDB collection.** A metadata field `type` separates them. `type: pattern` entries are the shared attack library (public jailbreak / injection templates) — they carry no target and apply to any agent. `type: memory` entries are per-target long-term memory, written back after each run; each one stores an embedding of a short situation description plus metadata: `target`, `attack_family`, `success`, `turns`, `owasp_category`. At the start of a run the attacker queries both in one call: general patterns for ideas, and memory filtered to the current target (or targets with similar traits) for lessons learned. A per-target profile is not stored separately — it is simply a summary of all memory records for that target.

**Phase two (time permitting)**

- Cost and loop attacks
- Cross-target reuse of the attack-pattern store (patterns that worked on one agent tried first on the next)
- Langfuse tracing, richer dashboard (trends over time, per-attack drill-down), classmates' agents as black-box targets
- Endpoint ownership verification via a code placed in the target's system prompt

## Leader feedback (review on 21 Oct 2026)

1. **Target audience: vibe coders.** People building AI agents quickly with Cursor / Claude Code / Lovable etc. usually ship without any security testing. Business model: the scan itself is free (register an endpoint, run the red-team suite, get the OWASP report with risk score); charging starts when the user wants the findings fixed — e.g. generated patches / hardened system prompts / guardrail configs, or a re-scan that verifies the fix. For the capstone this means the report should be built so each finding can later carry a paid "fix" action.
2. **Attacker model: use a less-censored model such as DeepSeek or Qwen.** Western frontier models (Claude, GPT, Gemini) often refuse to *generate* jailbreaks or injection payloads, which breaks the attacker loop. DeepSeek-V3 / Qwen are more compliant with the attack instructions and cheap (API or local via Ollama). Keep the strict, paid model for the **judge** role only — there compliance is not an issue and accuracy matters most. Note for the report: state which attacker model was used, since ASR depends on it.

## Positioning vs. promptfoo (checked 23 Oct 2026)

promptfoo (MIT, now part of OpenAI) is the closest competitor and already covers more than expected: HTTP targets with auth headers / request templates, OWASP-named plugins, agent plugins (excessive agency, tool discovery, indirect injection), \~30 encoding transforms, and adaptive multi-turn attackers (Crescendo, GOAT, Hydra). So "adaptive multi-turn attack" alone is **not** a differentiator.

**Pitch: same job as promptfoo, but it learns.** promptfoo is static — every run starts from zero and forgets everything (open issue #11702: Crescendo does not reason about why the previous turn failed). This project adds a **learning layer on top** of that baseline:

1. **Attack library that grows** — every successful attack from any scan is anonymised and written back into the ChromaDB store; public repos (promptfoo, PyRIT, JailbreakBench) are imported on a schedule.
2. **Per-target long-term memory** — what worked / failed against each agent is retrieved at the start of the next run; run 10 is better than run 1, promptfoo's run 10 equals run 1.
3. **Hard-evidence judge** — canary tokens in tool arguments give deterministic proof of breach, not only an LLM opinion.
4. **Audience & model** — hosted free scan for vibe coders with paid fixes, vs. a CLI for engineers in CI.

**Plan:** use promptfoo as the control in the A/B experiment — run its red-team suite against the HS-code agent and compare ASR / turns-to-breach with this platform cold and warmed-up. Say in the viva: "promptfoo is the baseline; my contribution is the learning layer."

## Market check: vibe-coder security scanners (23 Oct 2026)

The business model the leader suggested already exists and is active: **Vibe App Scanner**, **Vibeship Scanner**, **VibeCheck**, **ZeriFlow**, **VibeEval** all follow the same pattern — paste a URL, free score and issue counts, pay to unlock full findings and fixes, each finding comes with a copy-paste prompt for Cursor / Claude Code. Pricing ranges from $5 per scan packs to monthly plans and AppSumo lifetime deals. This validates the freemium "free scan, paid fix" model for this audience.

**What they do not do:** all of them scan classic web security — exposed secrets, SQL injection / XSS, missing auth, headers, dependency CVEs. None of them attack the LLM agent itself (prompt injection, tool abuse, data exfiltration via tool calls). The closest agent-side tool is **Snyk agent-scan**, but it is a CLI for engineers that statically scans MCP configs and skills, not a hosted dynamic red-team.

**Gap = this project:** vibe-coder UX and business model × dynamic agent red-teaming with a learning layer. Position as "the Vibe App Scanner for your AI agent" rather than competing with the web scanners.

## Post-capstone go-to-market (decided 23 Oct 2026)

The capstone is treated as the MVP, not as homework. No employer conflict (no current employment); only check Bildungsgutschein rules on side income with the Agentur für Arbeit. Build first, talk to angels only with traction.

1. **Finish the capstone** so it runs end to end against any URL (register target → scan → OWASP report).
2. **Publish on a public domain** with a free tier: scan a limited set of attack families, show score, issue counts and one finding in detail; lock the rest. Collect emails from day one.
3. **One paid option** (e.g. \~€20) to unlock the full report with copy-paste fix prompts. A Stripe link or a "request full report" button is enough to measure interest — no company or billing platform needed yet.
4. **Distribute** where vibe coders are: X, Reddit, Cursor / Lovable / Claude Code communities, with the HS-code agent breach demo as the hook.
5. **Signal to watch:** strangers running scans and coming back, not revenue. \~100 scans and a few payers → talk to angels; no interest → still a strong portfolio piece and job-search asset.

## Project name: Kestrel (decided 23 Oct 2026)

A kestrel hovers, observes the target, then dives precisely — reconnaissance first, then attack. The name is deliberately not locked to "red team" so it can grow into AI product evaluation. Repo / folder: `kestrel`. Domains to check: kestrel.dev, kestrel.ai, kestrellabs.com.

- **Kestrel Red** — agent security red-teaming (this capstone).
- **Kestrel Eval** — agent quality evaluation (phase two: RAG metrics, tool-call accuracy, DeepEval / RAGAS).

## Spec Kit

The constitution lives in `.specify/memory/constitution.md` and is the only source of truth.

**Build order (one Spec Kit feature each):** 1) register target + send one prompt + show reply → 2) single-turn attack from library + judge → 3) multi-turn adaptive attacker loop → 4) ChromaDB patterns + per-target memory write-back → 5) OWASP report with risk score → 6) A/B experiment harness (cold / warm / promptfoo).

**This week**

- [ ] Install promptfoo, run its built-in red-team plugins, note what the report looks like
- [ ] Read the PyRIT multi-turn orchestrator source to understand how an attacker/judge loop is written
- [ ] Review RAMPART's test-case structure, especially behavioural regression
- [ ] Ask two classmates whether their agents can be tested during the Capstone stage
- [ ] Reserve an attackable tool in the HS-code project design
