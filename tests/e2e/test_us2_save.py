"""Spec acceptance test 3 (US2.2) and US2.1 against the sacrificial HS-code target, through the real screen."""
import pytest

pytestmark = pytest.mark.e2e


def test_saving_needs_the_permission_box_and_then_lists_the_target(ui, fill_form, assert_no_secret_in_logs):
    at = fill_form(ui, display_name="HS-code target")
    at.button(key="test_button").click().run()
    assert at.success and "Connection works" in at.success[0].value

    # The checkbox is the only thing missing: saving is blocked and nothing is listed.
    at.button(key="save_button").click().run()
    assert not at.exception
    assert at.error
    assert not at.dataframe

    at.checkbox(key="permission").check().run()
    at.button(key="save_button").click().run()
    assert not at.exception
    assert at.dataframe[0].value["Name"].tolist() == ["HS-code target"]
    assert_no_secret_in_logs()
