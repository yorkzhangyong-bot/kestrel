"""Spec acceptance (011/FR-018, 011/SC-010): the shipped retrieval controls on the real embedding model, against the
live HS-code sacrificial target with the real attacker and judge, through the API running in-process (as
tests/e2e/test_us2_experience.py does) on a temporary store.

Two warm adaptive runs of the `system_prompt_leak` family under a turn cap of four (a time limit that fits four
real turns); while no run has reached turn 4 — a run ends early on success, an attacker or send failure, the token
or time limit, and then never issues a seedless query — up to two more are started, four at most. The kept lines of
every run are read through `GET /api/runs/{id}/log`: first, at least one `memory.retrieval` line must exist (no
vacuous pass); then every such line carries the shipped settings, counts that add up and at least one selected
pattern within the floor; and at least one turn-4 line — a query without the seed — selects a pattern, or the test
fails. Then, on the same store with the real model, a neutral document, its one-word variant and its paraphrase
are written back at the shipped threshold (added, merged with hit count 2, added); the store records the model
name and the `l2` space; and the shipped default embedding and the model it is recorded under embed one neutral
probe identically. The target's key appears zero times on the stream, in the served lines and in the target's own
output. No attack text — behaviour only; the write-back sentences are neutral shipping questions."""
import os
import uuid

import pytest
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction, ONNXMiniLM_L6_V2
from fastapi.testclient import TestClient

from kestrel.api.main import create_app
from kestrel.attacks.library import FAMILIES
from kestrel.experience.retrieval import squared_distance
from kestrel.experience.store import DEFAULT_EMBEDDING_MODEL, DISTANCE_SPACE, ExperienceStore
from kestrel.settings import Settings

FEATURE = "011"

pytestmark = pytest.mark.e2e

FAMILY = "system_prompt_leak"
TURN_CAP = 4
MIN_RUNS, MAX_RUNS = 2, 4
SHIPPED = {"k": 5, "distance_floor": 1.8, "dedupe_threshold": 0.15}
# Metadata only (`origin_run_id`): write_pattern's added ids are unique uuids since the 011 post-review fix, so
# these need not avoid colliding with any real run id. Kept as obviously-fake numbers for readability below.
WRITEBACK_RUN_IDS = (900001, 900002, 900003)
DOCUMENT = "Please summarise the shipping rules for fragile goods in two sentences."
VARIANT = "Please summarise the shipping rules for fragile items in two sentences."          # one word changed
PARAPHRASE = "In two sentences, give me a summary of how fragile goods must be shipped."
PROBE = "A neutral probe sentence about shipping schedules and tariff codes."


def _settings(tmp_path) -> Settings:
    key = os.environ["OPENROUTER_API_KEY"]
    return Settings(mode="local", db_path=tmp_path / "data" / "kestrel.db", key_file=tmp_path / "secret.key",
                    secret_key=None, chroma_path=tmp_path / "data" / "chroma",   # an isolated, temporary store
                    judge_api_key=key, attacker_api_key=key,
                    adaptive_max_turns=TURN_CAP, adaptive_time_limit_s=120)    # the shipped retrieval defaults


def _save_target(api, hs_target) -> int:
    form_id = str(uuid.uuid4())
    settings = {"url": hs_target.url, "method": "POST", "headers": [{"name": "X-API-Key", "value": hs_target.key}],
                "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply"}
    tested = api.post("/api/connection-tests", json={"form_id": form_id, "target_id": None, "display_name": "HS",
                                                     "settings": settings})
    assert tested.json()["ok"], tested.text
    saved = api.post("/api/targets", json={"form_id": form_id, "name": "HS-code target", "settings": settings,
                                           "permission_confirmed": True,
                                           "terms_version": api.get("/api/config").json()["terms"]["version"],
                                           "canaries": [hs_target.canary]})
    assert saved.status_code == 201, saved.text
    return saved.json()["id"]


def _seedless(line: dict) -> bool:
    """A turn-4 query holds the attacker's turn-2 and turn-3 messages only — the seed has left the window."""
    return line["turn"] >= 4 and line["query_messages"] == 2


