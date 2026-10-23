"""The screen's US2 parts through AppTest, with api_client stubbed (contracts/ui-form.md rows 7 to 9)."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

import api_client

APP = str(Path(__file__).resolve().parents[2] / "ui" / "app.py")
TERMS = "You confirm that you own this agent or have written permission to test it."
CONFIG = {"mode": "local",
          "defaults": {"method": "POST", "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply"},
          "terms": {"version": "1", "text": TERMS}}
PERMISSION = "I own this agent or have written permission to test it"
SAVED = {"id": 1, "name": "My agent", "url": "http://127.0.0.1:8001/chat", "method": "POST",
         "permission_confirmed_at": "2026-10-23T14:05:00Z", "terms_version": "1",
         "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply",
         "headers": [{"name": "X-API-Key", "has_value": True, "readable": True}]}
SUMMARY_KEYS = ("id", "name", "url", "method", "permission_confirmed_at", "terms_version")


@pytest.fixture
def api(monkeypatch):
    stub = SimpleNamespace(saved=[], targets=[], save_error=None)

    def save_target(payload):
        stub.saved.append(payload)
        if stub.save_error is not None:
            raise stub.save_error
        stub.targets = [{key: SAVED[key] for key in SUMMARY_KEYS}]
        return SAVED

    monkeypatch.setattr(api_client, "get_config", lambda: CONFIG)
    monkeypatch.setattr(api_client, "list_targets", lambda: stub.targets)
    monkeypatch.setattr(api_client, "test_connection", lambda payload: {
        "ok": True, "step": "success", "message": "Connection works.", "detail": None, "status_code": 200,
        "reply_text": "Hi", "reply_truncated": False, "duration_ms": 10})
    monkeypatch.setattr(api_client, "save_target", save_target)
    return stub


def filled_app() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=10).run()
    at.text_input(key="display_name").input("My agent")
    at.text_input(key="url").input("http://127.0.0.1:8001/chat")
    at.button(key="add_header").click().run()
    at.text_input(key="header_name_0").input("X-API-Key")
    at.text_input(key="header_value_0").input("key-12345")
    at.run()
    return at.button(key="test_button").click().run()


def texts(elements) -> list[str]:
    return [element.value for element in elements]


def test_the_permission_checkbox_has_the_exact_label(api):
    at = AppTest.from_file(APP, default_timeout=10).run()
    assert at.checkbox(key="permission").label == PERMISSION
    assert at.checkbox(key="permission").value is False


def test_the_terms_are_shown_in_an_expander_and_the_form_is_kept(api):
    at = filled_app()
    assert [e.label for e in at.expander] == ["Terms of service (version 1)"]
    assert TERMS in texts(at.expander[0].text)
    at.run()
    assert at.text_input(key="url").value == "http://127.0.0.1:8001/chat"
    assert at.text_input(key="display_name").value == "My agent"


def test_save_sends_the_permission_and_the_terms_version(api):
    at = filled_app()
    at.checkbox(key="permission").check().run()
    at.button(key="save_button").click().run()
    assert len(api.saved) == 1
    sent = api.saved[0]
    assert sent["permission_confirmed"] is True and sent["terms_version"] == "1" and sent["name"] == "My agent"
    assert sent["settings"]["headers"] == [{"name": "X-API-Key", "value": "key-12345"}]


@pytest.mark.parametrize("error, message", [
    (api_client.ApiError(409, {"error": {"code": "not_tested", "field": None,
                                         "message": "Run a successful test with these settings before saving."}}),
     "Run a successful test with these settings before saving."),
    (api_client.ApiError(409, {"error": {"code": "name_taken", "field": "name",
                                         "message": "Another saved target already has this name."}}),
     "Another saved target already has this name."),
    (api_client.ApiError(422, {"errors": [{"field": "permission_confirmed",
                                           "message": "Tick the box to confirm you may test this agent."}]}),
     "Tick the box to confirm you may test this agent."),
])
def test_save_errors_are_shown(api, error, message):
    api.save_error = error
    at = filled_app()
    at.button(key="save_button").click().run()
    assert message in texts(at.error)
    assert not at.dataframe


def test_after_a_save_the_table_lists_the_target_and_typed_values_are_gone(api):
    at = filled_app()
    form_id = at.session_state["form_id"]
    at.checkbox(key="permission").check().run()
    at.button(key="save_button").click().run()
    table = at.dataframe[0].value
    assert table.to_dict("records") == [{"Name": "My agent", "URL": "http://127.0.0.1:8001/chat", "Method": "POST",
                                         "Permission confirmed": "2026-10-23", "Terms version": "1"}]
    typed = [at.session_state[key] for key in ("header_value_0",) if key in at.session_state]
    assert "key-12345" not in typed
    assert all(row["value"] == "" for row in at.session_state["headers"])
    assert at.session_state["form_id"] != form_id
