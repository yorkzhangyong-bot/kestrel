"""End-to-end harness (tasks.md T019): the sacrificial target and Kestrel's API run as subprocesses, and the screen
is driven through Streamlit's AppTest. Every test here is marked e2e, and all of them are skipped without
OPENROUTER_API_KEY, because the target makes real model calls through CargoLint."""
from __future__ import annotations

import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from streamlit.testing.v1 import AppTest

E2E_DIR = Path(__file__).resolve().parent
REPO_ROOT = E2E_DIR.parents[1]
TARGET_DIR = REPO_ROOT / "targets" / "hs_code"


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items):
    for item in items:
        if Path(str(item.path)).resolve().is_relative_to(E2E_DIR):
            item.add_marker(pytest.mark.e2e)


@pytest.fixture(scope="session", autouse=True)
def _needs_openrouter_key():
    if not os.environ.get("OPENROUTER_API_KEY"):
        pytest.skip("OPENROUTER_API_KEY is not set; the sacrificial target needs it for its model calls.")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _Server:
    """A server process started with its own interpreter (not `uv run`), so stopping it stops the server itself."""

    def __init__(self, name: str, args: list[str], cwd: Path, env: dict[str, str], log_path: Path) -> None:
        self.name, self.args, self.cwd, self.env, self.log_path = name, args, cwd, env, log_path
        self.process: subprocess.Popen | None = None
        self._log = None

    def start(self, ready_url: str, timeout: float) -> None:
        self._log = open(self.log_path, "wb")
        self.process = subprocess.Popen(self.args, cwd=self.cwd, env=self.env, stdout=self._log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"{self.name} exited with code {self.process.returncode}; see {self.log_path}")
            try:
                if httpx.get(ready_url, timeout=2).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        self.stop()
        raise RuntimeError(f"{self.name} didn't become ready within {timeout:.0f} s; see {self.log_path}")

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=15)
        if self._log is not None:
            self._log.close()


def _target_python() -> str:
    found = subprocess.run(["uv", "run", "--project", str(TARGET_DIR), "python", "-c", "import sys; print(sys.executable)"],
                           cwd=TARGET_DIR, capture_output=True, text=True, check=True)
    return found.stdout.strip().splitlines()[-1]


@pytest.fixture(scope="session")
def hs_target(tmp_path_factory):
    """The sacrificial HS-code target on a free port, with a fresh key and canary (known values for SC-004/SC-008)."""
    key = secrets.token_urlsafe(24)
    canary = "KESTREL-CANARY-" + secrets.token_urlsafe(12)
    port = _free_port()
    log_path = tmp_path_factory.mktemp("logs") / "hs_target.log"
    # HS_TARGET_CANARY puts the canary in the agent's system prompt so a leak attack can surface it (FR-036).
    env = {**os.environ, "HS_TARGET_API_KEY": key, "HS_TARGET_CANARY": canary, "PYTHONUNBUFFERED": "1"}
    server = _Server("sacrificial HS-code target",
                     [_target_python(), "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(port)],
                     TARGET_DIR, env, log_path)
    server.start(f"http://127.0.0.1:{port}/health", timeout=300)
    yield SimpleNamespace(url=f"http://127.0.0.1:{port}/chat", key=key, canary=canary, port=port, log_path=log_path)
    server.stop()


@pytest.fixture
def library_required():
    """Feature-002 e2e tests need the shipped attack library; skip until it is assembled (T013 deferred)."""
    from kestrel.attacks.library import DATA_FILE

    if not DATA_FILE.exists():
        pytest.skip("Attack library data file not assembled yet (T013 deferred).")


@pytest.fixture
def kestrel_api(tmp_path_factory):
    """Kestrel's API in local mode, with its database and key file in a temp folder.

    Function-scoped: each test gets a fresh database, so a target or run saved by one test does not leak into
    another (the attack tests save targets; test_us2_save asserts a clean list). The target stays session-scoped,
    since loading CargoLint is the slow part; restarting the lightweight API per test is cheap.
    """
    data = tmp_path_factory.mktemp("kestrel")
    port = _free_port()
    log_path = data / "kestrel_api.log"
    env = {**os.environ, "KESTREL_MODE": "local", "KESTREL_DB_PATH": str(data / "kestrel.db"),
           "KESTREL_KEY_FILE": str(data / "secret.key"), "PYTHONUNBUFFERED": "1",
           # Keep the adaptive e2e quick and cheap: a low turn cap and time limit (feature 003).
           "KESTREL_ADAPTIVE_MAX_TURNS": "2", "KESTREL_ADAPTIVE_TIME_LIMIT_S": "120"}
    env.pop("KESTREL_SECRET_KEY", None)
    server = _Server("Kestrel API",
                     [sys.executable, "-m", "uvicorn", "--factory", "kestrel.api.main:create_app",
                      "--host", "127.0.0.1", "--port", str(port)],
                     REPO_ROOT, env, log_path)
    server.start(f"http://127.0.0.1:{port}/api/config", timeout=60)
    yield SimpleNamespace(url=f"http://127.0.0.1:{port}", log_path=log_path)
    server.stop()


@pytest.fixture
def ui(kestrel_api, monkeypatch):
    monkeypatch.setenv("KESTREL_API_URL", kestrel_api.url)
    return AppTest.from_file(str(REPO_ROOT / "ui" / "app.py"), default_timeout=120)


@pytest.fixture
def fill_form(hs_target):
    """Fill the form for the sacrificial target, leaving the defaults (POST, {"message": "{{prompt}}"}) unchanged."""

    def fill(at: AppTest, *, response_path: str | None = None, display_name: str | None = None) -> AppTest:
        at.run()
        if display_name is not None:
            at.text_input(key="display_name").input(display_name)
        at.text_input(key="url").input(hs_target.url)
        at.button(key="add_header").click().run()
        at.text_input(key="header_name_0").input("X-API-Key")
        at.text_input(key="header_value_0").input(hs_target.key)
        if response_path is not None:
            at.text_input(key="response_path").input(response_path)
        return at.run()

    return fill


@pytest.fixture
def assert_no_secret_in_logs(hs_target, kestrel_api):
    """SC-004: the target's key must appear 0 times in either process's output."""

    def check() -> None:
        for path in (hs_target.log_path, kestrel_api.log_path):
            text = path.read_text(encoding="utf-8", errors="replace")
            assert text.count(hs_target.key) == 0, f"the target's key appears in {path.name}"

    return check
