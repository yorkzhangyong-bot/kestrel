"""The report header names the judge and attacker prompt versions next to the model slugs, from the provenance each
run and turn recorded; a judged run or attacker turn without provenance reads "not recorded", never a guessed
version (009/FR-003; the FR-004 honesty rule). Pure: build_report over Run/Turn values, no store."""
from kestrel.report.model import build_report
from kestrel.report.render import render_markdown
from kestrel.store import Run, Turn

FEATURE = "009"

NOW = "2026-11-13T12:00:00Z"


def run(**kw) -> Run:
    base = dict(id=1, target_id=1, prompt_id="spl-001", prompt_title="t", prompt_text="<seed>",
                family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                attacker_source="library:1.0.0", status="finished", started_at=NOW, finished_at=NOW,
                verdict="failed", judge_used=True, judge_model="google/gemini-3.8-flash",
                judge_prompt_id="judge", judge_prompt_version="1")
    return Run(**{**base, **kw})


class Target:  # a minimal stand-in; build_report only reads name and description
    name = "My agent"
    description = "a customs assistant"


def turn(position, **kw) -> Turn:
    return Turn(position=position, attacker_message=f"<m{position}>", reply_text="r", **kw)


def test_the_header_collects_prompt_versions_from_runs_and_turns():  # 009/FR-003
    adaptive = run(id=2, mode="adaptive", attacker_model="deepseek/deepseek-v4.1-flash", family="direct_injection",
                   owasp_category="LLM01: Prompt Injection")
    turns = [turn(1, judge_prompt_id="judge", judge_prompt_version="1"),   # the library seed: no attacker prompt
             turn(2, attacker_prompt_id="attacker:direct_injection", attacker_prompt_version="1",
                  judge_prompt_id="judge", judge_prompt_version="1")]
    header = build_report(target=Target(), runs=[run(id=1), adaptive], turns_by_run={2: turns}, now=NOW).header
    assert header.judge_prompts == ("judge@1",)
    assert header.attacker_prompts == ("attacker:direct_injection@1",)


def test_the_header_renders_the_versions_next_to_the_model_slugs():  # 009/FR-003
    adaptive = run(id=2, mode="adaptive", attacker_model="deepseek/deepseek-v4.1-flash")
    turns = [turn(1), turn(2, attacker_prompt_id="attacker:system_prompt_leak", attacker_prompt_version="1")]
    md = render_markdown(build_report(target=Target(), runs=[adaptive], turns_by_run={2: turns}, now=NOW))
    assert "- **Attacker model(s)**: deepseek/deepseek-v4.1-flash · prompt(s): attacker:system_prompt_leak@1" in md
    assert "- **Judge model(s)**: google/gemini-3.8-flash · prompt(s): judge@1" in md


def test_distinct_versions_are_all_named():  # 009/FR-003
    runs = [run(id=1), run(id=2, judge_prompt_version="2")]
    header = build_report(target=Target(), runs=runs, turns_by_run={}, now=NOW).header
    assert header.judge_prompts == ("judge@1", "judge@2")


def test_missing_provenance_reads_not_recorded_never_a_guessed_version():  # 009/FR-003
    old = run(id=3, judge_prompt_id=None, judge_prompt_version=None)                  # a judged run from before v7
    adaptive = run(id=4, mode="adaptive", attacker_model="deepseek/deepseek-v4.1-flash")
    turns = [turn(1), turn(2)]                                                        # attacker turn from before v7
    model = build_report(target=Target(), runs=[old, adaptive], turns_by_run={4: turns}, now=NOW)
    assert model.header.judge_prompts == ("judge@1", "not recorded")
    assert model.header.attacker_prompts == ("not recorded",)
    assert "prompt(s): not recorded" in render_markdown(model)


def test_runs_without_a_judge_or_attacker_show_no_prompt_suffix():  # 009/FR-003
    single = run(id=1, judge_used=False, judge_model=None, judge_prompt_id=None, judge_prompt_version=None)
    md = render_markdown(build_report(target=Target(), runs=[single], turns_by_run={}, now=NOW))
    assert "- **Attacker model(s)**: —\n" in md and "- **Judge model(s)**: —\n" in md
    assert "prompt(s)" not in md
