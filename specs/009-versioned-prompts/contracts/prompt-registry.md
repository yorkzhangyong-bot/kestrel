# Contract: prompt registry + guard (internal)

New module `src/kestrel/prompt_registry.py` and committed lock `src/kestrel/prompt_versions.lock.json`. This is the
authority for valid `(id, version)` pairs and active versions (FR-001/002/005/006/009).

## Types / functions (proposed signatures)

```python
@dataclass(frozen=True)
class PromptEntry:
    id: str          # "attacker:<family>" | "judge" | "recommender"
    version: str     # active version, "MAJOR.MINOR.PATCH"
    text: str        # authored template text (static; attacker resolved per family)
    fingerprint: str # sha256(text) hex

def registry() -> list[PromptEntry]: ...          # active entries, sorted by id
def fingerprint(text: str) -> str: ...            # sha256 hex (stdlib hashlib)
def is_valid_version(v: str) -> bool: ...         # regex MAJOR.MINOR.PATCH
def has(id: str, version: str) -> bool: ...       # exists in the lock (FR-009 authority)
def text_for(id: str, version: str) -> str: ...   # resolve a specific version's text (for A/B arms)
def verify_lock() -> list[str]: ...               # [] if clean; else ids whose live fingerprint != lock active
```

## Invariants
- Each active entry's `fingerprint == lock[id][version]`; `verify_lock()` returns the mismatched ids (empty = clean).
- `registry()` carries no secrets and no runtime data; `text` is the authored template only (`DATA_RULE`/`fence`
  excluded, D7).
- Seeded active version for every id is `1.0.0` (FR-002), with the text shipped through feature 008 unchanged.

## Guard test (FR-006/US2/SC-002)
A `judge_eval`-independent unit test asserts `verify_lock() == []`. Editing any prompt's authored text without
appending a new `(version → fingerprint)` to the lock makes `verify_lock()` return that id → the test fails and
names the prompt. The fix is: bump the version in code **and** append the new fingerprint to the lock. Rewriting an
existing `(id, version)` fingerprint is an append-only violation (FR-005) caught in review.

## Provenance recording (FR-003, data-model §Schema v7)
- Adaptive turns: when a turn is produced, record the active (or arm-pinned) `attacker:<family>` id+version and the
  `judge` id+version on the `run_turns` row (`add_turn`).
- Run/single-turn verdict: record the `judge` id+version on the `runs` row (`finish_run`).
- A run or arm naming an `(id, version)` for which `has(...)` is false is refused before any model call (FR-009).

## Secrets (FR-012/SC-007)
The registry and the lock contain ids, versions, fingerprints, and the prompts' own authored template text only —
never a target auth value, URL, or name, and never attack-library fixture text.
