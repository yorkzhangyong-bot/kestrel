"""The screen's US1 parts through AppTest, with api_client stubbed (contracts/ui-form.md)."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

import api_client

APP = str(Path(__file__).resolve().parents[2] / "ui" / "app.py")
CONFIG = {"mode": "local",
          "defaults": {"method": "POST", "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply"}}
HOSTILE = '**bold** <img src=x onerror=alert(1)> [link](http://evil.test) ![x](http://evil.test/x.png)'


def result(**changes):
    base = {"ok": True, "step": "success", "message": "Connection works.", "detail": None, "status_code": 200,
            "reply_text": "Hi there", "reply_truncated": False, "duration_ms": 1234}
    return {**base, **changes}


@pytest.fixture
def api(monkeypatch):
    stub = SimpleNamespace(payloads=[], answer=result())

    def test_connection(payload):
        stub.payloads.append(payload)
        if isinstance(stub.answer, Exception):
            raise stub.answer
        return stub.answer

    monkeypatch.setattr(api_client, "get_config", lambda: CONFIG)
    monkeypatch.setattr(api_client, "test_connection", test_connection)
    return stub


def filled_app() -> AppTest:
    at = AppTest.from_file(APP).run()
    at.text_input(key="display_name").input("My agent")
    at.text_input(key="url").input("http://127.0.0.1:8001/chat")
    at.button(key="add_header").click().run()
    at.text_input(key="header_name_0").input("X-API-Key")
    at.text_input(key="header_value_0").input("key-12345")
    return at.run()


def click_test(at: AppTest) -> AppTest:
    return at.button(key="test_button").click().run()


def texts(elements) -> list[str]:
    return [element.value for element in elements]


def test_the_form_starts_with_the_defaults(api):
    at = AppTest.from_file(APP).run()
    assert not at.exception
    assert at.selectbox(key="method").value == "POST"
    assert at.text_input(key="body_template").value == CONFIG["defaults"]["body_template"]
    assert at.text_input(key="response_path").value == "$.reply"
    assert "Running locally" in texts(at.caption)


def test_header_rows_can_be_added_and_removed(api):
    at = AppTest.from_file(APP).run()
    at.button(key="add_header").click().run()
    at.button(key="add_header").click().run()
    at.text_input(key="header_name_1").input("X-Second").run()
    at.button(key="header_remove_0").click().run()
    assert at.text_input(key="header_name_0").value == "X-Second"
    assert len([w for w in at.text_input if w.key and w.key.startswith("header_name_")]) == 1


def test_clicking_test_connection_sends_the_form(api):
    click_test(filled_app())
    assert len(api.payloads) == 1
    sent = api.payloads[0]
    assert sent["form_id"] and sent["target_id"] is None and sent["display_name"] == "My agent"
    assert sent["settings"] == {"url": "http://127.0.0.1:8001/chat", "method": "POST",
                                "headers": [{"name": "X-API-Key", "value": "key-12345"}],
                                "body_template": CONFIG["defaults"]["body_template"], "response_path": "$.reply"}


def test_a_success_shows_the_reply_as_code(api):
    at = click_test(filled_app())
    assert "Connection works" in at.success[0].value
    assert texts(at.code) == ["Hi there"]


def test_a_hostile_reply_appears_only_inside_the_code_element(api):
    api.answer = result(reply_text=HOSTILE)
    at = click_test(filled_app())
    assert texts(at.code) == [HOSTILE]
    rendered_as_markdown = texts(at.markdown) + texts(at.success) + texts(at.error) + texts(at.caption) + texts(at.info)
    assert not any("evil.test" in text or "<img" in text for text in rendered_as_markdown)


def test_an_empty_reply_says_so(api):
    api.answer = result(reply_text="")
    at = click_test(filled_app())
    assert "(empty reply)" in texts(at.caption)


def test_a_cut_reply_shows_a_caption(api):
    api.answer = result(reply_text="a" * 2000, reply_truncated=True)
    at = click_test(filled_app())
    assert any("2,000" in text for text in texts(at.caption))


def test_a_failure_shows_the_message_and_the_detail_as_code(api):
    api.answer = result(ok=False, step="endpoint_error", message="The endpoint answered with an error.",
                        detail="Status 500", status_code=500, reply_text=None)
    at = click_test(filled_app())
    assert texts(at.error) == ["The endpoint answered with an error."]
    assert texts(at.code) == ["Status 500"]


def test_validation_errors_are_shown(api):
    api.answer = api_client.ApiError(422, {"errors": [
        {"field": "settings.url", "message": "put credentials in an auth header, not the URL"},
        {"field": "settings.headers.0.value", "message": "Auth header values must be at least 4 characters."}]})
    at = click_test(filled_app())
    assert "put credentials in an auth header, not the URL" in texts(at.error)
    assert "Auth header values must be at least 4 characters." in texts(at.error)
