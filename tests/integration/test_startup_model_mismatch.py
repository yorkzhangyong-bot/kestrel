"""A store built by another embedding model, or with an index in another distance space, fails clearly at
start-up: one ERROR `experience.unavailable` line naming the kind, both values and the remedy as its constant
message — never the exception's text — and the store stays disabled for the session, so a run records loudly as
not written back and retrieves nothing; a feature-004 store (version only) starts cleanly and is stamped
(011/FR-010, 011/FR-011, 011/FR-017, 011/SC-006). Temporary stores on the lexical stub; placeholders only."""
import chromadb
import httpx
from fastapi.testclient import TestClient

from kestrel.api.main import create_app
from kestrel.experience.store import (COLLECTION, EMBEDDING_MODEL_KEY, VERSION_KEY, EmbeddingModelMismatch,
                                      ExperienceStore, SpaceMismatch)
from tests.support import REPLY_TEXT, StubAttacker, StubEmbeddingFunction, StubJudge, fixture_library, saved_target

MODEL_MISMATCH_MESSAGE = ("The experience store was built by a different embedding model, so it is disabled for "
                          "this session and runs will record loudly as not written back (Principle V). Rebuild the "
                          "store directory, or run Kestrel with the model that built it.")
SPACE_MISMATCH_MESSAGE = ("The experience store's index uses a different distance space than Kestrel expects, so "
                          "it is disabled for this session and runs will record loudly as not written back "
                          "(Principle V). Rebuild the store directory.")
STAMPED = "Recorded the embedding model name and distance space on the experience store."
REPLY = httpx.MockTransport(lambda request: httpx.Response(200, json={"reply": REPLY_TEXT}))


class OtherModelStore(ExperienceStore):
    """The app's own store, opened under a different embedding model than the one that built it on disk."""

    def __init__(self, path, **kwargs):
        super().__init__(path, embedding_function=StubEmbeddingFunction(), embedding_model="other-model")


class StubStore(ExperienceStore):
    def __init__(self, path, **kwargs):
        super().__init__(path, embedding_function=StubEmbeddingFunction())


def app_with_own_store(settings, monkeypatch, store_class):
    """`create_app` with no injected store: the app builds its own (the patched class) and runs `self_check`."""
    monkeypatch.setattr("kestrel.api.main.ExperienceStore", store_class)
    return create_app(settings, transport=REPLY, library=fixture_library(), judge=StubJudge(),
                      attacker=StubAttacker())


def raw_collection(settings, **kwargs):
    client = chromadb.PersistentClient(path=str(settings.chroma_path))
    return client.get_or_create_collection(COLLECTION, embedding_function=StubEmbeddingFunction(), **kwargs)


def test_a_model_mismatch_is_one_error_line_with_the_remedy_and_disables_the_store(settings, monkeypatch, json_log):
    # 011/FR-010, 011/FR-017, 011/SC-006
    ExperienceStore(settings.chroma_path, embedding_function=StubEmbeddingFunction())   # built by the stub model
    app = app_with_own_store(settings, monkeypatch, OtherModelStore)
    lines = json_log.of("experience.unavailable")
    assert len(lines) == 1
    line = lines[0]
    assert line["level"] == "ERROR" and line["exc_type"] == "EmbeddingModelMismatch"
    assert line["reason_kind"] == "embedding_model_mismatch"
    assert line["stored_model"] == "kestrel-lexical-stub" and line["expected_model"] == "other-model"
    assert line["message"] == MODEL_MISMATCH_MESSAGE and line["stack"]
    assert str(EmbeddingModelMismatch(stored="kestrel-lexical-stub", expected="other-model")) not in json_log.text()
    assert json_log.of("experience.seed_failed") == [] and app.state.experience is None
    with TestClient(app) as api:
        target = saved_target(api.app.state.store)
        run = api.post("/api/runs", json={"target_id": target.id, "family": "system_prompt_leak",
                                          "mode": "adaptive", "use_prior_experience": True}).json()
    assert run["status"] == "finished" and run["memory_written"] is False
    run_lines = [r for r in json_log() if r.get("run_id") == run["id"]]
    writeback = [r for r in run_lines if r["event"] == "memory.writeback"]
    assert len(writeback) == 1 and writeback[0]["written"] is False and writeback[0]["level"] == "ERROR"
    assert not [r for r in run_lines if r["event"] == "memory.retrieval"]
    assert run_lines[-1]["event"] == "run.end" and run_lines[-1]["memory_written"] is False


def test_a_space_mismatch_is_one_error_line_with_its_own_kind_and_remedy(settings, monkeypatch, json_log):
    # 011/FR-010, 011/SC-006
    raw_collection(settings, configuration={"hnsw": {"space": "cosine"}})
    app = app_with_own_store(settings, monkeypatch, StubStore)
    lines = json_log.of("experience.unavailable")
    assert len(lines) == 1
    line = lines[0]
    assert line["level"] == "ERROR" and line["exc_type"] == "SpaceMismatch" and line["reason_kind"] == "space_mismatch"
    assert line["stored_space"] == "cosine" and line["expected_space"] == "l2"
    assert line["message"] == SPACE_MISMATCH_MESSAGE
    assert "stored_model" not in line and "expected_model" not in line
    assert str(SpaceMismatch(stored="cosine", expected="l2")) not in json_log.text()
    assert app.state.experience is None and STAMPED not in json_log.text()


def test_a_feature_004_store_starts_cleanly_and_is_stamped(settings, monkeypatch, json_log):  # 011/FR-011, SC-006
    raw_collection(settings, metadata={VERSION_KEY: "1"})   # a version, no model name, no space key
    app = app_with_own_store(settings, monkeypatch, StubStore)
    assert json_log.of("experience.unavailable") == [] and app.state.experience is not None
    assert [r["message"] for r in json_log.of("message")].count(STAMPED) == 1
    metadata = app.state.experience._collection.metadata
    assert metadata[EMBEDDING_MODEL_KEY] == "kestrel-lexical-stub" and metadata["kestrel_distance_space"] == "l2"
    assert app.state.experience.count("pattern") == len(fixture_library().prompts)   # seeded as usual
