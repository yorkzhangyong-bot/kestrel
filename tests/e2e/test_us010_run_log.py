"""Spec acceptance (010/SC-001, 010/SC-002): a real adaptive run against the live HS-code target, through Kestrel's
API running as its own process. Its kept log is served as JSON objects — run.start naming the attacker and judge
prompt references and model slugs — and the target's real key appears zero times in the served lines and in the API's
log output, every Kestrel line of which is JSON. Skipped without OPENROUTER_API_KEY. No attack text — behaviour only."""
import json
import re
import uuid

import httpx
import pytest

FEATURE = "010"

pytestmark = pytest.mark.e2e


def test_a_real_runs_log_is_json_names_its_prompts_and_never_the_key(hs_target, kestrel_api, library_required,
                                                                     assert_no_secret_in_logs):  # SC-001, SC-002
    with httpx.Client(base_url=kestrel_api.url, timeout=360) as api:
        form_id = str(uuid.uuid4())
        settings = {"url": hs_target.url, "method": "POST",
                    "headers": [{"name": "X-API-Key", "value": hs_target.key}],
                    "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply"}
        tested = api.post("/api/connection-tests", json={"form_id": form_id, "target_id": None,
                                                         "display_name": "HS", "settings": settings})
        assert tested.json()["ok"], tested.text
        terms = api.get("/api/config").json()["terms"]["version"]
        saved = api.post("/api/targets", json={"form_id": form_id, "name": "HS-code target", "settings": settings,
                                               "permission_confirmed": True, "terms_version": terms,
                                               "canaries": [hs_target.canary]})
        assert saved.status_code == 201, saved.text
        run = api.post("/api/runs", json={"target_id": saved.json()["id"], "family": "system_prompt_leak",
                                          "mode": "adaptive", "use_prior_experience": False}).json()
        assert run["verdict"] in ("succeeded", "failed", "unclear")

        served = api.get(f"/api/runs/{run['id']}/log")
        assert served.status_code == 200
        lines = served.json()["lines"]

    assert lines and lines[0]["event"] == "run.start" and lines[-1]["event"] in ("run.end", "log.truncated")
    start = lines[0]
    assert re.fullmatch(r"attacker:system_prompt_leak@\d+", start["attacker_prompt"])
    assert re.fullmatch(r"judge@\d+", start["judge_prompt"])
    assert start["attacker_model"] and start["judge_model"]
    assert any(line["event"] == "turn" for line in lines) and all(line["run_id"] == run["id"] for line in lines)
    assert served.text.count(hs_target.key) == 0

    assert_no_secret_in_logs()   # the key: zero times in the API's and the target's output
    output = kestrel_api.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    kestrel_lines = [json.loads(line) for line in output if line.startswith("{")]   # uvicorn's own lines are text
    assert any(record.get("event") == "run.end" and record.get("run_id") == run["id"] for record in kestrel_lines)
