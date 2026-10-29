"""Spec acceptance test (SC-008, second and third parts): with no canary, the judge decides and the run names
the judge model. Skips until the attack library is assembled (T013b) and without OPENROUTER_API_KEY.

The exact verdict a real judge returns is not asserted — it is an opinion and model-dependent. What is asserted
is deterministic and is what SC-008's second and third parts are about: the judge was consulted, the run names
the model, and the verdict is never dressed up as hard evidence (Principle II)."""
import pytest

FEATURE = "002"

pytestmark = pytest.mark.e2e


def save_plain_target(at, fill_form):
    at = fill_form(at, display_name="HS-code target")
    at.button(key="test_button").click().run()
    assert at.success and "Connection works" in at.success[0].value
    at.checkbox(key="permission").check().run()
    at.button(key="save_button").click().run()
    assert at.dataframe, "the target should be saved and listed"
    return at


def test_a_run_with_no_canary_is_decided_by_the_judge_which_is_named(
        ui, fill_form, hs_target, library_required, assert_no_secret_in_logs):
    at = save_plain_target(ui, fill_form)       # no canary declared, so the judge decides
    at.selectbox(key="target_select").select(1).run()

    at.selectbox(key="attack_family").select("direct_injection").run()
    at.button(key="run_button").click().run()
    assert not at.exception

    run = at.session_state["run_result"]
    assert run is not None
    assert run["judge_used"] is True                 # no canary, so the judge was consulted
    assert run["judge_model"]                        # the run names the model that judged it (SC-004, Principle III)
    assert run["verdict"] in ("succeeded", "failed", "unclear")
    assert run["hard_evidence"] is False             # a judge verdict is opinion, never confirmed (Principle II)

    # And the stored run keeps the judge model (third part of SC-008).
    runs = at.session_state["runs"] or []
    assert runs and runs[0]["judge_model"] == run["judge_model"]
    assert_no_secret_in_logs()
