"""Deleting a target deletes its memory; shared patterns survive (FR-024, FR-025, SC-010)."""
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


def test_delete_removes_memory_and_keeps_patterns(make_client):
    # A succeeding judge so the run also contributes a shared pattern.
    api = make_client(transport=REPLY, library=fixture_library(), judge=StubJudge(verdict="succeeded"))
    tid = save_target(api)
    api.post("/api/runs", json={"target_id": tid, "family": "system_prompt_leak", "mode": "single_turn"})

    experience = api.app.state.experience
    assert experience.count("memory", target_id=tid) >= 1
    patterns_before = experience.count("pattern")
    assert patterns_before > len(fixture_library().prompts)  # the seed plus the success-derived pattern

    assert api.delete(f"/api/targets/{tid}").status_code == 204
    assert experience.count("memory", target_id=tid) == 0          # FR-024, SC-010
    assert experience.count("pattern") == patterns_before          # FR-025: shared patterns survive
