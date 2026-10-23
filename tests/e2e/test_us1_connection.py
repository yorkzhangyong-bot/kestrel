"""Spec acceptance tests 1 and 2 (US1.1, US1.2) against the sacrificial HS-code target, through the real screen."""
import pytest

pytestmark = pytest.mark.e2e


def test_registering_the_sacrificial_target_shows_its_reply(ui, fill_form, assert_no_secret_in_logs):
    at = fill_form(ui)
    at.button(key="test_button").click().run()
    assert not at.exception
    assert at.success and "Connection works" in at.success[0].value
    assert at.code and at.code[0].value.strip()
    assert_no_secret_in_logs()


def test_a_wrong_response_path_shows_response_path_not_found(ui, fill_form, assert_no_secret_in_logs):
    at = fill_form(ui, response_path="$.answer")
    at.button(key="test_button").click().run()
    assert not at.exception
    assert at.error and at.error[0].value.startswith("Response path not found")
    assert not at.code
    assert_no_secret_in_logs()
