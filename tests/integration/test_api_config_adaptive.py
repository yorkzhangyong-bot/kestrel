"""/api/config exposes the attacker and caps, and every adaptive run names its attacker and budget (FR-014, FR-015, SC-004)."""
import uuid

import httpx

from kestrel.api.main import load_terms
from kestrel.settings import DEFAULT_ATTACKER_MODEL
from tests.support import StubAttacker, StubJudge, fixture_library

FEATURE = "003"

SECRET = "s3cret-header-value"
CURRENT_TERMS = load_terms().version


def connection(**changes):
    base = {"url": "http://127.0.0.1:8102/chat", "method": "POST",
            "headers": [{"name": "X-API-Key", "value": SECRET}],
            "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply"}
    return {**base, **changes}


def save_target(api):
    form_id = str(uuid.uuid4())
    assert api.post("/api/connection-tests", json={"form_id": form_id, "target_id": None, "display_name": "A",
                                                   "settings": connection()}).json()["ok"]
    return api.post("/api/targets", json={"form_id": form_id, "name": "HS Agent", "settings": connection(),
                                          "permission_confirmed": True, "terms_version": CURRENT_TERMS}).json()["id"]


def test_config_reports_the_attacker_and_the_caps(make_client):
    # /api/config reports the attacker model from settings (the default), independent of the stub instance.
    api = make_client(library=fixture_library(), judge=StubJudge(), attacker=StubAttacker())
    config = api.get("/api/config").json()
    assert config["attacker"] == {"model": DEFAULT_ATTACKER_MODEL, "configured": True}
    assert config["adaptive"] == {"max_turns": 6, "token_budget": 40000, "time_limit_s": 300}
    assert config["terms"]["version"] == "3"


def test_config_reports_an_unconfigured_attacker(make_client):
    api = make_client(library=fixture_library(), judge=StubJudge(), attacker=StubAttacker(configured=False))
    assert api.get("/api/config").json()["attacker"]["configured"] is False


def test_an_adaptive_run_records_its_attacker_judge_and_budgets(make_client):
    api = make_client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"reply": "ok"})),
                      library=fixture_library(), judge=StubJudge(), attacker=StubAttacker(model="deepseek/deepseek-v3.2"))
    tid = save_target(api)
    body = api.post("/api/runs", json={"target_id": tid, "family": "system_prompt_leak", "mode": "adaptive"}).json()
    assert body["attacker_model"] == "deepseek/deepseek-v3.2"
    assert body["judge_model"] == "google/gemini-3.8-flash"
    assert body["turn_budget"] == 6 and body["turns_used"] >= 1
    assert body["token_budget"] == 40000 and body["tokens_used"] >= 0
    assert body["time_limit_s"] == 300


def test_two_runs_with_different_attackers_each_name_their_own(make_client, settings):
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"reply": "ok"}))
    api1 = make_client(settings, transport=transport, library=fixture_library(), judge=StubJudge(),
                       attacker=StubAttacker(model="deepseek/deepseek-v3.2"))
    tid = save_target(api1)
    first = api1.post("/api/runs", json={"target_id": tid, "family": "system_prompt_leak", "mode": "adaptive"}).json()
    # A second app over the same database, configured with a different attacker model.
    api2 = make_client(settings, transport=transport, library=fixture_library(), judge=StubJudge(),
                       attacker=StubAttacker(model="qwen/qwen3.2"))
    second = api2.post("/api/runs", json={"target_id": tid, "family": "direct_injection", "mode": "adaptive"}).json()
    assert first["attacker_model"] == "deepseek/deepseek-v3.2"
    assert second["attacker_model"] == "qwen/qwen3.2"
    # The earlier run still names the model that drove it.
    assert api2.get(f"/api/runs/{first['id']}").json()["attacker_model"] == "deepseek/deepseek-v3.2"
