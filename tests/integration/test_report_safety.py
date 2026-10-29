"""Generating a report is safe and read-only (US4, FR-003/016/018, SC-006/007).

It starts no attack, sends nothing to the target, writes nothing to the experience store, and leaks no auth
value, URL or header name into either output format.
"""
import httpx

from kestrel.experience.store import ExperienceStore
from tests.support import StubEmbeddingFunction, StubJudge, fixture_library

FEATURE = "005"

SECRET = "s3cret-auth-value-xyz"
URL = "http://127.0.0.1:8109/private-chat"
HEADER_NAME = "X-Secret-Header"


class SpyExperience(ExperienceStore):
    """A real stub-backed store that records every write, so the test can prove report generation adds none."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.writes: list[str] = []

    def seed_patterns(self, library):
        self.writes.append("seed_patterns")
        return super().seed_patterns(library)

    def write_memory(self, **kwargs):
        self.writes.append("write_memory")
        return super().write_memory(**kwargs)

    def write_pattern(self, **kwargs):
        self.writes.append("write_pattern")
        return super().write_pattern(**kwargs)

    def delete_target_memory(self, target_id):
        self.writes.append("delete_target_memory")
        return super().delete_target_memory(target_id)

    def self_check(self):
        self.writes.append("self_check")
        return super().self_check()


def spy_transport() -> tuple[httpx.MockTransport, list]:
    sends: list = []

    def handler(request):
        sends.append(request.url)
        return httpx.Response(200, json={"reply": "hello"})
    return httpx.MockTransport(handler), sends


def a_target_with_a_secret(store):
    return store.create_target(name="Guarded agent", url=URL, method="POST",
                               headers=[(HEADER_NAME, SECRET)], body_template='{"message": "{{prompt}}"}',
                               response_path="$.reply", terms_version="5", description="a customs assistant").id


def seed_success(store, tid):
    run_id = store.claim_run(tid, prompt_id="spl-001", prompt_title="t", prompt_text="<seed>",
                             family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                             attacker_source="library:1.0.0")
    store.finish_run(run_id, verdict="succeeded", hard_evidence=True, reply_text="...KESTREL-CANARY-9Z...")


def _report_client(make_client, settings):
    transport, sends = spy_transport()
    experience = SpyExperience(settings.chroma_path, embedding_function=StubEmbeddingFunction())
    api = make_client(transport=transport, library=fixture_library(), judge=StubJudge(), experience=experience)
    tid = a_target_with_a_secret(api.app.state.store)
    seed_success(api.app.state.store, tid)
    return api, tid, sends, experience


def test_report_sends_nothing_and_writes_nothing(make_client, settings):
    api, tid, sends, experience = _report_client(make_client, settings)
    before = list(experience.writes)   # whatever startup did (e.g. pattern seeding) is the baseline

    api.get(f"/api/targets/{tid}/report?format=md")
    api.get(f"/api/targets/{tid}/report?format=html")

    assert sends == []                          # 0 requests reached the target (SC-007)
    assert experience.writes == before          # report generation added no experience-store write (SC-006)


def test_neither_format_leaks_url_headers_or_secret(make_client, settings):
    api, tid, _sends, _experience = _report_client(make_client, settings)
    md = api.get(f"/api/targets/{tid}/report?format=md").text
    html = api.get(f"/api/targets/{tid}/report?format=html").text
    for output in (md, html):
        assert SECRET not in output          # the auth value never appears
        assert URL not in output             # the target URL never appears
        assert HEADER_NAME not in output     # header names never appear
