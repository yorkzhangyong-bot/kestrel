"""Spec acceptance test 1 (SC-008, first part): a system-prompt-leak attack settled by its canary, no judge.

Skips until the attack library is assembled (T013 deferred) and without OPENROUTER_API_KEY. Runs against the
live sacrificial target through the real screen.
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


def test_a_system_prompt_leak_is_confirmed_by_the_canary_without_the_judge(
        ui, fill_form, hs_target, library_required):
    at = save_target_with_canary(ui, fill_form, hs_target)
    at.selectbox(key="target_select").select(1).run()

    at.selectbox(key="attack_family").select("system_prompt_leak").run()
    at.button(key="run_button").click().run()
    assert not at.exception

    run = at.session_state["run_result"]
    assert run is not None and run["verdict"] == "succeeded"
    assert run["hard_evidence"] is True            # settled by the canary (Principle II)
    assert run["judge_used"] is False              # no model was consulted (SC-003)
    assert hs_target.canary in (run["reply_text"] or "")  # the leak itself: the canary surfaced in the reply
