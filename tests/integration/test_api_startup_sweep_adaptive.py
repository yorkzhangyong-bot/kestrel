"""An interrupted adaptive run is swept to "unclear" on start-up, keeping its turns (FR-022, SC-010)."""
import logging

import httpx

from kestrel.api.main import load_terms
from kestrel.secrets import Vault, load_or_create_key
from kestrel.store import TargetStore
from tests.support import StubAttacker, StubJudge, fixture_library

SECRET = "s3cret-header-value"
CURRENT_TERMS = load_terms().version


def connection(**changes):
    base = {"url": "http://127.0.0.1:8102/chat", "method": "POST",
            "headers": [{"name": "X-API-Key", "value": SECRET}],
            "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply"}
    return {**base, **changes}


def _store(settings) -> TargetStore:
    key, _ = load_or_create_key(settings, logging.getLogger("test"))
    return TargetStore(settings.db_path, Vault(key))


def seed_interrupted_adaptive(settings):
    store = _store(settings)
    target = store.create_target(name="A", url="http://127.0.0.1:8102/chat", method="POST",
                                 headers=[("X-API-Key", SECRET)], body_template='{"message": "{{prompt}}"}',
                                 response_path="$.reply", terms_version=CURRENT_TERMS)
    run_id = store.claim_run(target.id, prompt_id="spl-001", prompt_title="t", prompt_text="x",
                             family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                             attacker_source="library:1.0.0", mode="adaptive", attacker_model="deepseek/deepseek-v3.2",
                             turn_budget=6, token_budget=40000, time_limit_s=300)
    store.add_turn(run_id, position=1, attacker_message="<m1>", reply_text="<r1>", judge_verdict="failed")
    return target.id, run_id


def test_startup_closes_an_interrupted_adaptive_run_keeping_its_turns(make_client, settings, all_logs):
    target_id, run_id = seed_interrupted_adaptive(settings)
    api = make_client(settings, library=fixture_library(), judge=StubJudge(), attacker=StubAttacker())
    detail = api.get(f"/api/runs/{run_id}").json()
    assert detail["verdict"] == "unclear" and detail["stopping_condition"] == "interrupted"
    assert len(detail["turns"]) == 1  # the turn stored before the interruption is kept
    assert "interrupted" in all_logs().lower()


def test_the_target_can_run_again_after_the_adaptive_sweep(make_client, settings):
    target_id, _ = seed_interrupted_adaptive(settings)
    api = make_client(settings, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"reply": "ok"})),
                      library=fixture_library(), judge=StubJudge(), attacker=StubAttacker())
    r = api.post("/api/runs", json={"target_id": target_id, "family": "system_prompt_leak", "mode": "adaptive"})
    assert r.status_code == 201
