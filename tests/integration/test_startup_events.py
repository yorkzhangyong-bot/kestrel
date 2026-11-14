"""Start-up and maintenance lines are named events with their values as fields: a failure names its class and its
kind, never its message text, which may quote a path, a host or a provider error (010/FR-006, 010/FR-009)."""
import pytest
from cryptography.fernet import Fernet

from kestrel.api.main import create_app
from kestrel.attacks.library import LibraryError
from kestrel.experience.store import ExperienceStore
from kestrel.secrets import Vault
from kestrel.store import TargetStore
from tests.support import StubEmbeddingFunction, fixture_library, saved_target

FEATURE = "010"


def test_a_library_that_cannot_load_is_named_without_its_text(make_client, monkeypatch, json_log):  # FR-009
    def broken():
        raise LibraryError("could not read /private/library-path/library.json")
    monkeypatch.setattr("kestrel.api.main.load_library", broken)
    make_client()
    line = json_log.of("library.unavailable")[0]
    assert line["exc_type"] == "LibraryError" and line["level"] == "WARNING" and line["stack"]
    assert "/private/library-path" not in json_log.text()


@pytest.mark.parametrize("text, kind", [
    ("Embedding function kestrel_stub not found at /private/chroma", "embedding_function_mismatch"),
    ("could not resolve host while downloading the onnx model", "model_download"),
    ("something else entirely at /private/chroma", "other"),
])
def test_an_unusable_experience_store_is_named_by_kind(settings, monkeypatch, json_log, text, kind):  # FR-009
    class Broken:
        def __init__(self, path, **kwargs):
            raise RuntimeError(text)
    monkeypatch.setattr("kestrel.api.main.ExperienceStore", Broken)
    create_app(settings, library=fixture_library())
    line = json_log.of("experience.unavailable")[0]
    assert (line["exc_type"], line["reason_kind"], line["level"]) == ("RuntimeError", kind, "ERROR")
    assert text not in json_log.text() and "/private" not in json_log.text()


def test_a_failed_self_check_is_named_by_its_cause(settings, monkeypatch, json_log):  # FR-009
    class FailsCheck(ExperienceStore):
        def __init__(self, path, **kwargs):
            super().__init__(path, embedding_function=StubEmbeddingFunction())

        def self_check(self):
            try:
                raise ValueError("Embedding function default not found")
            except ValueError as error:
                from kestrel.experience.store import ExperienceStoreError, describe_store_error
                raise ExperienceStoreError(describe_store_error(error)) from error
    monkeypatch.setattr("kestrel.api.main.ExperienceStore", FailsCheck)
    create_app(settings, library=fixture_library())
    line = json_log.of("experience.unavailable")[0]
    assert (line["exc_type"], line["reason_kind"]) == ("ValueError", "embedding_function_mismatch")


def test_a_seeding_failure_is_named_without_its_text(settings, json_log):  # FR-009
    class Unseedable:
        def seed_patterns(self, library):
            raise RuntimeError("could not resolve model.example.test while downloading")
    create_app(settings, library=fixture_library(), experience=Unseedable())
    line = json_log.of("experience.seed_failed")[0]
    assert (line["exc_type"], line["reason_kind"], line["level"]) == ("RuntimeError", "model_download", "ERROR")
    assert "model.example.test" not in json_log.text()


def test_start_up_counts_are_message_events_with_their_values_as_fields(settings, json_log):  # FR-006
    store = TargetStore(settings.db_path, Vault(Fernet.generate_key()))
    target = saved_target(store)
    store.claim_run(target.id, prompt_id="spl-001", prompt_title="t", prompt_text="<seed>",
                    family="system_prompt_leak", owasp_category="LLM07: System Prompt Leakage",
                    attacker_source="library:1.0.0")   # left in progress by a "previous process"
    library = fixture_library()
    create_app(settings, library=library,
               experience=ExperienceStore(settings.chroma_path, embedding_function=StubEmbeddingFunction()))
    counts = {r["message"]: r["count"] for r in json_log.of("message") if "count" in r}
    assert 1 in counts.values() and len(library.prompts) in counts.values()
    assert all("%" not in message and not any(ch.isdigit() for ch in message) for message in counts)


def test_a_memory_that_cannot_be_deleted_is_named_with_the_target_id(make_client, settings, json_log):  # FR-009
    class Undeletable(ExperienceStore):
        def delete_target_memory(self, target_id):
            raise RuntimeError("chroma said no at /private/chroma")

    api = make_client(experience=Undeletable(settings.chroma_path, embedding_function=StubEmbeddingFunction()))
    target = saved_target(api.app.state.store)
    assert api.delete(f"/api/targets/{target.id}").status_code == 204   # the target is gone; the memory failure is loud
    line = json_log.of("experience.delete_failed")[0]
    assert (line["exc_type"], line["target_id"], line["level"]) == ("RuntimeError", target.id, "ERROR")
    assert "/private/chroma" not in json_log.text()
