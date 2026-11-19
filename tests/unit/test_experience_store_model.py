"""The store knows which embedding model and distance space built it (feature 011, contracts/experience-store.md):
the collection is created with an explicit `l2` index and records the model name and the space beside the store
version; the same model reopens silently; a different model name, or an index in another space, fails `self_check`
with a named mismatch that writes nothing; a feature-004 store (version only) opens cleanly and is stamped once,
and a stamp never overwrites a recorded name (FR-009, FR-010, FR-011, SC-006). Temporary stores on the lexical stub;
two of them open the shipped default beside it (the constructor embeds nothing, so that stays offline)."""
import chromadb
import pytest

from kestrel.experience.store import (COLLECTION, DISTANCE_SPACE_KEY, EMBEDDING_MODEL_KEY, VERSION_KEY,
                                      EmbeddingModelMismatch, ExperienceStore, ExperienceStoreError, SpaceMismatch,
                                      describe_store_error, embedding_model_name, store_error_kind)
from tests.support import StubEmbeddingFunction

FEATURE = "011"

STUB_MODEL = "kestrel-lexical-stub"
STAMPED = "Recorded the embedding model name and distance space on the experience store."


def open_store(path, **kwargs) -> ExperienceStore:
    return ExperienceStore(path, embedding_function=StubEmbeddingFunction(), **kwargs)


def raw_collection(path, **kwargs):
    """A collection created directly with ChromaDB — a store from another version or tool — under the stub."""
    client = chromadb.PersistentClient(path=str(path))
    return client.get_or_create_collection(COLLECTION, embedding_function=StubEmbeddingFunction(), **kwargs)


def messages(json_log) -> list[str]:
    return [record["message"] for record in json_log.of("message")]


def test_a_fresh_store_records_the_model_name_and_an_l2_space(tmp_path):  # FR-009, SC-006
    store = open_store(tmp_path / "chroma")
    metadata = store._collection.metadata
    assert metadata[VERSION_KEY] == "1" and metadata[EMBEDDING_MODEL_KEY] == STUB_MODEL
    assert metadata[DISTANCE_SPACE_KEY] == "l2"
    assert store._collection.configuration_json["hnsw"]["space"] == "l2"
    assert store.embedding_model == store.stored_embedding_model == STUB_MODEL and store.distance_space == "l2"


def test_the_same_model_reopens_silently_and_passes_self_check(tmp_path, json_log):  # FR-010, SC-006
    open_store(tmp_path / "chroma")
    reopened = open_store(tmp_path / "chroma")
    reopened.self_check()
    assert messages(json_log) == [] and not [r for r in json_log() if r["level"] in ("WARNING", "ERROR")]


def test_a_different_model_name_fails_self_check_without_writing(tmp_path):  # FR-010, SC-006
    open_store(tmp_path / "chroma")                                        # built under the stub's model name
    store = open_store(tmp_path / "chroma", embedding_model="other-model")   # the test seam for "another model"
    with pytest.raises(EmbeddingModelMismatch) as caught:
        store.self_check()
    error = caught.value
    assert isinstance(error, ExperienceStoreError)
    assert (error.stored, error.expected) == (STUB_MODEL, "other-model")
    assert STUB_MODEL in str(error) and "other-model" in str(error) and "Rebuild the store directory" in str(error)
    assert store.count() == 0 and store._collection.get(ids=["kestrel:self-check"])["ids"] == []   # no probe
    assert store._collection.metadata[EMBEDDING_MODEL_KEY] == STUB_MODEL   # the recorded name is kept


def test_an_index_in_another_space_fails_self_check_and_is_never_stamped(tmp_path, json_log):  # FR-010, FR-011
    raw_collection(tmp_path / "chroma", configuration={"hnsw": {"space": "cosine"}})
    store = open_store(tmp_path / "chroma")
    assert store.distance_space == "cosine"
    with pytest.raises(SpaceMismatch) as caught:
        store.self_check()
    assert isinstance(caught.value, ExperienceStoreError)
    assert (caught.value.stored, caught.value.expected) == ("cosine", "l2")
    assert "cosine" in str(caught.value) and "l2" in str(caught.value) and "Rebuild" in str(caught.value)
    assert not (store._collection.metadata or {}).get(DISTANCE_SPACE_KEY)   # never stamped …
    assert messages(json_log) == []                                           # … and no stamp line


