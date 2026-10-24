"""The ExperienceStore opens one versioned collection with an injected offline embedder (FR-001/2/3, R1/R2/R5)."""
import logging

import pytest

from kestrel.experience.store import ExperienceStore
from tests.support import StubEmbeddingFunction


def open_store(path, *, store_version="1") -> ExperienceStore:
    return ExperienceStore(path, embedding_function=StubEmbeddingFunction(), store_version=store_version)


def test_a_fresh_store_is_empty_and_records_its_version(tmp_path):
    store = open_store(tmp_path / "chroma")
    assert store.count() == 0
    assert store.version == "1"


def test_the_store_persists_and_reopens(tmp_path):
    path = tmp_path / "chroma"
    open_store(path)
    reopened = open_store(path)
    assert reopened.version == "1"  # read back from the collection metadata


def test_a_version_mismatch_is_logged(tmp_path, caplog):
    path = tmp_path / "chroma"
    open_store(path, store_version="1")
    with caplog.at_level(logging.WARNING, logger="kestrel"):
        open_store(path, store_version="2")   # code now expects "2" but the store was written at "1"
    assert "version" in caplog.text.lower()
