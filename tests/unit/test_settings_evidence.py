"""Feature-013 settings: the callback listener's base URL (with its start-up validation), its bounded wait, and the
side-channel request timeout, from KESTREL_* variables (FR-021, FR-027, FR-030, FR-068)."""
import pytest

from kestrel.settings import SettingsError, callback_base_class, load_settings, validate_callback_base

FEATURE = "013"


def test_defaults_when_unset():  # FR-027, FR-030, FR-021
    settings = load_settings({})
    assert settings.callback_base_url is None            # the listener is disabled
    assert settings.callback_wait_s == 2.0
    assert settings.side_channel_timeout_s == 10


def test_valid_overrides_are_taken():  # FR-027, FR-030, FR-021
    settings = load_settings({"KESTREL_CALLBACK_BASE_URL": "https://kestrel.example.com/callback/",
                              "KESTREL_CALLBACK_WAIT_S": "0.5", "KESTREL_SIDE_CHANNEL_TIMEOUT_S": "3"})
    assert settings.callback_base_url == "https://kestrel.example.com/callback"   # a trailing slash is dropped
    assert settings.callback_wait_s == 0.5 and settings.side_channel_timeout_s == 3
    assert load_settings({"KESTREL_CALLBACK_WAIT_S": "0"}).callback_wait_s == 0   # 0 = check once, never sleep


@pytest.mark.parametrize("value", ["not a url", "ftp://host/callback", "http:///callback", "http://host/hits",
                                   "http://host/callbacks", "http://host/callback?x=1", "http://host:99999/callback",
                                   "http://user:pw@host/callback", "http://host/callback#frag"])
def test_a_malformed_or_misrouted_base_refuses_to_start_naming_the_variable(value):  # FR-027, FR-068
    with pytest.raises(SettingsError, match="KESTREL_CALLBACK_BASE_URL"):
        load_settings({"KESTREL_CALLBACK_BASE_URL": value})


@pytest.mark.parametrize("value", ["-1", "nan", "inf", "abc"])
def test_a_bad_wait_refuses_to_start_naming_the_variable(value):  # FR-030
    with pytest.raises(SettingsError, match="KESTREL_CALLBACK_WAIT_S"):
        load_settings({"KESTREL_CALLBACK_WAIT_S": value})


@pytest.mark.parametrize("value", ["0", "-5", "2.5", "abc"])
def test_a_bad_timeout_refuses_to_start_naming_the_variable(value):  # FR-021
    with pytest.raises(SettingsError, match="KESTREL_SIDE_CHANNEL_TIMEOUT_S"):
        load_settings({"KESTREL_SIDE_CHANNEL_TIMEOUT_S": value})


def test_the_start_up_check_accepts_a_usable_base_and_classifies_its_host():  # FR-068
    assert validate_callback_base("http://127.0.0.1:8000/callback") == "http://127.0.0.1:8000/callback"
    assert callback_base_class("http://127.0.0.1:8000/callback") == "loopback"
    assert callback_base_class("http://localhost:8000/callback") == "loopback"
    assert callback_base_class("http://[::1]:8000/callback") == "loopback"
    assert callback_base_class("http://192.168.1.20:8000/callback") == "private"
    assert callback_base_class("http://10.0.0.5/callback") == "private"
    assert callback_base_class("http://169.254.169.254/callback") == "private"
    assert callback_base_class("http://100.64.0.1/callback") == "private"
    assert callback_base_class("https://8.8.8.8/callback") == "public"   # the TEST-NET ranges are not routable
    assert callback_base_class("https://kestrel.example.com/callback") == "public"   # a name: never resolved here
