# Contract: prompt registry + guard (internal)

Module `src/kestrel/prompt_registry.py`, the prompt files `src/kestrel/prompts/<id>.v<N>.md`, the committed lock
`src/kestrel/prompt_versions.lock.json`, and the maintainer script `scripts/bump_prompt.py`. The files are the
authority for valid `(id, version)` pairs and active versions; the lock is the drift baseline
(FR-001/002/005/006/009). *Amended by the PR #19 review (research D12): file-backed, integer versions.*

## The prompt files

```
---
id: judge
version: 2
---
<the prompt text>
```

- Name: `<id with ':'→'_'>.v<N>.md` (`attacker_direct_injection.v1.md`, `judge.v2.md`); a colon is not a legal
  Windows file-name character, so the front-matter `id` is authoritative and must agree with the file name.
- Front-matter: exactly `id` and `version` (the `key: value` subset of YAML, read with the standard library).
- `text`: everything below the front-matter minus leading/trailing newlines — a checkout's line-ending or
  trailing-newline convention cannot move a fingerprint.
- The **active** version of an id is its highest `N`; older files are the non-active versions an A/B arm can pin.
- A malformed file is loud: lookups raise `PromptFileError`; `verify_lock()` names the file.

## Types / functions

```python
@dataclass(frozen=True)
class PromptEntry:
    id: str          # "attacker:<family>" | "judge" | "recommender"
    version: str     # active version: a positive integer, "1", "2", …
    text: str        # authored template text (the file body)
    fingerprint: str # sha256(text) hex

def load_prompt(id: str) -> tuple[str, str]: ...   # (text, "judge@2") for the active version; PromptNotRegistered
def registry() -> list[PromptEntry]: ...           # active entries, sorted by id
def active_version(id: str) -> str: ...            # highest file version; PromptNotRegistered
def has(id: str, version: str) -> bool: ...        # a file exists for it (FR-009 authority)
def text_for(id: str, version: str) -> str: ...    # a specific version's text (for A/B arms); PromptNotRegistered
def families() -> tuple[str, ...]: ...             # families with an attacker prompt file
def fingerprint(text: str) -> str: ...             # sha256 hex (stdlib hashlib)
def is_valid_version(v: str) -> bool: ...          # ^[1-9]\d*$
def prompt_path(id, version, directory=None) -> Path: ...
def format_prompt_file(id, version, text) -> str: ...     # the on-disk form
def parse_prompt_file(path) -> PromptFile: ...            # validates name <-> front-matter
def prompt_files(directory=None) -> dict[str, dict[str, PromptFile]]: ...
def read_lock(path=None) -> dict[str, dict[str, str]]: ...
def write_lock(lock, path=None) -> None: ...              # sorted, LF-terminated
def verify_lock() -> list[str]: ...                       # [] if clean; else the drifted prompt ids / file names
```

## The lock

`{ "<id>": { "<version>": "<sha256>" } }`, sorted, fingerprints only. Append-only: a present `(id, version)`
fingerprint is immutable (FR-005).

## Invariants
- Every file's `fingerprint(text) == lock[id][version]`; every lock entry has a file; `verify_lock()` returns the
  ids that break either rule (empty = clean).
- `registry()` carries no secrets and no runtime data; `text` is the authored template only (`DATA_RULE`/`fence`
  excluded, D7).
- Seeded active version for every id is `1` (FR-002), with the text shipped through feature 008 byte-identical
  (the fingerprints are unchanged from the first implementation's `1.0.0` entries).
- No prompt text lives in Python: `attack/attacker.py` and `judge/client.py` call `load_prompt(...)` (or use the
  text an A/B arm pinned via `text_for`).

## Guard test (FR-006/US2/SC-002)
`tests/unit/test_prompt_guard.py` asserts `verify_lock() == []` on the shipped files and, on a copy of them, that an
edited file without a bump, a version file the lock does not pin, a pinned version with no file, a malformed file,
and a non-integer lock version are each reported naming the prompt.

## Bump flow (`scripts/bump_prompt.py`)
```
uv run python scripts/bump_prompt.py judge          # judge.v1.md -> judge.v2.md (front-matter version: 2); edit it
uv run python scripts/bump_prompt.py judge --lock   # record judge@2's fingerprint; the guard is green again
```
`bump` refuses while the current version is unrecorded (no stacking); `--lock` refuses to re-record a pinned
version with a different text unless `--force` (an unmerged version). `tests/unit/test_bump_prompt.py` covers it.

## Provenance recording (FR-003, data-model §Schema v7)
- Adaptive turns: when a turn is produced, record the active (or arm-pinned) `attacker:<family>` id+version and the
  `judge` id+version on the `run_turns` row (`add_turn`).
- Run/single-turn verdict: record the `judge` id+version on the `runs` row (`finish_run`).
- The OWASP report header prints the distinct recorded `id@version` values next to the model slugs, `not recorded`
  for a judged run or attacker-produced turn that predates v7.
- A run or arm naming an `(id, version)` for which `has(...)` is false is refused before any model call (FR-009).

## Secrets (FR-012/SC-007)
The prompt files, the registry and the lock contain ids, versions, fingerprints, and the prompts' own authored
template text only — never a target auth value, URL, or name, and never attack-library fixture text.
