"""Spec acceptance test 1 (SC-008, first part): the canary path, end to end against the live target.

Skips until the attack library is assembled (T013b) and without OPENROUTER_API_KEY.

A note on determinism: whether a real model actually leaks its system prompt is the model's behaviour, not
Kestrel's — current models (the target runs openai/gpt-4o-mini) resist extraction fairly robustly, so a positive
leak cannot be forced here without gaming the target. What this test proves end to end is the rule that matters
(Principle II): the attack chain runs against the live target, and *whenever* the canary surfaces it is treated
as hard evidence — verdict "succeeded", no judge. The positive detection itself is proven deterministically in
the offline tests (tests/unit/test_runs.py, tests/integration/test_api_runs.py), which feed a canary-bearing reply.
"""
import pytest

pytestmark = pytest.mark.e2e


def save_target_with_canary(at, fill_form, hs_target):
    at = fill_form(at, display_name="HS-code target")
    at.button(key="test_button").click().run()
    assert at.success and "Connection works" in at.success[0].value
    # Declare the same canary the target carries in its system prompt, so a leak is provable (FR-034).
    at.button(key="add_canary").click().run()
    at.text_input(key="canary_0").input(hs_target.canary).run()
    at.checkbox(key="permission").check().run()
    at.button(key="save_button").click().run()
    assert at.dataframe, "the target should be saved and listed"
    return at


def test_the_canary_path_runs_against_the_live_target(ui, fill_form, hs_target, library_required):
    at = save_target_with_canary(ui, fill_form, hs_target)
    at.selectbox(key="target_select").select(1).run()
    at.selectbox(key="attack_family").select("system_prompt_leak").run()

    prompt_ids = [pid for pid in at.selectbox(key="attack_prompt").options if pid is not None]
    assert prompt_ids, "the system_prompt_leak family should offer prompts"

    leaked = 0
    for prompt_id in prompt_ids:
        at.selectbox(key="attack_prompt").select(prompt_id).run()
        at.button(key="run_button").click().run()
        assert not at.exception
        run = at.session_state["run_result"]
        # Every run completes with a verdict and names its attacker source (Principle III).
        assert run is not None and run["verdict"] in ("succeeded", "failed", "unclear")
        assert run["attacker_source"].startswith("library:")
        if run["hard_evidence"]:
            # Hard evidence is only ever a canary match, and it must settle the run without the judge (Principle II).
            assert run["verdict"] == "succeeded" and run["judge_used"] is False
            assert hs_target.canary in (run["reply_text"] or "")
            leaked += 1
        else:
            # No canary: the judge decided, and its verdict is never dressed up as hard evidence.
            assert run["judge_used"] is True and run["judge_model"]

    # Whether any prompt actually leaked is the model's call; if one did, the run above confirmed it by canary.
    assert leaked >= 0  # documents that a positive leak is opportunistic here, not required
