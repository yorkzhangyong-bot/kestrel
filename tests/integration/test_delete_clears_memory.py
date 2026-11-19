"""Deleting a target deletes its memory; shared patterns survive (FR-024, FR-025, SC-010).

Changed on purpose by feature 011 (011/FR-006, 011/FR-008, 011/SC-009): the single-turn success below replays its
library seed verbatim, which now *merges* into that seed — its hit count rises, no pattern is added — instead of
adding a success-derived copy. The deletion assertions (memory gone, the shared pattern count unchanged) are as
they were."""
import uuid

import httpx

from kestrel.api.main import load_terms
from tests.support import StubJudge, fixture_library

FEATURE = "004"

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
    run = api.post("/api/runs", json={"target_id": tid, "family": "system_prompt_leak",
                                      "mode": "single_turn"}).json()

    experience = api.app.state.experience
    assert experience.count("memory", target_id=tid) >= 1
    patterns_before = experience.count("pattern")
    # 011/FR-006, 011/FR-008: the success replayed its seed verbatim, so it merged into the seed — no copy added.
    assert patterns_before == len(fixture_library().prompts)
    seed = experience._collection.get(ids=[f"pattern:lib:{run['prompt_id']}"], include=["metadatas"])
    assert seed["metadatas"][0]["hit_count"] == 2 and seed["metadatas"][0]["last_hit_run_id"] == run["id"]

    assert api.delete(f"/api/targets/{tid}").status_code == 204
    assert experience.count("memory", target_id=tid) == 0          # FR-024, SC-010
    assert experience.count("pattern") == patterns_before          # FR-025: shared patterns survive
