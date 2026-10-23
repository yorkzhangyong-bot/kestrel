"""Header values never show up in a repr, so they can't slip into a log line or traceback (research R9, T055)."""
from kestrel.api.schemas import ConnectionSettingsIn, HeaderIn
from kestrel.connection.tester import ResolvedSettings
from kestrel.store import HeaderValue

SECRET = "s3cret-header-value"


def test_resolved_settings_repr_hides_header_values_and_the_query_string():
    settings = ResolvedSettings(url="http://h/chat?tenant=t-81&q={{prompt}}", method="GET",
                                headers=(("X-API-Key", SECRET),), body_template="", response_path="$.reply")
    text = repr(settings)
    assert SECRET not in text and "t-81" not in text
    assert "X-API-Key" in text and "'http://h/chat'" in text


def test_request_models_hide_header_values():
    settings = ConnectionSettingsIn(url="http://h/chat", headers=[HeaderIn(name="X-API-Key", value=SECRET)])
    assert SECRET not in repr(settings) and SECRET not in str(settings)


def test_stored_header_values_hide_their_value():
    assert SECRET not in repr(HeaderValue(name="X-API-Key", value=SECRET))
