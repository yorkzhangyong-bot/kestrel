"""Saved targets in one SQLite file, through the standard-library sqlite3 module, no ORM (data-model.md; research R6).

Rules the database can't check (URL, template and header rules, value length) are enforced by the API before saving.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from kestrel.secrets import Vault

SCHEMA_VERSION = "1"

SCHEMA = """
CREATE TABLE IF NOT EXISTS targets (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 100),   -- trimmed, 1 to 100 characters
    name_key TEXT NOT NULL UNIQUE,                               -- name.casefold(): unique ignoring case (FR-013)
    url TEXT NOT NULL,
    method TEXT NOT NULL CHECK (method IN ('POST', 'GET')),
    body_template TEXT NOT NULL,
    response_path TEXT NOT NULL,
    permission_confirmed_at TEXT NOT NULL,                       -- ISO-8601 UTC
    terms_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS target_headers (
    id INTEGER PRIMARY KEY,
    target_id INTEGER NOT NULL REFERENCES targets(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    name TEXT NOT NULL,
    value_encrypted TEXT NOT NULL                                -- Fernet token; never returned by the API
);
CREATE UNIQUE INDEX IF NOT EXISTS target_headers_name ON target_headers (target_id, lower(name));
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class NameTaken(Exception):
    """Another saved target has this display name, ignoring case."""


class TargetNotFound(LookupError):
    pass


class MissingStoredValue(LookupError):
    """A header asked to keep its stored value, but the target has no stored header with that name."""


@dataclass(frozen=True)
class StoredHeader:
    name: str
    readable: bool  # False when the current key can't decrypt the value


@dataclass(frozen=True)
class HeaderValue:
    name: str
    value: str | None = None  # None when the current key can't decrypt the value

    def __repr__(self) -> str:  # never print a header value
        return f"HeaderValue(name={self.name!r}, value={'<unreadable>' if self.value is None else '<hidden>'})"


@dataclass(frozen=True)
class Target:
    id: int
    name: str
    url: str
    method: str
    body_template: str
    response_path: str
    permission_confirmed_at: str
    terms_version: str
    created_at: str
    updated_at: str
    headers: tuple[StoredHeader, ...] = ()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class TargetStore:
    def __init__(self, db_path: Path, vault: Vault) -> None:
        self._path = Path(db_path)
        self._vault = vault
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(SCHEMA)
            db.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)", (SCHEMA_VERSION,))

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """One connection per call; commits on success and rolls back on any error."""
        db = sqlite3.connect(self._path)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys = ON")
            db.execute("PRAGMA secure_delete = ON")
            with db:
                yield db
        finally:
            db.close()

    def create_target(self, *, name: str, url: str, method: str, headers: list[tuple[str, str]], body_template: str,
                      response_path: str, terms_version: str) -> Target:
        now = utc_now()
        try:
            with self.connect() as db:
                cursor = db.execute(
                    "INSERT INTO targets (name, name_key, url, method, body_template, response_path,"
                    " permission_confirmed_at, terms_version, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (name, name.casefold(), url, method, body_template, response_path, now, terms_version, now, now))
                target_id = cursor.lastrowid
                self._insert_headers(db, target_id, [(n, self._vault.encrypt(v)) for n, v in headers])
        except sqlite3.IntegrityError as error:
            if "name_key" in str(error):
                raise NameTaken(name) from None
            raise
        return self.get_target(target_id)

    def update_target(self, target_id: int, *, name: str, url: str, method: str,
                      headers: list[tuple[str, str | None]], body_template: str, response_path: str,
                      terms_version: str) -> Target:
        """A value of None keeps the stored value of that header (FR-017); headers left out are removed.

        The permission date is renewed when the URL changes or newer terms are accepted (FR-018).
        """
        now = utc_now()
        try:
            with self.connect() as db:
                row = db.execute("SELECT url, terms_version, permission_confirmed_at FROM targets WHERE id = ?",
                                 (target_id,)).fetchone()
                if row is None:
                    raise TargetNotFound(target_id)
                stored = {h["name"].lower(): h["value_encrypted"] for h in self._header_rows(db, target_id)}
                encrypted = []
                for header_name, value in headers:
                    if value is None:
                        if header_name.lower() not in stored:
                            raise MissingStoredValue(header_name)
                        encrypted.append((header_name, stored[header_name.lower()]))
                    else:
                        encrypted.append((header_name, self._vault.encrypt(value)))
                renewed = url != row["url"] or terms_version != row["terms_version"]
                db.execute(
                    "UPDATE targets SET name = ?, name_key = ?, url = ?, method = ?, body_template = ?,"
                    " response_path = ?, permission_confirmed_at = ?, terms_version = ?, updated_at = ? WHERE id = ?",
                    (name, name.casefold(), url, method, body_template, response_path,
                     now if renewed else row["permission_confirmed_at"], terms_version, now, target_id))
                db.execute("DELETE FROM target_headers WHERE target_id = ?", (target_id,))
                self._insert_headers(db, target_id, encrypted)
        except sqlite3.IntegrityError as error:
            if "name_key" in str(error):
                raise NameTaken(name) from None
            raise
        return self.get_target(target_id)

    def delete_target(self, target_id: int) -> None:
        """Remove the target; its header rows go with it (ON DELETE CASCADE, overwritten by secure_delete)."""
        with self.connect() as db:
            if db.execute("DELETE FROM targets WHERE id = ?", (target_id,)).rowcount == 0:
                raise TargetNotFound(target_id)

    def key_matches(self) -> bool:
        """False when the current key can't decrypt a stored header value (research R5)."""
        with self.connect() as db:
            row = db.execute("SELECT value_encrypted FROM target_headers LIMIT 1").fetchone()
        return row is None or self._vault.decrypt(row["value_encrypted"]) is not None

    def list_targets(self) -> list[Target]:
        with self.connect() as db:
            ids = [row["id"] for row in db.execute("SELECT id FROM targets ORDER BY name_key, id")]
        return [self.get_target(target_id) for target_id in ids]

    def get_target(self, target_id: int) -> Target:
        with self.connect() as db:
            row = db.execute("SELECT * FROM targets WHERE id = ?", (target_id,)).fetchone()
            if row is None:
                raise TargetNotFound(target_id)
            headers = tuple(StoredHeader(name=h["name"], readable=self._vault.decrypt(h["value_encrypted"]) is not None)
                            for h in self._header_rows(db, target_id))
        return Target(id=row["id"], name=row["name"], url=row["url"], method=row["method"],
                      body_template=row["body_template"], response_path=row["response_path"],
                      permission_confirmed_at=row["permission_confirmed_at"], terms_version=row["terms_version"],
                      created_at=row["created_at"], updated_at=row["updated_at"], headers=headers)

    def resolve_headers(self, target_id: int) -> list[HeaderValue]:
        """The decrypted header values, for the tester only; value is None when this key can't decrypt one."""
        with self.connect() as db:
            if db.execute("SELECT 1 FROM targets WHERE id = ?", (target_id,)).fetchone() is None:
                raise TargetNotFound(target_id)
            return [HeaderValue(name=h["name"], value=self._vault.decrypt(h["value_encrypted"]))
                    for h in self._header_rows(db, target_id)]

    @staticmethod
    def _header_rows(db: sqlite3.Connection, target_id: int) -> list[sqlite3.Row]:
        return db.execute("SELECT name, value_encrypted FROM target_headers WHERE target_id = ? ORDER BY position",
                          (target_id,)).fetchall()

    @staticmethod
    def _insert_headers(db: sqlite3.Connection, target_id: int, encrypted: list[tuple[str, str]]) -> None:
        db.executemany("INSERT INTO target_headers (target_id, position, name, value_encrypted) VALUES (?, ?, ?, ?)",
                       [(target_id, position, name, token) for position, (name, token) in enumerate(encrypted)])
