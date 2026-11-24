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
    # Feature 013 (013/SC-008): the planting template the two injection families fill per run.
    "override_task",
}
# Feature 013: the attacker prompts the planted-task families got a new version of (contracts/prompts.md).
BUMPED_IDS = {"attacker:direct_injection", "attacker:indirect_injection"}


def test_config_lists_active_prompt_versions(client):  # 009/FR-007, 013/SC-008
    prompts = client.get("/api/config").json()["prompts"]
    assert {p["id"] for p in prompts} == EXPECTED_IDS
    assert all(p["version"] == ("2" if p["id"] in BUMPED_IDS else "1") for p in prompts)


def test_config_prompts_carry_only_id_and_version(client):  # 009/SC-004, 009/FR-012
    prompts = client.get("/api/config").json()["prompts"]
    assert prompts and all(set(p) == {"id", "version"} for p in prompts)   # never the prompt text or a secret
