"""GET /api/config exposes the active prompt versions — id + version only, never the prompt text
(009/FR-007, 009/SC-004, 009/FR-012)."""
FEATURE = "009"

EXPECTED_IDS = {
    "attacker:direct_injection",
    "attacker:system_prompt_leak",
    "attacker:tool_exfiltration",
    "attacker:indirect_injection",
    "judge",
    "recommender",
}


def test_config_lists_active_prompt_versions(client):  # 009/FR-007
    prompts = client.get("/api/config").json()["prompts"]
    assert {p["id"] for p in prompts} == EXPECTED_IDS
    assert all(p["version"] == "1.0.0" for p in prompts)


def test_config_prompts_carry_only_id_and_version(client):  # 009/SC-004, 009/FR-012
    prompts = client.get("/api/config").json()["prompts"]
    assert prompts and all(set(p) == {"id", "version"} for p in prompts)   # never the prompt text or a secret
