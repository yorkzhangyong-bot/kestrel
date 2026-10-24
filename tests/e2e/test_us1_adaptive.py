"""Spec acceptance (SC-009): an adaptive attack runs against the live sacrificial target and stores the whole run.

Skips until the attack library exists and without OPENROUTER_API_KEY. The exact verdict is model-dependent and
not asserted; what is asserted is deterministic — the run completes, names its attacker and budgets, and stores
the conversation (the feature-002 model-determinism caveat applies here too)."""
import pytest

pytestmark = pytest.mark.e2e


def save_target_with_canary(at, fill_form, hs_target):
    at = fill_form(at, display_name="HS-code target")
    at.button(key="test_button").click().run()
    assert at.success and "Connection works" in at.success[0].value
    at.button(key="add_canary").click().run()
    at.text_input(key="canary_0").input(hs_target.canary).run()
    at.checkbox(key="permission").check().run()
    at.button(key="save_button").click().run()
    assert at.dataframe, "the target should be saved and listed"
    return at


def test_an_adaptive_attack_completes_and_stores_the_conversation(ui, fill_form, hs_target, library_required,
                                                                  assert_no_secret_in_logs):
    at = save_target_with_canary(ui, fill_form, hs_target)
    at.selectbox(key="target_select").select(1).run()
    at.radio(key="attack_mode").set_value("Adaptive").run()
    at.selectbox(key="attack_family").select("system_prompt_leak").run()
    at.button(key="run_button").click().run()
    assert not at.exception

    run = at.session_state["run_result"]
    assert run is not None and run["mode"] == "adaptive"
    assert run["verdict"] in ("succeeded", "failed", "unclear")
    assert run["attacker_model"]                                  # names the attacker (SC-004, Principle III)
    assert run["turns_used"] and run["turns_used"] <= 2           # honoured the e2e turn cap
    assert run["turns"], "the full conversation is stored (FR-020)"
    # The hard-evidence rule holds whenever the canary surfaced; otherwise the judge decided.
    if run["hard_evidence"]:
        assert run["verdict"] == "succeeded" and run["judge_used"] is False
    assert run["stopping_condition"] is not None
    assert_no_secret_in_logs()
