"""On start-up, a run left in progress by a stopped process is closed as "unclear" (FR-031, SC-012)."""
import httpx
import pytest
from cryptography.fernet import Fernet

from kestrel.secrets import Vault
from kestrel.store import TargetStore
from tests.support import StubJudge, fixture_library

SECRET = "s3cret-header-value"


def connection(**changes):
    base = {"url": "http://agent.test/chat", "method": "POST", "headers": [{"name": "X-API-Key", "value": SECRET}],
            "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply"}
    return {**base, **changes}


def seed_interrupted_run(settings):
    """Create a target with a run stuck in progress, as a crash mid-run would leave it."""
    store = TargetStore(settings.db_path, _vault(settings))
    target = store.create_target(name="HS Agent", url="http://agent.test/chat", method="POST",
                                 headers=[("X-API-Key", SECRET)], body_template='{"message": "{{prompt}}"}',
                                 response_path="$.reply", terms_version="2")
    store.claim_run(target.id, prompt_id="spl-001", prompt_title="t", prompt_text="x", family="system_prompt_leak",
                    owasp_category="LLM07: System Prompt Leakage", attacker_source="library:1.0.0")
    return target.id


def _vault(settings):
    from kestrel.secrets import load_or_create_key
    import logging
    key, _ = load_or_create_key(settings, logging.getLogger("test"))
    return Vault(key)


def test_startup_closes_an_interrupted_run_and_logs_it(make_client, settings, all_logs):
    target_id = seed_interrupted_run(settings)
    api = make_client(settings, library=fixture_library(), judge=StubJudge())
    runs = api.get(f"/api/targets/{target_id}/runs").json()
    assert runs[0]["verdict"] == "unclear"
    detail = api.get(f"/api/runs/{runs[0]['id']}").json()
    assert "interrupted" in detail["reason"].lower()
    assert "interrupted" in all_logs().lower()


def test_the_target_can_run_again_after_the_sweep(make_client, settings):
    target_id = seed_interrupted_run(settings)
    api = make_client(settings, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"reply": "ok"})),
                      library=fixture_library(), judge=StubJudge())
    # The sweep released the one-in-progress lock, so a new run is accepted (not 409).
    response = api.post("/api/runs", json={"target_id": target_id, "family": "system_prompt_leak"})
    assert response.status_code == 201
