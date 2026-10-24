"""The screen's US3 parts through AppTest, with api_client stubbed (contracts/ui-form.md rows 1, 4 and 10)."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

import api_client

APP = str(Path(__file__).resolve().parents[2] / "ui" / "app.py")
CONFIG = {"mode": "local",
          "defaults": {"method": "POST", "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply"},
          "terms": {"version": "1", "text": "Terms text."}}
DETAIL = {"id": 1, "name": "My agent", "url": "http://127.0.0.1:8001/chat", "method": "POST",
          "permission_confirmed_at": "2026-10-23T14:05:00Z", "terms_version": "1",
          "body_template": '{"msg": "{{prompt}}"}', "response_path": "$.answer",
          "headers": [{"name": "X-API-Key", "has_value": True, "readable": True}]}
SUMMARY = {key: DETAIL[key] for key in ("id", "name", "url", "method", "permission_confirmed_at", "terms_version")}


@pytest.fixture
def api(monkeypatch):
    stub = SimpleNamespace(targets=[SUMMARY], tests=[], updates=[], deletes=[])

    def test_connection(payload):
        stub.tests.append(payload)
        return {"ok": True, "step": "success", "message": "Connection works.", "detail": None, "status_code": 200,
                "reply_text": "Hi", "reply_truncated": False, "duration_ms": 10}

    def update_target(target_id, payload):
        stub.updates.append((target_id, payload))
        return {**DETAIL, "name": payload["name"]}

    def delete_target(target_id):
        stub.deletes.append(target_id)
        stub.targets = []

    monkeypatch.setattr(api_client, "get_config", lambda: CONFIG)
    monkeypatch.setattr(api_client, "list_targets", lambda: stub.targets)
    monkeypatch.setattr(api_client, "get_profile", lambda target_id: {"target_id": 1, "total_runs": 0, "by_family": [], "by_verdict": [], "recent": []})
    monkeypatch.setattr(api_client, "get_target", lambda target_id: DETAIL)
    monkeypatch.setattr(api_client, "test_connection", test_connection)
    monkeypatch.setattr(api_client, "update_target", update_target)
    monkeypatch.setattr(api_client, "delete_target", delete_target)
    return stub


def loaded_app() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=10).run()
    return at.selectbox(key="target_select").select(1).run()


def test_the_picker_offers_new_target_and_saved_targets(api):
    at = AppTest.from_file(APP, default_timeout=10).run()
    picker = at.selectbox(key="target_select")
    assert picker.options == ["New target", "My agent · http://127.0.0.1:8001/chat"]


def test_selecting_a_saved_target_loads_it_with_stored_headers_hidden(api):
    at = loaded_app()
    assert at.text_input(key="display_name").value == "My agent"
    assert at.text_input(key="url").value == "http://127.0.0.1:8001/chat"
    assert at.text_input(key="body_template").value == '{"msg": "{{prompt}}"}'
    assert at.text_input(key="response_path").value == "$.answer"
    assert at.checkbox(key="permission").value is True
    assert at.text_input(key="header_name_0").value == "X-API-Key"
    value = at.text_input(key="header_value_0")
    assert value.value == "" and value.placeholder == "Stored · leave empty to keep"


def test_testing_a_loaded_target_sends_its_id_and_keeps_stored_values(api):
    at = loaded_app()
    at.button(key="test_button").click().run()
    sent = api.tests[-1]
    assert sent["target_id"] == 1
    assert sent["settings"]["headers"] == [{"name": "X-API-Key", "value": None}]


def test_changing_the_url_clears_the_permission_box(api):
    at = loaded_app()
    at.text_input(key="url").input("http://127.0.0.1:8001/v2/chat").run()
    assert at.checkbox(key="permission").value is False
    at.checkbox(key="permission").check().run()
    assert at.checkbox(key="permission").value is True


def test_a_name_only_change_is_saved_as_an_update(api):
    at = loaded_app()
    at.text_input(key="display_name").input("Renamed").run()
    at.button(key="save_button").click().run()
    target_id, payload = api.updates[-1]
    assert target_id == 1 and payload["name"] == "Renamed" and payload["permission_confirmed"] is True
    assert payload["settings"]["headers"] == [{"name": "X-API-Key", "value": None}]
    assert not at.error


def test_delete_asks_for_confirmation_and_cancel_changes_nothing(api):
    at = loaded_app()
    at.button(key="delete_button").click().run()
    assert at.button(key="delete_confirm") and at.button(key="delete_cancel")
    at.button(key="delete_cancel").click().run()
    assert api.deletes == []
    assert at.text_input(key="display_name").value == "My agent"
    assert at.dataframe


def test_confirming_delete_removes_the_target_and_starts_a_new_form(api):
    at = loaded_app()
    form_id = at.session_state["form_id"]
    at.button(key="delete_button").click().run()
    at.button(key="delete_confirm").click().run()
    assert api.deletes == [1]
    assert not at.dataframe
    assert at.session_state["form_id"] != form_id
    assert at.selectbox(key="target_select").index == 0  # "New target"
    assert at.text_input(key="display_name").value == ""
