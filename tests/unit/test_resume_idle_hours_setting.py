"""`KESTREL_RESUME_IDLE_HOURS`: unset defaults to 24.0; a positive float parses exactly; invalid values refuse to
start, naming the offending one; `GET /api/config` reports it in its own `resume` group (014/FR-057)."""
import pytest

from kestrel.settings import DEFAULT_RESUME_IDLE_HOURS, MAX_RESUME_IDLE_HOURS, SettingsError, load_settings

FEATURE = "014"


def _env(**over):
    base = {"KESTREL_DB_PATH": "x.db", "KESTREL_KEY_FILE": "x.key"}
    return {**base, **over}


def test_unset_defaults_to_24_hours():
    settings = load_settings(_env())
    assert settings.resume_idle_hours == DEFAULT_RESUME_IDLE_HOURS == 24.0


def test_a_positive_decimal_parses_exactly():
    settings = load_settings(_env(KESTREL_RESUME_IDLE_HOURS="0.5"))
    assert settings.resume_idle_hours == 0.5


@pytest.mark.parametrize("raw", ["0", "-1", "nan", "inf", "-inf", "not-a-number", "87601"])
def test_invalid_values_refuse_to_start_naming_the_value(raw):
    with pytest.raises(SettingsError, match=raw if raw not in ("nan", "inf", "-inf") else "hours"):
        load_settings(_env(KESTREL_RESUME_IDLE_HOURS=raw))


def test_the_maximum_itself_is_accepted():
    settings = load_settings(_env(KESTREL_RESUME_IDLE_HOURS=str(MAX_RESUME_IDLE_HOURS)))
    assert settings.resume_idle_hours == MAX_RESUME_IDLE_HOURS


def test_get_api_config_reports_its_own_resume_group(settings, make_client):
    from tests.support import StubAttacker, StubJudge, fixture_library
    api = make_client(settings, library=fixture_library(), judge=StubJudge(), attacker=StubAttacker())
    body = api.get("/api/config").json()
    assert body["resume"] == {"idle_hours": settings.resume_idle_hours}


def test_the_adaptive_group_is_untouched_by_this_feature(settings, make_client):
    # test_api_config_adaptive.py keeps asserting config["adaptive"] as the exact, closed object it already is.
    from tests.support import StubAttacker, StubJudge, fixture_library
    api = make_client(settings, library=fixture_library(), judge=StubJudge(), attacker=StubAttacker())
    body = api.get("/api/config").json()
    assert set(body["adaptive"].keys()) == {"max_turns", "token_budget", "time_limit_s"}
