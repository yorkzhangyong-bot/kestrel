"""The target form's "Side channel" section (013/FR-041, FR-043; US4), through AppTest with api_client stubbed:
the four exact labels, all optional; the header value masked with the stored-value placeholder behaviour of the
auth headers; the submitted payload carrying the section as typed - the form validates nothing of its own, the
API's field messages land under each field - and the API's "Side channel checked." flag displayed as is."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

import api_client

FEATURE = "013"

APP = str(Path(__file__).resolve().parents[2] / "ui" / "app.py")
CONFIG = {"mode": "local",
          "defaults": {"method": "POST", "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply"},
          "terms": {"version": "1", "text": "Terms text."},
          "judge": {"model": "google/gemini-3.8-flash", "configured": True}}
SIDE_URL = "http://127.0.0.1:8001/side-channel"
LABELS = {"side_channel_url": "Side-channel URL", "side_channel_header_name": "Side-channel header name",
          "side_channel_header_value": "Side-channel header value", "side_channel_honeypot": "Honeypot tool name"}
STORED_TARGET = {"id": 1, "name": "My agent", "url": "http://127.0.0.1:8001/chat", "method": "POST",
                 "permission_confirmed_at": "2026-11-20T14:05:00Z", "terms_version": "1",
                 "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply", "headers": [],
                 "canaries": [],
                 "side_channel": {"url": SIDE_URL, "header_name": "X-Side-Key", "has_value": True,
                                  "readable": True, "honeypot_tool": "approve_duty_refund"}}
SUMMARY = {key: STORED_TARGET[key] for key in ("id", "name", "url", "method", "permission_confirmed_at",
                                                "terms_version")}


def result(**changes) -> dict:
    base = {"ok": True, "step": "success", "message": "Connection works.", "detail": None, "status_code": 200,
            "reply_text": "Hi there", "reply_truncated": False, "duration_ms": 1234}
    return {**base, **changes}


@pytest.fixture
def api(monkeypatch):
    stub = SimpleNamespace(payloads=[], answer=result(), targets=[], target=None)

    def test_connection(payload):
        stub.payloads.append(payload)
        if isinstance(stub.answer, Exception):
            raise stub.answer
        return stub.answer

    monkeypatch.setattr(api_client, "get_config", lambda: CONFIG)
    monkeypatch.setattr(api_client, "test_connection", test_connection)
    monkeypatch.setattr(api_client, "list_targets", lambda: stub.targets)
    monkeypatch.setattr(api_client, "get_target", lambda target_id: stub.target)
    monkeypatch.setattr(api_client, "get_profile", lambda target_id: {"target_id": 1, "total_runs": 0,
                                                                      "by_family": [], "by_verdict": [],
                                                                      "recent": []})
    monkeypatch.setattr(api_client, "list_runs", lambda target_id: [])
    monkeypatch.setattr(api_client, "attack_families", lambda: {"library_version": "1.0.0", "families": []})
    return stub


def basic_form() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=10).run()
    at.text_input(key="display_name").input("My agent")
    at.text_input(key="url").input("http://127.0.0.1:8001/chat")
    return at


def click_test(at: AppTest) -> AppTest:
    return at.button(key="test_button").click().run()


def test_the_section_shows_the_four_exact_labels_all_optional(api):  # FR-041
    at = basic_form().run()
    for key, label in LABELS.items():
        assert at.text_input(key=key).label == label
        assert at.text_input(key=key).value == ""
    at = click_test(at)
    [payload] = api.payloads
    assert payload["settings"].get("side_channel") is None                   # left empty: no side channel, and
    assert "side_channel" not in payload["settings"]                        # exactly today's payload (SC-008)


def test_the_payload_carries_the_section_as_typed(api):  # FR-041, FR-043
    at = basic_form()
    at.text_input(key="side_channel_url").input(SIDE_URL)
    at.text_input(key="side_channel_header_name").input("X-Side-Key")
    at.text_input(key="side_channel_header_value").input("side-secret-123")
    at.text_input(key="side_channel_honeypot").input("approve_duty_refund")
    at = click_test(at.run())
    [payload] = api.payloads
    assert payload["settings"]["side_channel"] == {"url": SIDE_URL,
                                                   "header": {"name": "X-Side-Key", "value": "side-secret-123"},
                                                   "honeypot_tool": "approve_duty_refund"}


def test_the_form_validates_nothing_itself_and_shows_the_apis_field_messages(api):  # FR-041, FR-043
    at = basic_form()
    at.text_input(key="side_channel_url").input("not a url")
    at.text_input(key="side_channel_honeypot").input("no spaces allowed")
    api.answer = api_client.ApiError(422, {"errors": [
        {"field": "settings.side_channel.url", "message": "Enter a full http:// or https:// address."},
        {"field": "settings.side_channel.honeypot_tool",
         "message": "Use a tool name of 1 to 100 characters: letters, digits, '_', '-' and '.' only."}]})
    at = click_test(at.run())
    [payload] = api.payloads
    assert payload["settings"]["side_channel"]["url"] == "not a url"          # sent as typed, unvalidated
    assert payload["settings"]["side_channel"]["honeypot_tool"] == "no spaces allowed"
    shown = [e.value for e in at.error]
    assert "Enter a full http:// or https:// address." in shown
    assert any("tool name" in text for text in shown)


def test_a_loaded_targets_stored_value_is_kept_when_left_empty(api):  # FR-041
    api.targets = [SUMMARY]
    api.target = STORED_TARGET
    at = AppTest.from_file(APP, default_timeout=10).run()
    at = at.selectbox(key="target_select").select(1).run()
    assert at.text_input(key="side_channel_url").value == SIDE_URL
    assert at.text_input(key="side_channel_header_name").value == "X-Side-Key"
    assert at.text_input(key="side_channel_header_value").value == ""       # the value is never loaded
    assert at.text_input(key="side_channel_header_value").placeholder == "Stored · leave empty to keep"
    assert at.text_input(key="side_channel_honeypot").value == "approve_duty_refund"
    at = click_test(at)
    [payload] = api.payloads
    assert payload["target_id"] == 1
    assert payload["settings"]["side_channel"]["header"] == {"name": "X-Side-Key", "value": None}


def test_an_unreadable_stored_value_says_so_in_the_placeholder(api):  # FR-041
    api.targets = [SUMMARY]
    api.target = {**STORED_TARGET, "side_channel": {**STORED_TARGET["side_channel"], "readable": False}}
    at = AppTest.from_file(APP, default_timeout=10).run()
    at = at.selectbox(key="target_select").select(1).run()
    assert at.text_input(key="side_channel_header_value").placeholder == \
        "Can't be read with the current key · enter it again"


def test_the_checked_flag_is_displayed_as_the_api_set_it(api):  # FR-021, FR-043
    at = basic_form()
    at.text_input(key="side_channel_url").input(SIDE_URL)
    api.answer = result(side_channel_checked=True)
    at = click_test(at.run())
    assert "Side channel checked." in [c.value for c in at.caption]
    api.payloads.clear()
    api.answer = result()
    at = click_test(at)
    assert "Side channel checked." not in [c.value for c in at.caption]
