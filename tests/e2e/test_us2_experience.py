"""Spec acceptance (SC-012, FR-026): two warm runs against the live sacrificial target, where the second run's
attacker is given at least one memory record produced by the first.

End to end with real pieces — the real HS-code target subprocess, the real judge, and the real ChromaDB store with
its default local embeddings (downloaded once). The API runs in-process so a spy attacker can record the hints it
receives; the spy wraps a real AttackerClient, so even if the attacker model refuses or is blocked, the hints it was
given on the second run are still observed (the feature-002/003 model-determinism caveat applies)."""
import os

import pytest
from fastapi.testclient import TestClient

from kestrel.api.main import create_app
from kestrel.attack.attacker import AttackerClient
from kestrel.settings import Settings

FEATURE = "004"

pytestmark = pytest.mark.e2e

MEMORY_SECTION = "What happened before against this target:"  # the label format_hints uses for memory (contracts)


class SpyAttacker:
    """Wraps the real attacker and records the hints block it is given each turn."""

    def __init__(self, inner: AttackerClient) -> None:
        self._inner = inner
        self.hints_seen: list[str | None] = []

    @property
    def configured(self) -> bool:
        return self._inner.configured

    @property
    def model(self) -> str:
        return self._inner.model

    async def next_message(self, *, conversation, family, progress=None, hints=None, timeout=None):
        self.hints_seen.append(hints)  # record before delegating, so a failing call is still observed
        return await self._inner.next_message(conversation=conversation, family=family, progress=progress,
                                              hints=hints, timeout=timeout)


def _settings(tmp_path) -> Settings:
    key = os.environ["OPENROUTER_API_KEY"]
    return Settings(mode="local", db_path=tmp_path / "data" / "kestrel.db", key_file=tmp_path / "secret.key",
                    secret_key=None, chroma_path=tmp_path / "data" / "chroma",   # isolated store (G1)
                    judge_api_key=key, attacker_api_key=key, adaptive_max_turns=2, adaptive_time_limit_s=120)


def _save_target(api, hs_target) -> int:
    import uuid
    form_id = str(uuid.uuid4())
    settings = {"url": hs_target.url, "method": "POST", "headers": [{"name": "X-API-Key", "value": hs_target.key}],
                "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply"}
    assert api.post("/api/connection-tests", json={"form_id": form_id, "target_id": None, "display_name": "HS",
                                                   "settings": settings}).json()["ok"]
    return api.post("/api/targets", json={"form_id": form_id, "name": "HS-code target", "settings": settings,
                                          "permission_confirmed": True,
                                          "terms_version": api.get("/api/config").json()["terms"]["version"],
                                          "canaries": [hs_target.canary]}).json()["id"]


def test_the_second_warm_run_attacker_gets_memory_from_the_first(tmp_path, hs_target, library_required):
    settings = _settings(tmp_path)
    spy = SpyAttacker(AttackerClient(model=settings.attacker_model, api_key=settings.attacker_api_key,
                                     base_url=settings.attacker_base_url))
    with TestClient(create_app(settings, attacker=spy)) as api:
        tid = _save_target(api, hs_target)

        first = api.post("/api/runs", json={"target_id": tid, "family": "system_prompt_leak", "mode": "adaptive",
                                            "use_prior_experience": True}).json()
        assert first["use_prior_experience"] is True
        assert first["verdict"] in ("succeeded", "failed", "unclear")
        assert api.get(f"/api/targets/{tid}/profile").json()["total_runs"] == 1  # the first run wrote back (FR-006)

        hints_before = len(spy.hints_seen)
        second = api.post("/api/runs", json={"target_id": tid, "family": "system_prompt_leak", "mode": "adaptive",
                                             "use_prior_experience": True}).json()
        assert second["verdict"] in ("succeeded", "failed", "unclear")

        # The attacker was driven on the second run and at least one of those hint blocks carried this target's
        # memory from the first run (SC-012, FR-026).
        second_run_hints = [h for h in spy.hints_seen[hints_before:] if h]
        assert second_run_hints, "the attacker generated at least one turn on the second run"
        assert any(MEMORY_SECTION in h for h in second_run_hints)
        assert api.get(f"/api/targets/{tid}/profile").json()["total_runs"] == 2
