"""The per-target profile summarises that target's memory, secrets-free (FR-022, FR-023, SC-013)."""
import uuid

import httpx

from kestrel.api.main import load_terms
from tests.support import StubJudge, fixture_library

SECRET = "s3cret-header-value"
CURRENT_TERMS = load_terms().version
REPLY = httpx.MockTransport(lambda r: httpx.Response(200, json={"reply": "ok"}))


def connection():
    return {"url": "http://127.0.0.1:8102/chat", "method": "POST",
            "headers": [{"name": "X-API-Key", "value": SECRET}],
            "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply"}


def save_target(api) -> int:
    form_id = str(uuid.uuid4())
    assert api.post("/api/connection-tests", json={"form_id": form_id, "target_id": None, "display_name": "A",
                                                   "settings": connection()}).json()["ok"]
    return api.post("/api/targets", json={"form_id": form_id, "name": "A", "settings": connection(),
                                          "permission_confirmed": True, "terms_version": CURRENT_TERMS}).json()["id"]


def test_profile_counts_runs_by_family_and_verdict_with_recent_summaries(make_client):
    api = make_client(transport=REPLY, library=fixture_library(), judge=StubJudge(verdict="failed"))
    tid = save_target(api)
    for _ in range(2):
        api.post("/api/runs", json={"target_id": tid, "family": "system_prompt_leak", "mode": "single_turn"})
    profile = api.get(f"/api/targets/{tid}/profile").json()
    assert profile["total_runs"] == 2
    assert {"family": "system_prompt_leak", "count": 2} in profile["by_family"]
    assert {"verdict": "failed", "count": 2} in profile["by_verdict"]
    assert len(profile["recent"]) == 2
    assert SECRET not in str(profile) and "http://127.0.0.1:8102/chat" not in str(profile)  # SC-013


def test_an_unused_target_has_an_empty_profile(make_client):
    api = make_client(transport=REPLY, library=fixture_library(), judge=StubJudge())
    tid = save_target(api)
    profile = api.get(f"/api/targets/{tid}/profile").json()
    assert profile["total_runs"] == 0 and profile["by_family"] == [] and profile["recent"] == []


def test_a_missing_target_profile_is_404(make_client):
    api = make_client(transport=REPLY, library=fixture_library(), judge=StubJudge())
    assert api.get("/api/targets/9999/profile").status_code == 404
