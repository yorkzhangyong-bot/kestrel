"""The attack-import pipeline (tasks.md T013a): selection by id, licence refusal, schema mapping — no network.

The fixture datasets below hold placeholder text, not real attack prompts: these tests check the pipeline, not
any content. The script is loaded from scripts/ by path, since scripts/ is not on the import path.
"""
import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_module():
    import sys

    spec = importlib.util.spec_from_file_location("import_attacks", REPO_ROOT / "scripts" / "import_attacks.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # so dataclasses/typing in the module resolve their own module
    spec.loader.exec_module(module)
    return module


imp = _load_module()

# A tiny fixture dataset: ids and placeholder text only.
DATASET = [
    {"ref": "A1", "prompt": "<fixture prompt one>", "name": "First"},
    {"ref": "A2", "prompt": "<fixture prompt two>", "name": "Second"},
    {"ref": "A3", "prompt": "<fixture prompt three>"},
    {"ref": "A4", "prompt": "   "},  # blank text, to exercise the guard
]


def jsonl(records) -> str:
    return "\n".join(json.dumps(r) for r in records)


def fetch_from(mapping):
    def fetch(url: str) -> str:
        if url not in mapping:
            raise AssertionError(f"unexpected fetch of {url!r}")  # proves only listed sources are fetched
        return mapping[url]
    return fetch


def source(**over) -> dict:
    base = {"name": "Fixture set", "url": "https://data.test/set.jsonl", "source_url": "https://cite.test/set",
            "licence": "MIT", "format": "jsonl", "family": "direct_injection", "id_field": "ref",
            "text_field": "prompt", "title_field": None, "items": ["A1", "A2"]}
    return {**base, **over}


# --- licences (R8) ---

@pytest.mark.parametrize("licence", ["MIT", "Apache-2.0", "apache 2.0", "CC-BY-4.0", "CC-BY-SA-4.0", "CC0-1.0",
                                     "BSD-3-Clause", "ISC"])
def test_redistributable_licences_are_accepted(licence):
    assert imp.licence_ok(licence)


@pytest.mark.parametrize("licence", ["CC-BY-NC-4.0", "CC-BY-ND-4.0", "proprietary", "research-only", "", "unknown"])
def test_non_redistributable_licences_are_refused(licence):
    assert not imp.licence_ok(licence)


def test_a_source_with_a_bad_licence_is_refused_and_nothing_is_imported():
    config = {"version": "1.0.0", "sources": [source(licence="CC-BY-NC-4.0")]}
    with pytest.raises(imp.LicenceRefused):
        imp.import_library(config, fetch=fetch_from({source()["url"]: jsonl(DATASET)}))


# --- parsing ---

def test_parse_jsonl_and_json():
    assert len(imp.parse_dataset(jsonl(DATASET), "jsonl")) == 4
    assert len(imp.parse_dataset(json.dumps(DATASET), "json")) == 4


def test_an_unknown_format_is_refused():
    with pytest.raises(imp.ImportError_):
        imp.parse_dataset("{}", "csv")


# --- selection by id only ---

def test_only_the_named_items_are_taken_in_order():
    config = {"version": "1.0.0", "sources": [source(items=["A3", "A1"])]}
    library = imp.import_library(config, fetch=fetch_from({source()["url"]: jsonl(DATASET)}))
    texts = [p["text"] for p in library["prompts"]]
    assert texts == ["<fixture prompt three>", "<fixture prompt one>"]  # the order listed, not the dataset order


def test_a_missing_item_id_is_an_error():
    config = {"version": "1.0.0", "sources": [source(items=["A1", "NOPE"])]}
    with pytest.raises(imp.ImportError_, match="NOPE"):
        imp.import_library(config, fetch=fetch_from({source()["url"]: jsonl(DATASET)}))


def test_an_item_with_blank_text_is_an_error():
    config = {"version": "1.0.0", "sources": [source(items=["A4"])]}
    with pytest.raises(imp.ImportError_, match="no text"):
        imp.import_library(config, fetch=fetch_from({source()["url"]: jsonl(DATASET)}))


# --- schema mapping ---

def test_items_map_to_the_library_schema():
    config = {"version": "2.1.0", "sources": [source(items=["A1", "A2"])]}
    library = imp.import_library(config, fetch=fetch_from({source()["url"]: jsonl(DATASET)}))
    assert library["version"] == "2.1.0"
    first = library["prompts"][0]
    assert first["id"] == "dir-001" and first["family"] == "direct_injection"
    assert first["owasp_category"] == "LLM01: Prompt Injection"  # derived from the family, not the dataset
    assert first["source"] == "Fixture set" and first["source_url"] == "https://cite.test/set"
    assert first["licence"] == "MIT" and first["text"] == "<fixture prompt one>"


def test_generated_ids_are_sequential_per_family():
    config = {"version": "1.0.0", "sources": [
        source(name="A", url="https://data.test/a.jsonl", family="direct_injection", items=["A1", "A2"]),
        source(name="B", url="https://data.test/b.jsonl", family="system_prompt_leak", items=["A1", "A3"]),
    ]}
    fetch = fetch_from({"https://data.test/a.jsonl": jsonl(DATASET), "https://data.test/b.jsonl": jsonl(DATASET)})
    ids = [p["id"] for p in imp.import_library(config, fetch=fetch)["prompts"]]
    assert ids == ["dir-001", "dir-002", "spl-001", "spl-002"]


def test_a_title_field_is_used_when_present():
    config = {"version": "1.0.0", "sources": [source(title_field="name", items=["A1"])]}
    library = imp.import_library(config, fetch=fetch_from({source()["url"]: jsonl(DATASET)}))
    assert library["prompts"][0]["title"] == "First"


def test_a_neutral_title_is_generated_when_absent():
    """No title in the source means a title from family + id, so no attack text ends up in the title."""
    config = {"version": "1.0.0", "sources": [source(items=["A3"])]}  # A3 has no name field
    library = imp.import_library(config, fetch=fetch_from({source()["url"]: jsonl(DATASET)}))
    title = library["prompts"][0]["title"]
    assert title == "Direct prompt injection — dir-001"
    assert "<fixture" not in title


def test_an_unknown_family_is_refused():
    config = {"version": "1.0.0", "sources": [source(family="social_engineering")]}
    with pytest.raises(imp.ImportError_, match="attack family"):
        imp.import_library(config, fetch=fetch_from({source()["url"]: jsonl(DATASET)}))


# --- provenance file ---

def test_sources_md_lists_provenance_without_prompt_text():
    config = {"version": "1.0.0", "sources": [source(items=["A1", "A2"])]}
    md = imp.build_sources_md(config)
    assert "Fixture set" in md and "MIT" in md and "https://cite.test/set" in md
    assert "A1" in md and "A2" in md            # the item ids are recorded for traceability
    assert "<fixture prompt" not in md          # but never the prompt text


# --- end to end: the output loads under the T012 loader ---

def test_a_full_import_passes_the_library_loader():
    """A 16-item import (4 per family) must satisfy the loader's rules, so T013b's output is loadable."""
    big = [{"ref": f"{fam}{n}", "prompt": f"<fixture {fam} {n}>"} for fam in "abcd" for n in range(1, 5)]
    fam_for = {"a": "direct_injection", "b": "system_prompt_leak", "c": "tool_exfiltration", "d": "indirect_injection"}
    sources = [source(name=f"Set {letter}", url=f"https://data.test/{letter}.jsonl", family=fam_for[letter],
                      items=[f"{letter}{n}" for n in range(1, 5)]) for letter in "abcd"]
    fetch = fetch_from({f"https://data.test/{letter}.jsonl": jsonl(big) for letter in "abcd"})
    library = imp.import_library({"version": "1.0.0", "sources": sources}, fetch=fetch)
    assert len(library["prompts"]) == 16

    from kestrel.attacks.library import build_library  # the T012 loader's validation
    loaded = build_library(library)
    assert len(loaded.prompts) == 16
    assert {p.family for p in loaded.prompts} == set(fam_for.values())
