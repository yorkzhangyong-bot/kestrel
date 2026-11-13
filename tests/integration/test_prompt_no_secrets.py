"""Feature 009 security: the committed lock, the registry and the /api/config surface carry only ids, versions and
fingerprints — never prompt text, a target secret, or attack-library fixtures; the prompt files hold Kestrel's own
operational prompts and no library payload (009/FR-011, 009/FR-012, 009/SC-007)."""
import json
import re

from kestrel import prompt_registry as pr
from kestrel.attacks.library import load_library

FEATURE = "009"

HEX64 = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_IDS = {
    "attacker:direct_injection",
    "attacker:system_prompt_leak",
    "attacker:tool_exfiltration",
    "attacker:indirect_injection",
    "judge",
    "recommender",
}


def test_the_lock_holds_only_ids_versions_and_fingerprints():  # 009/FR-011, 009/SC-007
    lock = json.loads(pr.LOCK_PATH.read_text(encoding="utf-8"))
    assert set(lock) == EXPECTED_IDS
    for versions in lock.values():
        assert versions and all(pr.is_valid_version(v) for v in versions)
        assert all(HEX64.match(fp) for fp in versions.values())   # fingerprints only, never text


def test_the_prompt_files_carry_no_attack_library_fixture_text():  # 009/FR-011, 009/SC-007
    library = load_library()
    texts = [entry.text for entry in pr.registry()]
    for family in library.families():
        for prompt in library.prompts_in(family["key"]):
            assert not any(prompt.text in text for text in texts)


def test_the_registry_ingests_only_the_three_prompt_kinds():  # 009/FR-011
    assert {e.id for e in pr.registry()} == EXPECTED_IDS   # attack-library fixtures are never pulled into the registry


def test_config_prompts_expose_only_id_and_version(client):  # 009/FR-012, 009/SC-007
    prompts = client.get("/api/config").json()["prompts"]
    assert prompts and all(set(p) == {"id", "version"} for p in prompts)   # no text, fingerprint, or secret on the wire
