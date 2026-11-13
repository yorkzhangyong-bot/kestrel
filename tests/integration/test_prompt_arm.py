"""Feature 009 US4: a prompt-version A/B arm — validation, the recorded diff, persistence, the client override, and
the older prompt file as the non-active version (009/FR-008, 009/FR-009, 009/SC-005). Offline; no models."""
import pytest
from cryptography.fernet import Fernet

from kestrel import prompt_registry as pr
from kestrel.api.schemas import ArmIn, CapsIn, CreateExperimentRequest, experiment_diff, validate_experiment
from kestrel.attack.attacker import AttackerClient
from kestrel.judge.client import JudgeClient
from kestrel.secrets import Vault
from kestrel.store import TargetStore

FEATURE = "009"

FAMILIES = ["direct_injection", "system_prompt_leak", "tool_exfiltration", "indirect_injection"]


def _arm(**over):
    base = dict(attacker_model="m", judge_model="j", use_prior_experience=False, turn_cap=6,
                token_budget=40000, write_back=True)
    base.update(over)
    return ArmIn(**base)


def _request(arm_a, arm_b):
    return CreateExperimentRequest(target_id=1, mode="adaptive", families=["direct_injection"], reps=1,
                                   caps=CapsIn(), arm_a=arm_a, arm_b=arm_b)


@pytest.fixture
def two_judge_versions(monkeypatch):
    """Pretend the registry also knows judge@2 (the shipped registry has only version 1)."""
    real_has = pr.has
    monkeypatch.setattr(pr, "has", lambda i, v: (i == "judge" and v in ("1", "2")) or real_has(i, v))


def test_two_arms_differing_only_by_judge_version_are_valid(two_judge_versions):  # 009/FR-008
    req = _request(_arm(prompt_arm_target="judge", prompt_arm_version="1"),
                   _arm(prompt_arm_target="judge", prompt_arm_version="2"))
    assert validate_experiment(req, FAMILIES) == []


def test_a_recommender_arm_is_refused():  # 009/FR-008
    req = _request(_arm(), _arm(prompt_arm_target="recommender", prompt_arm_version="1"))
    assert any("attacker or judge" in e["message"] for e in validate_experiment(req, FAMILIES))


def test_an_absent_version_is_refused():  # 009/FR-009
    req = _request(_arm(), _arm(prompt_arm_target="judge", prompt_arm_version="99"))
    assert any("Unknown prompt judge@99" in e["message"] for e in validate_experiment(req, FAMILIES))


def test_half_a_pin_is_refused():  # 009/FR-008
    req = _request(_arm(), _arm(prompt_arm_target="judge"))   # version missing
    assert any("both a prompt and a version" in e["message"] for e in validate_experiment(req, FAMILIES))


def test_the_diff_names_the_prompt_and_both_versions(two_judge_versions):  # 009/SC-005
    a = _arm(prompt_arm_target="judge", prompt_arm_version="1")
    b = _arm(prompt_arm_target="judge", prompt_arm_version="2")
    assert "prompt: A=judge@1, B=judge@2" in experiment_diff(a, b)


def test_the_arm_round_trips_through_the_store(tmp_path):  # 009/FR-008
    store = TargetStore(tmp_path / "k.db", Vault(Fernet.generate_key()))
    target = store.create_target(name="A", url="http://t/chat", method="POST", headers=[("X-API-Key", "k")],
                                 body_template='{"message": "{{prompt}}"}', response_path="$.reply", terms_version="7")
    exp = store.create_experiment(target_id=target.id, mode="adaptive", families=["direct_injection"], reps=1,
                                  seed_prompt_ids={}, max_runs=2, token_budget_total=40000, wall_clock_s=300,
                                  arm_a=_arm().model_dump(),
                                  arm_b=_arm(prompt_arm_target="judge", prompt_arm_version="1").model_dump())
    a = next(arm for arm in exp.arms if arm.label == "A")
    b = next(arm for arm in exp.arms if arm.label == "B")
    assert a.prompt_arm_target is None and a.prompt_arm_version is None
    assert b.prompt_arm_target == "judge" and b.prompt_arm_version == "1"


def test_the_clients_apply_a_pinned_prompt():  # 009/FR-008
    attacker = AttackerClient(model="m", api_key="k", base_url="http://x",
                              system_overrides={"direct_injection": "PINNED ATTACKER TEXT"})
    assert "PINNED ATTACKER TEXT" in attacker._payload([], None, "direct_injection")["messages"][0]["content"]
    assert "PINNED ATTACKER TEXT" not in attacker._payload([], None, "system_prompt_leak")["messages"][0]["content"]
    judge = JudgeClient(model="j", api_key="k", base_url="http://x", system_prompt="PINNED JUDGE TEXT")
    assert "PINNED JUDGE TEXT" in judge._judge_messages("attack", "reply", None)[0]["content"]


def test_text_for_reads_an_older_file_as_the_non_active_version(tmp_path, monkeypatch):  # 009/FR-008 (US4)
    monkeypatch.setattr(pr, "PROMPTS_DIR", tmp_path)
    monkeypatch.setattr(pr, "LOCK_PATH", tmp_path / "prompt_versions.lock.json")
    for version, text in (("1", "the first judge prompt"), ("2", "the second judge prompt")):
        pr.prompt_path("judge", version, tmp_path).write_text(pr.format_prompt_file("judge", version, text),
                                                              encoding="utf-8", newline="\n")
    pr.write_lock({"judge": {"1": pr.fingerprint("the first judge prompt"),
                             "2": pr.fingerprint("the second judge prompt")}})
    assert pr.active_version("judge") == "2"
    assert pr.text_for("judge", "1") == "the first judge prompt"   # the older file is what an arm can pin
    assert pr.verify_lock() == []   # both files match their pinned fingerprints
