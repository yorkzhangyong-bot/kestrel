"""GET /api/targets/{id}/report: both formats, bad format, missing target, empty state (US1, FR-002/3/19)."""
from tests.support import StubJudge, fixture_library

FEATURE = "005"

SECRET = "s3cret-header-value"


def a_target(store, name="HS agent"):
    return store.create_target(name=name, url="http://127.0.0.1:8102/chat", method="POST",
                               headers=[("X-API-Key", SECRET)], body_template='{"message": "{{prompt}}"}',
                               response_path="$.reply", terms_version="4", description="a customs assistant").id


def seed_runs(store, tid):
    r1 = store.claim_run(tid, prompt_id="spl-001", prompt_title="t", prompt_text="<seed>", family="system_prompt_leak",
                         owasp_category="LLM07: System Prompt Leakage", attacker_source="library:1.0.0")
    store.finish_run(r1, verdict="failed", reason="held", judge_used=True, judge_model="google/gemini-3.8-flash")
    r2 = store.claim_run(tid, prompt_id="dir-001", prompt_title="t", prompt_text="<seed>", family="direct_injection",
                         owasp_category="LLM01: Prompt Injection", attacker_source="library:1.0.0", mode="adaptive",
                         attacker_model="deepseek/deepseek-v4.1-flash", turn_budget=6, token_budget=40000)
    store.finish_run(r2, verdict="unclear", reason="stopped", judge_used=True, judge_model="google/gemini-3.8-flash",
                     stopping_condition="turn_cap", turns_used=6, tokens_used=1200)


def test_report_markdown_and_html(make_client):
    api = make_client(library=fixture_library(), judge=StubJudge())
    tid = a_target(api.app.state.store)
    seed_runs(api.app.state.store, tid)

    md = api.get(f"/api/targets/{tid}/report?format=md")
    assert md.status_code == 200 and md.headers["content-type"].startswith("text/markdown")
    assert "HS agent" in md.text and "a customs assistant" in md.text
    assert "system_prompt_leak" in md.text and "direct_injection" in md.text    # the two runs appear
    assert "Limitations" in md.text

    html = api.get(f"/api/targets/{tid}/report?format=html")
    assert html.status_code == 200 and html.headers["content-type"].startswith("text/html")
    assert "<html" in html.text.lower()


def test_default_format_is_markdown(make_client):
    api = make_client(library=fixture_library(), judge=StubJudge())
    tid = a_target(api.app.state.store)
    seed_runs(api.app.state.store, tid)
    r = api.get(f"/api/targets/{tid}/report")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/markdown")


def test_a_bad_format_is_rejected(make_client):
    api = make_client(library=fixture_library(), judge=StubJudge())
    tid = a_target(api.app.state.store)
    assert api.get(f"/api/targets/{tid}/report?format=pdf").status_code == 422


def test_a_missing_target_is_404(make_client):
    api = make_client(library=fixture_library(), judge=StubJudge())
    assert api.get("/api/targets/9999/report").status_code == 404


def test_empty_state_for_a_target_with_no_runs(make_client):
    judge = StubJudge()
    api = make_client(library=fixture_library(), judge=judge)
    tid = a_target(api.app.state.store, name="Fresh agent")
    r = api.get(f"/api/targets/{tid}/report?format=md")
    assert r.status_code == 200 and "No runs to report yet" in r.text
    assert judge.calls == []   # no model call for an empty report (SC-009)
