"""Versioned prompt registry (feature 009).

Every prompt Kestrel sends to a model — the attacker prompt per family, the judge prompt and the recommender
(fix-advice) prompt — is a file `src/kestrel/prompts/<file id>.v<N>.md`: a two-line YAML front-matter (`id`,
`version`) followed by the prompt text. The files *are* the registry. The active version of a prompt is its highest
`N`; older files stay in the folder as the non-active versions an A/B arm can pin (US4). No prompt text lives in
Python. The file id is the prompt id with `:` replaced by `_` (a colon is not a legal file-name character on
Windows), so `attacker:judge_x` is `attacker_judge_x.v1.md`; the front-matter `id` is authoritative.

A committed lock (`prompt_versions.lock.json`, `{id: {version: sha256}}`) pins the fingerprint of every
`(id, version)`. `verify_lock()` reports a prompt when a file's text no longer matches its pinned fingerprint, when a
version file has no lock entry, or when a lock entry has no file — so a prompt cannot change without a version bump
(FR-005, FR-006). `scripts/bump_prompt.py` copies the active file to `v<N+1>` and records the new fingerprint.

No new dependency: the front-matter is the `key: value` subset of YAML, read with the standard library; `hashlib`
and `re` are standard library too. The lock holds only ids, versions and fingerprints — never target secrets or
attack-library fixtures (FR-011, FR-012). The deterministic memory summariser has no model prompt and is not
registered (three prompt kinds, see the spec Assumptions footnote).
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
LOCK_PATH = Path(__file__).resolve().parent / "prompt_versions.lock.json"

JUDGE_ID = "judge"
RECOMMENDER_ID = "recommender"
ATTACKER_PREFIX = "attacker:"

_VERSION_RE = re.compile(r"^[1-9]\d*$")
_FILE_RE = re.compile(r"^(?P<stem>[A-Za-z0-9_.-]+)\.v(?P<version>[1-9]\d*)\.md$")
_FRONT_MATTER_KEYS = ("id", "version")
_FENCE = "---"


class PromptNotRegistered(LookupError):
    """A prompt id or version the registry does not know; a run or arm naming it is refused (FR-009)."""


class PromptFileError(ValueError):
    """A prompt file whose name or front-matter is malformed. Lookups raise it (loud); `verify_lock()` reports it."""


@dataclass(frozen=True)
class PromptEntry:
    """One registered prompt at its active version (FR-001). `text` is the authored template; `fingerprint` is
    sha256 of that text. Never carries a secret or a runtime-filled value."""

    id: str
    version: str
    text: str
    fingerprint: str


@dataclass(frozen=True)
class PromptFile:
    """One parsed prompt file: the id and version its front-matter declares, and the text below the front-matter."""

    id: str
    version: str
    text: str
    path: Path


def attacker_id(family: str) -> str:
    return f"{ATTACKER_PREFIX}{family}"


def is_valid_version(version: str) -> bool:
    """A version is a positive integer written in decimal: `1`, `2`, … (`v<N>` in the file name)."""
    return bool(_VERSION_RE.match(version))


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_stem(prompt_id: str) -> str:
    """The file-name form of a prompt id (`:` → `_`)."""
    return prompt_id.replace(":", "_")


def prompt_path(prompt_id: str, version: str, directory: Path | None = None) -> Path:
    return (directory or PROMPTS_DIR) / f"{file_stem(prompt_id)}.v{version}.md"


def format_prompt_file(prompt_id: str, version: str, text: str) -> str:
    """The on-disk form of a prompt: the two-line front-matter, then the text, ending with one newline."""
    return f"{_FENCE}\nid: {prompt_id}\nversion: {version}\n{_FENCE}\n{text.strip(chr(10))}\n"


def parse_prompt_file(path: Path) -> PromptFile:
    """Read one `<file id>.v<N>.md`: the front-matter must name exactly `id` and `version`, and they must agree with
    the file name. The text is everything below the front-matter, minus leading and trailing newlines (so a
    checkout's line-ending or trailing-newline convention cannot move a fingerprint)."""
    match = _FILE_RE.match(path.name)
    if match is None:
        raise PromptFileError(f"{path.name}: a prompt file is named '<id>.v<N>.md'")
    lines = path.read_text(encoding="utf-8").split("\n")
    if not lines or lines[0].strip() != _FENCE:
        raise PromptFileError(f"{path.name}: the file must start with a '---' front-matter block")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == _FENCE), None)
    if end is None:
        raise PromptFileError(f"{path.name}: the front-matter is not closed with '---'")
    meta: dict[str, str] = {}
    for line in lines[1:end]:
        key, sep, value = line.partition(":")
        if not sep or key.strip() not in _FRONT_MATTER_KEYS:
            raise PromptFileError(f"{path.name}: the front-matter allows only 'id' and 'version', not {line.strip()!r}")
        meta[key.strip()] = value.strip()
    missing = [key for key in _FRONT_MATTER_KEYS if key not in meta]
    if missing:
        raise PromptFileError(f"{path.name}: the front-matter is missing {', '.join(missing)}")
    prompt_id, version = meta["id"], meta["version"]
    if file_stem(prompt_id) != match["stem"] or version != match["version"]:
        raise PromptFileError(f"{path.name}: the front-matter names {prompt_id}@{version}, which does not match "
                              f"the file name")
    text = "\n".join(lines[end + 1:]).strip("\n")
    if not text:
        raise PromptFileError(f"{path.name}: the prompt text is empty")
    return PromptFile(id=prompt_id, version=version, text=text, path=path)