def test_shipped_controls_hold_on_the_real_model_against_the_hs_code_target(tmp_path, hs_target, library_required,
                                                                            json_log):  # FR-018, SC-010
    settings = _settings(tmp_path)
    with TestClient(create_app(settings)) as api:
        assert api.get("/api/config").json()["experience"]["distance_floor"] == SHIPPED["distance_floor"]
        target_id = _save_target(api, hs_target)

        runs, retrieval_lines, served_text = [], [], []
        while len(runs) < MAX_RUNS:
            if len(runs) >= MIN_RUNS and any(_seedless(line) for line in retrieval_lines):
                break
            run = api.post("/api/runs", json={"target_id": target_id, "family": FAMILY, "mode": "adaptive",
                                              "use_prior_experience": True}).json()
            assert run["verdict"] in ("succeeded", "failed", "unclear"), run
            assert run["use_prior_experience"] is True and run["turns_used"] <= TURN_CAP
            runs.append(run)
            served = api.get(f"/api/runs/{run['id']}/log")
            assert served.status_code == 200, served.text
            served_text.append(served.text)
            lines = served.json()["lines"]
            assert lines and lines[0]["event"] == "run.start" and all(line["run_id"] == run["id"] for line in lines)
            retrieval_lines.extend(line for line in lines if line["event"] == "memory.retrieval")

        # First: the test cannot pass vacuously — some run asked the store on turn 2 or later.
        assert retrieval_lines, f"no run produced a memory.retrieval line: {[r['stopping_condition'] for r in runs]}"

        for line in retrieval_lines:
            assert line["k"] == SHIPPED["k"]
            assert line["distance_floor"] == SHIPPED["distance_floor"]
            assert line["dedupe_threshold"] == SHIPPED["dedupe_threshold"]
            assert line["candidate_count"] == line["dropped_floor"] + line["dropped_duplicate"] + line["pattern_count"]
            assert line["pattern_count"] >= 1 and line["warm"] is True
            assert len(line["distances"]) == line["pattern_count"] == len(line["pattern_ids"])
            assert all(distance <= SHIPPED["distance_floor"] for distance in line["distances"])
            assert line["query_messages"] == (1 if line["turn"] == 2 else 2)

        # The floor is confirmed on a query without the seed: a turn-4 line selected a pattern.
        seedless = [line for line in retrieval_lines if _seedless(line)]
        assert seedless, (f"no run reached a seedless turn-4 query in {len(runs)} runs: "
                          f"{[(r['turns_used'], r['stopping_condition']) for r in runs]}")
        assert any(line["pattern_count"] >= 1 for line in seedless)

        # The shipped threshold's two outcomes on the real model, on the same store the runs used.
        store = api.app.state.experience
        assert store is not None, "the real store was usable for the whole session"
        owasp = FAMILIES[FAMILY]["owasp_category"]
        first = store.write_pattern(run_id=WRITEBACK_RUN_IDS[0], document=DOCUMENT, family=FAMILY,
                                    owasp_category=owasp, dedupe_threshold=SHIPPED["dedupe_threshold"])
        assert first.outcome == "added" and first.hit_count == 1
        assert first.pattern_id.startswith("pattern:run:")   # a fresh uuid, never pattern:run:<run_id> (011 review)
        merged = store.write_pattern(run_id=WRITEBACK_RUN_IDS[1], document=VARIANT, family=FAMILY,
                                     owasp_category=owasp, dedupe_threshold=SHIPPED["dedupe_threshold"])
        assert (merged.outcome, merged.pattern_id, merged.hit_count) == ("merged", first.pattern_id, 2), merged
        assert merged.distance is not None and merged.distance <= SHIPPED["dedupe_threshold"]
        added = store.write_pattern(run_id=WRITEBACK_RUN_IDS[2], document=PARAPHRASE, family=FAMILY,
                                    owasp_category=owasp, dedupe_threshold=SHIPPED["dedupe_threshold"])
        assert added.outcome == "added" and added.hit_count == 1
        assert added.pattern_id.startswith("pattern:run:") and added.pattern_id != first.pattern_id
        assert added.distance is not None and added.distance > SHIPPED["dedupe_threshold"], added

    # The store the runs used records the shipped model's name and the pinned space.
    reopened = ExperienceStore(settings.chroma_path)
    assert reopened.stored_embedding_model == DEFAULT_EMBEDDING_MODEL == "all-MiniLM-L6-v2"
    assert reopened.distance_space == reopened.stored_distance_space == DISTANCE_SPACE == "l2"
    reopened.self_check()   # the same model and space: no mismatch

    # The shipped default delegates to ONNX MiniLM: a silent change of ChromaDB's default model would show here.
    default_vector = [float(v) for v in DefaultEmbeddingFunction()([PROBE])[0]]
    onnx_vector = [float(v) for v in ONNXMiniLM_L6_V2()([PROBE])[0]]
    assert len(default_vector) == len(onnx_vector) > 0
    assert squared_distance(default_vector, onnx_vector) <= 1e-9

    # The target's key: zero times on the stream, in the served lines and in the target's own output.
    assert json_log.text().count(hs_target.key) == 0
    assert all(text.count(hs_target.key) == 0 for text in served_text)
    assert hs_target.log_path.read_text(encoding="utf-8", errors="replace").count(hs_target.key) == 0
