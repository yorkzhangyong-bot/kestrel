"""The version-7 migration is additive: a fresh DB carries the prompt-version columns and an older (v6) DB gains
them without losing data; an unknown future version is still refused (009/FR-004)."""
import sqlite3

import pytest
from cryptography.fernet import Fernet

from kestrel.secrets import Vault
from kestrel.store import SCHEMA_VERSION, TargetStore, UnknownSchemaVersion

FEATURE = "009"

NEW_COLUMNS = {
    "run_turns": {"attacker_prompt_id", "attacker_prompt_version", "judge_prompt_id", "judge_prompt_version"},
    "runs": {"judge_prompt_id", "judge_prompt_version"},
    "experiment_arms": {"prompt_arm_target", "prompt_arm_version"},
}


def _columns(path, table):
    db = sqlite3.connect(path)
    try:
        return {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
    finally:
        db.close()


def _schema_version(path):
    db = sqlite3.connect(path)
    try:
        return db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
    finally:
        db.close()


def test_a_fresh_database_is_version_7_with_the_prompt_columns(tmp_path):  # 009/FR-004
    path = tmp_path / "k.db"
    TargetStore(path, Vault(Fernet.generate_key()))
    assert _schema_version(path) == SCHEMA_VERSION == "8"   # bumped to 8 for feature 010
    for table, cols in NEW_COLUMNS.items():
        assert cols <= _columns(path, table)


def test_a_version_6_database_is_migrated_additively(tmp_path):  # 009/FR-004
    path = tmp_path / "k.db"
    TargetStore(path, Vault(Fernet.generate_key()))                 # create v7
    db = sqlite3.connect(path)                                      # roll back to a v6-shaped database
    try:
        for table, cols in NEW_COLUMNS.items():
            for col in cols:
                db.execute(f"ALTER TABLE {table} DROP COLUMN {col}")
        db.execute("UPDATE meta SET value='6' WHERE key='schema_version'")
        db.commit()
    finally:
        db.close()
    for table, cols in NEW_COLUMNS.items():
        assert not (cols & _columns(path, table))                  # columns gone
    TargetStore(path, Vault(Fernet.generate_key()))                # re-open migrates v6 -> v7
    for table, cols in NEW_COLUMNS.items():
        assert cols <= _columns(path, table)                       # re-added
    assert _schema_version(path) == "8"


def test_an_unknown_future_version_is_refused(tmp_path):  # 009/FR-004 (R11 guard preserved)
    path = tmp_path / "k.db"
    TargetStore(path, Vault(Fernet.generate_key()))
    db = sqlite3.connect(path)
    try:
        db.execute("UPDATE meta SET value='99' WHERE key='schema_version'")
        db.commit()
    finally:
        db.close()
    with pytest.raises(UnknownSchemaVersion):
        TargetStore(path, Vault(Fernet.generate_key()))