@lru_cache(maxsize=64)
def _parse_cached(path: Path, mtime_ns: int, size: int) -> PromptFile:
    """Parsed once per (path, modification time, size): a file that changes on disk is re-read, an unchanged one is
    served from memory (the attacker and judge load their prompt on every call)."""
    return parse_prompt_file(path)


def clear_cache() -> None:
    _parse_cached.cache_clear()


def _scan_all(directory: Path) -> tuple[dict[str, dict[str, PromptFile]], dict[str, str]]:
    """Every `*.md` file in the folder: `{id: {version: PromptFile}}` for the well-formed ones, and
    `{file name: problem}` for the malformed ones."""
    files: dict[str, dict[str, PromptFile]] = {}
    problems: dict[str, str] = {}
    for path in sorted(directory.glob("*.md")) if directory.is_dir() else []:
        try:
            stat = path.stat()
            parsed = _parse_cached(path, stat.st_mtime_ns, stat.st_size)
        except PromptFileError as error:
            problems[path.name] = str(error)
            continue
        files.setdefault(parsed.id, {})[parsed.version] = parsed
    return files, problems


def prompt_files(directory: Path | None = None) -> dict[str, dict[str, PromptFile]]:
    """Every well-formed prompt file, `{id: {version: PromptFile}}`; a malformed file raises PromptFileError."""
    files, problems = _scan_all(directory or PROMPTS_DIR)
    if problems:
        raise PromptFileError("; ".join(problems.values()))
    return files


def _versions(prompt_id: str) -> dict[str, PromptFile]:
    versions = prompt_files().get(prompt_id)
    if not versions:
        raise PromptNotRegistered(prompt_id)
    return versions


def _highest(versions: dict[str, PromptFile]) -> str:
    return max(versions, key=int)


def active_version(prompt_id: str) -> str:
    """The highest version on disk for this id (FR-001); older files are the non-active versions."""
    return _highest(_versions(prompt_id))


def has(prompt_id: str, version: str) -> bool:
    """Whether a file registers this exact `(id, version)` — the FR-009 authority for runs and arms."""
    return version in prompt_files().get(prompt_id, {})


def text_for(prompt_id: str, version: str) -> str:
    """The authored template text of a specific registered version (an A/B arm pins one, US4)."""
    file = prompt_files().get(prompt_id, {}).get(version)
    if file is None:
        raise PromptNotRegistered(f"{prompt_id}@{version}")
    return file.text


def load_prompt(prompt_id: str) -> tuple[str, str]:
    """The active text of a prompt and its reference, e.g. `load_prompt("judge") == (text, "judge@2")`."""
    versions = _versions(prompt_id)
    version = _highest(versions)
    return versions[version].text, f"{prompt_id}@{version}"


def active_ref(prompt_id: str) -> str | None:
    """The reference (`id@N`) of the active version, or None when the id has no prompt file."""
    try:
        return load_prompt(prompt_id)[1]
    except PromptNotRegistered:
        return None


def split_ref(ref: str | None) -> tuple[str | None, str | None]:
    """A prompt reference `id@N` as the provenance columns `(id, N)` (feature 010, FR-007); (None, None) for none."""
    if not ref or "@" not in ref:
        return None, None
    prompt_id, _, version = ref.rpartition("@")
    return (prompt_id, version) if prompt_id and version else (None, None)


def registry() -> list[PromptEntry]:
    """The active entry of every registered prompt, sorted by id (FR-001)."""
    out: list[PromptEntry] = []
    for prompt_id, versions in sorted(prompt_files().items()):
        file = versions[_highest(versions)]
        out.append(PromptEntry(id=prompt_id, version=file.version, text=file.text, fingerprint=fingerprint(file.text)))
    return out


def families() -> tuple[str, ...]:
    """The attack families that have an attacker prompt, sorted — the adaptive attacker can drive exactly these."""
    return tuple(sorted(pid[len(ATTACKER_PREFIX):] for pid in prompt_files() if pid.startswith(ATTACKER_PREFIX)))


def read_lock(path: Path | None = None) -> dict[str, dict[str, str]]:
    """`{id: {version: fingerprint}}` — committed, append-only (FR-005)."""
    return json.loads((path or LOCK_PATH).read_text(encoding="utf-8"))


def write_lock(lock: dict[str, dict[str, str]], path: Path | None = None) -> None:
    """Write the lock sorted and LF-terminated, so a bump is a one-line, reviewable diff."""
    content = json.dumps(lock, indent=2, sort_keys=True) + "\n"
    with open(path or LOCK_PATH, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)


def verify_lock() -> list[str]:
    """The prompts that fail the guard (FR-005, FR-006); empty = clean. A prompt is reported when any of its files
    has a text whose fingerprint is not the one pinned for that version, when a version file has no lock entry,
    or when a lock entry has no file. A malformed file is reported by its file name. The test suite asserts this is
    empty, so a prompt cannot change — or appear — without the lock recording it."""
    lock = read_lock()
    files, problems = _scan_all(PROMPTS_DIR)
    drifted: set[str] = set(problems)
    for prompt_id, versions in files.items():
        pinned = lock.get(prompt_id, {})
        for version, file in versions.items():
            if pinned.get(version) != fingerprint(file.text):
                drifted.add(prompt_id)
    for prompt_id, pinned in lock.items():
        for version in pinned:
            if not is_valid_version(version) or version not in files.get(prompt_id, {}):
                drifted.add(prompt_id)
    return sorted(drifted)