def test_store_error_kind_and_describe_name_both_values_of_a_mismatch():  # FR-010
    model = EmbeddingModelMismatch(stored="a-model", expected="b-model")
    space = SpaceMismatch(stored="cosine", expected="l2")
    assert store_error_kind(model) == "embedding_model_mismatch" and store_error_kind(space) == "space_mismatch"
    assert "a-model" in describe_store_error(model) and "b-model" in describe_store_error(model)
    assert "cosine" in describe_store_error(space) and "l2" in describe_store_error(space)
    assert store_error_kind(ValueError("Embedding function kestrel_stub not found")) == "embedding_function_mismatch"


def test_a_feature_004_store_opens_cleanly_and_is_stamped_once(tmp_path, json_log):  # FR-011, SC-006
    raw_collection(tmp_path / "chroma", metadata={VERSION_KEY: "1"})   # no configuration: the stub's l2 default
    store = open_store(tmp_path / "chroma")
    store.self_check()
    assert store._collection.metadata == {VERSION_KEY: "1", EMBEDDING_MODEL_KEY: STUB_MODEL,
                                          DISTANCE_SPACE_KEY: "l2"}
    assert store.stored_embedding_model == STUB_MODEL and store.distance_space == "l2"
    assert messages(json_log) == [STAMPED]
    open_store(tmp_path / "chroma").self_check()
    assert messages(json_log) == [STAMPED]   # the next open compares against the stamp and says nothing


def test_a_stamp_never_overwrites_a_recorded_model_name(tmp_path, json_log):  # FR-011
    raw_collection(tmp_path / "chroma", metadata={VERSION_KEY: "1", EMBEDDING_MODEL_KEY: "other-model"})
    store = open_store(tmp_path / "chroma")
    metadata = store._collection.metadata
    assert metadata[DISTANCE_SPACE_KEY] == "l2" and metadata[EMBEDDING_MODEL_KEY] == "other-model"
    assert messages(json_log) == [STAMPED]
    with pytest.raises(EmbeddingModelMismatch) as caught:
        store.self_check()
    assert (caught.value.stored, caught.value.expected) == ("other-model", STUB_MODEL)


def persisted_function(store: ExperienceStore) -> str:
    """The embedding function name ChromaDB persisted in the collection's configuration."""
    return store._collection.configuration_json["embedding_function"]["name"]


def test_a_default_store_after_a_stub_store_keeps_its_own_embedding_function(tmp_path):  # FR-009, SC-006
    """ChromaDB writes the embedding function of a call into the configuration dict it is given: a configuration
    shared between calls pinned the first store's function onto every later one — a default store built on the
    stub while recording the shipped model's name, the silent mismatch the stamp exists to prevent."""
    stub = open_store(tmp_path / "stub-first")
    default = ExperienceStore(tmp_path / "default-after")   # the shipped default; no ValueError
    assert persisted_function(stub) == "kestrel_stub" and stub.embedding_model == STUB_MODEL
    assert persisted_function(default) == "default" and default.embedding_model == "all-MiniLM-L6-v2"
    assert default._collection.metadata[EMBEDDING_MODEL_KEY] == "all-MiniLM-L6-v2"


def test_a_stub_store_after_a_default_store_keeps_its_own_embedding_function(tmp_path):  # FR-009, SC-006
    """The reverse order: with a shared configuration the stub store failed in the constructor ("Multiple
    embedding functions provided"); each store now carries its own."""
    default = ExperienceStore(tmp_path / "default-first")
    stub = open_store(tmp_path / "stub-after")                 # no ValueError
    assert persisted_function(default) == "default" and default.embedding_model == "all-MiniLM-L6-v2"
    assert persisted_function(stub) == "kestrel_stub" and stub.embedding_model == STUB_MODEL
    assert stub._collection.metadata[EMBEDDING_MODEL_KEY] == STUB_MODEL


def test_the_model_name_is_derived_from_the_embedding_function_in_use():  # FR-009
    from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2

    assert embedding_model_name(None) == ONNXMiniLM_L6_V2.MODEL_NAME == "all-MiniLM-L6-v2"   # the shipped default
    assert embedding_model_name(StubEmbeddingFunction()) == STUB_MODEL

    class Nameless:
        @staticmethod
        def name() -> str:
            return "nameless_ef"

    assert embedding_model_name(Nameless()) == "nameless_ef"   # no MODEL_NAME: the registered name
