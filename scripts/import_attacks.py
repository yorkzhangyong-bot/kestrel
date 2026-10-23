"""Import attack prompts into the library from published datasets, by item ID (tasks.md T013a, research R8).

This is a data pipeline, not a prompt author. It never contains or generates attack text: `sources.json` lists
only dataset URLs, licences, the item IDs to take, and the target family. The script downloads each dataset,
pulls the named items, copies their text into the library schema, and refuses any source whose licence does not
permit redistribution. Filling `sources.json` and running this is T013b, done by the user.

Run it from the repo root:

    uv run python scripts/import_attacks.py

It reads src/kestrel/attacks/data/sources.json and writes library.json and SOURCES.md beside it.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Callable, Iterable

# Make `kestrel` importable when run as a plain script (python scripts/import_attacks.py).
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from kestrel.attacks.library import FAMILIES, build_library  # noqa: E402

DATA_DIR = REPO_ROOT / "src" / "kestrel" / "attacks" / "data"
SOURCES_PATH = DATA_DIR / "sources.json"
LIBRARY_PATH = DATA_DIR / "library.json"
SOURCES_MD_PATH = DATA_DIR / "SOURCES.md"

# Library ids are '<prefix>-NNN' (see library.ID_PATTERN); generated per family, not taken from the dataset.
FAMILY_PREFIX = {"direct_injection": "dir", "system_prompt_leak": "spl",
                 "tool_exfiltration": "tex", "indirect_injection": "iin"}

# Licences that permit redistributing the prompt text. Anything else (NC, ND, proprietary, unknown) is refused.
REDISTRIBUTABLE_LICENCES = {
    "mit", "apache-2.0", "apache 2.0", "bsd-2-clause", "bsd-3-clause", "isc", "unlicense", "cc0-1.0", "cc0",
    "cc-by-4.0", "cc-by-3.0", "cc-by-sa-4.0", "cc-by-sa-3.0",
}


class ImportError_(Exception):
    """A source could not be imported. Named with a trailing underscore to avoid shadowing the builtin."""


class LicenceRefused(ImportError_):
    """A source's licence does not permit redistributing its text, so it is refused (R8)."""


Fetch = Callable[[str], str]


def _http_fetch(url: str) -> str:
    import httpx  # imported here so the unit tests, which inject a fetch, need no network

    response = httpx.get(url, timeout=60, follow_redirects=True)
    response.raise_for_status()
    return response.text


def licence_ok(licence: str) -> bool:
    return licence.strip().lower() in REDISTRIBUTABLE_LICENCES


def parse_dataset(raw: str, fmt: str) -> list[dict]:
    """A dataset as a list of records. 'jsonl' is one object per line; 'json' is a list of objects."""
    if fmt == "jsonl":
        return [json.loads(line) for line in io.StringIO(raw) if line.strip()]
    if fmt == "json":
        data = json.loads(raw)
        if isinstance(data, list):
            return data
        raise ImportError_("A 'json' dataset must be a list of objects.")
    raise ImportError_(f"Unknown dataset format {fmt!r}; use 'jsonl' or 'json'.")


def _index(records: Iterable[dict], id_field: str) -> dict[str, dict]:
    index: dict[str, dict] = {}
    for record in records:
        if id_field in record:
            index[str(record[id_field])] = record
    return index


class _Counter:
    """Hands out library ids per family: dir-001, dir-002, ..."""

    def __init__(self) -> None:
        self.seen: dict[str, int] = {}

    def next_id(self, family: str) -> str:
        self.seen[family] = self.seen.get(family, 0) + 1
        return f"{FAMILY_PREFIX[family]}-{self.seen[family]:03d}"


def _prompts_from_source(source: dict, records: list[dict], counter: _Counter) -> list[dict]:
    family = source["family"]
    if family not in FAMILIES:
        raise ImportError_(f"{source.get('name', '?')}: {family!r} is not an attack family.")
    index = _index(records, source["id_field"])
    text_field = source["text_field"]
    title_field = source.get("title_field")
    prompts = []
    for item_id in source["items"]:
        record = index.get(str(item_id))
        if record is None:
            raise ImportError_(f"{source.get('name', '?')}: item {item_id!r} is not in the dataset.")
        text = record.get(text_field)
        if not isinstance(text, str) or not text.strip():
            raise ImportError_(f"{source.get('name', '?')}: item {item_id!r} has no text in field {text_field!r}.")
        generated_id = counter.next_id(family)
        # A neutral title when the source gives none, so no attack text leaks into the title.
        title = record.get(title_field) if title_field else None
        title = title if isinstance(title, str) and title.strip() else f"{FAMILIES[family]['label']} — {generated_id}"
        prompts.append({
            "id": generated_id, "title": title, "text": text, "family": family,
            "owasp_category": FAMILIES[family]["owasp_category"], "source": source["name"],
            "source_url": source["source_url"], "licence": source["licence"],
        })
    return prompts


def import_library(config: dict, *, fetch: Fetch = _http_fetch) -> dict:
    """Build the library dict from the sources config. Refuses non-redistributable licences (R8).

    Does not enforce the 16-24 / 3-per-family counts; that is the loader's job (T012), checked in T013b.
    """
    counter = _Counter()
    prompts: list[dict] = []
    for source in config.get("sources", []):
        if not licence_ok(source["licence"]):
            raise LicenceRefused(
                f"{source.get('name', '?')}: licence {source['licence']!r} does not permit redistribution.")
        records = parse_dataset(fetch(source["url"]), source.get("format", "jsonl"))
        prompts.extend(_prompts_from_source(source, records, counter))
    return {"version": config.get("version", "1.0.0"), "prompts": prompts}


def build_sources_md(config: dict) -> str:
    """A provenance file listing each source, its licence and the item ids taken (like PROVENANCE.md)."""
    lines = ["# Attack library sources", "",
             "Every prompt in `library.json` was imported by `scripts/import_attacks.py` from a published dataset,",
             "selected by item id. No prompt was written for this repository (research R8).", ""]
    for source in config.get("sources", []):
        lines += [f"## {source['name']}", "",
                  f"- Dataset: {source['url']}", f"- Citation: {source['source_url']}",
                  f"- Licence: {source['licence']}", f"- Family: {source['family']}",
                  f"- Items taken ({len(source['items'])}): {', '.join(str(i) for i in source['items'])}", ""]
    return "\n".join(lines)


def main() -> int:
    if not SOURCES_PATH.exists():
        print(f"No {SOURCES_PATH} yet. Fill it in (T013b) before running this.", file=sys.stderr)
        return 1
    config = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    try:
        library = import_library(config)
    except ImportError_ as error:
        print(f"Import failed: {error}", file=sys.stderr)
        return 1
    try:
        build_library(library)  # the T012 loader's rules, so a bad set is caught before it is written
    except Exception as error:  # noqa: BLE001 - surface the loader's message verbatim
        print(f"The imported library is not valid: {error}", file=sys.stderr)
        return 1
    LIBRARY_PATH.write_text(json.dumps(library, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    SOURCES_MD_PATH.write_text(build_sources_md(config), encoding="utf-8")
    print(f"Wrote {len(library['prompts'])} prompts to {LIBRARY_PATH.name} and {SOURCES_MD_PATH.name}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
