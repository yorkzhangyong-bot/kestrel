"""GET /api/attack-families and GET /api/attack-prompts (contracts/kestrel-api.md, FR-002, FR-003, FR-005, FR-008)."""
import pytest

from tests.support import fixture_library


@pytest.fixture
def api(make_client):
    return make_client(library=fixture_library())


def test_families_list_the_four_with_their_category_and_count(api):
    body = api.get("/api/attack-families").json()
    assert body["library_version"] == "1.0.0"
    keys = {f["key"] for f in body["families"]}
    assert keys == {"direct_injection", "system_prompt_leak", "tool_exfiltration", "indirect_injection"}
    leak = next(f for f in body["families"] if f["key"] == "system_prompt_leak")
    assert leak["owasp_category"] == "LLM07: System Prompt Leakage" and leak["prompt_count"] == 5


def test_prompts_in_a_family_are_returned(api):
    body = api.get("/api/attack-prompts", params={"family": "system_prompt_leak"}).json()
    assert len(body["prompts"]) == 5
    assert {p["family"] for p in body["prompts"]} == {"system_prompt_leak"}
    assert all(p["id"] and p["title"] and p["text"] for p in body["prompts"])


def test_an_unknown_family_is_422_on_family(api):
    response = api.get("/api/attack-prompts", params={"family": "nonsense"})
    assert response.status_code == 422 and response.json()["errors"][0]["field"] == "family"


def test_the_routes_report_when_no_library_is_loaded(api):
    api.app.state.library = None  # force "no library available", whatever is on disk
    assert api.get("/api/attack-families").status_code == 503
    assert api.get("/api/attack-prompts", params={"family": "system_prompt_leak"}).status_code == 503
