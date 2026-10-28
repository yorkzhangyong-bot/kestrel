"""Feature 005 e2e (T027, required): one real attack against the sacrificial target, then generate the OWASP
report in both formats and confirm the run shows up in the coverage table and that report generation is read-only
(the experience-store record count does not change).

Skipped without OPENROUTER_API_KEY (the target makes real model calls) and until the attack library is assembled.
The database and ChromaDB store are isolated under a temp dir by the `kestrel_api` fixture (its own
KESTREL_DB_PATH and KESTREL_CHROMA_PATH), so this never touches the repo's data/.
"""
import httpx
import pytest

pytestmark = pytest.mark.e2e


def save_target(at, fill_form, hs_target):
    at = fill_form(at, display_name="HS-code target")
    at.button(key="test_button").click().run()
    assert at.success and "Connection works" in at.success[0].value
    # Declare the canary the target carries, so a leak would be provable hard evidence (Principle II).
    at.button(key="add_canary").click().run()
    at.text_input(key="canary_0").input(hs_target.canary).run()
    at.checkbox(key="permission").check().run()
    at.button(key="save_button").click().run()
    assert at.dataframe, "the target should be saved and listed"
    return at


def run_one_attack(at):
    at.selectbox(key="target_select").select(1).run()
    at.selectbox(key="attack_family").select("system_prompt_leak").run()
    prompt_ids = [pid for pid in at.selectbox(key="attack_prompt").options if pid is not None]
    assert prompt_ids, "the system_prompt_leak family should offer prompts"
    at.selectbox(key="attack_prompt").select(prompt_ids[0]).run()
    at.button(key="run_button").click().run()
    assert not at.exception
    run = at.session_state["run_result"]
    assert run is not None and run["verdict"] in ("succeeded", "failed", "unclear")   # the run completed


def coverage_line(markdown: str, owasp_class: str) -> str:
    return next((line for line in markdown.splitlines() if owasp_class in line), "")


def test_report_e2e_runs_an_attack_then_reports_read_only(ui, kestrel_api, fill_form, hs_target, library_required):
    at = save_target(ui, fill_form, hs_target)
    run_one_attack(at)
    base = kestrel_api.url

    # The experience-store record count for this target, from an endpoint independent of the report.
    before = httpx.get(f"{base}/api/targets/1/profile", timeout=30).json()["total_runs"]

    md = httpx.get(f"{base}/api/targets/1/report", params={"format": "md"}, timeout=90)
    html = httpx.get(f"{base}/api/targets/1/report", params={"format": "html"}, timeout=90)
    assert md.status_code == 200 and md.headers["content-type"].startswith("text/markdown")
    assert html.status_code == 200 and html.headers["content-type"].startswith("text/html")
    assert "<html" in html.text.lower()

    # The run appears in the coverage table under its OWASP class, not as "not run yet".
    line = coverage_line(md.text, "LLM07: System Prompt Leakage")
    assert "run(s)" in line and "not run yet" not in line

    # Generating the report wrote nothing to the experience store: the record count is unchanged (read-only).
    after = httpx.get(f"{base}/api/targets/1/profile", timeout=30).json()["total_runs"]
    assert after == before
