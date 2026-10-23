import pytest

from kestrel.connection.sessions import FormSessions
from kestrel.connection.tester import ResolvedSettings


def make(**changes) -> ResolvedSettings:
    base = dict(url="http://h/chat", method="POST", headers=(("X-API-Key", "secret-1234"),),
                body_template='{"message": "{{prompt}}"}', response_path="$.reply")
    return ResolvedSettings(**{**base, **changes})


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_start_refuses_a_second_test_for_the_same_form_only():
    sessions = FormSessions()
    assert sessions.start("a")
    assert not sessions.start("a")
    assert sessions.start("b")


def test_finish_releases_the_form_and_records_the_fingerprint():
    sessions = FormSessions()
    sessions.start("a")
    sessions.finish("a", "fp")
    assert sessions.last_success("a") == "fp"
    assert sessions.start("a")


def test_finish_without_a_fingerprint_clears_the_earlier_one():
    sessions = FormSessions()
    sessions.start("a")
    sessions.finish("a", "fp")
    sessions.start("a")
    sessions.finish("a", None)
    assert sessions.last_success("a") is None


def test_fingerprint_ignores_header_order_and_name_case():
    sessions = FormSessions()
    a = make(headers=(("X-API-Key", "secret-1234"), ("X-Other", "value-5678")))
    b = make(headers=(("x-other", "value-5678"), ("x-api-key", "secret-1234")))
    assert sessions.fingerprint(a) == sessions.fingerprint(b)


@pytest.mark.parametrize("change", [dict(url="http://h/other"), dict(method="GET"),
                                    dict(headers=(("X-API-Key", "secret-9999"),)),
                                    dict(body_template='{"m": "{{prompt}}"}'), dict(response_path="$.answer")])
def test_fingerprint_changes_with_any_connection_setting(change):
    sessions = FormSessions()
    assert sessions.fingerprint(make()) != sessions.fingerprint(make(**change))


def test_fingerprint_is_a_hex_hmac_without_header_values():
    fingerprint = FormSessions().fingerprint(make())
    assert len(fingerprint) == 64 and all(c in "0123456789abcdef" for c in fingerprint)
    assert "secret-1234" not in fingerprint


def test_sessions_unused_for_an_hour_are_dropped():
    clock = Clock()
    sessions = FormSessions(clock=clock)
    sessions.start("a")
    sessions.finish("a", "fp")
    clock.now = 3599
    assert sessions.last_success("a") == "fp"
    clock.now = 3599 + 3601
    assert sessions.last_success("a") is None
