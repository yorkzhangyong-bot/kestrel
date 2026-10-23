"""Smoke tests for the sacrificial HS-code target (contracts/hs-code-target.md). No model calls: FakeRawClient
stands in for the model, the way CargoLint's own tests do it."""
import pytest
from fastapi.testclient import TestClient

KEY = "test-key-1234567890"


@pytest.fixture
def fake_model():
    """Inject CargoLint's FakeRawClient and count how often the client factory is called."""
    from agent.llm import set_client_factory
    from rag.translate import clear_cache
    from tests.fakes import FakeRawClient

    clear_cache()
    client = FakeRawClient()
    calls: list[int] = []

    def factory():
        calls.append(1)
        return client

    set_client_factory(factory)
    yield client, calls
    set_client_factory(None)


@pytest.fixture
def target(monkeypatch):
    monkeypatch.setenv("HS_TARGET_API_KEY", KEY)
    import app as target_app

    with TestClient(target_app.app) as client:
        yield client


def test_the_copied_classifier_imports():
    import tools.classify_hs6  # noqa: F401  catches modules the copied files import lazily but weren't copied


def test_start_up_fails_without_a_key(monkeypatch):
    monkeypatch.delenv("HS_TARGET_API_KEY", raising=False)
    import app as target_app

    with pytest.raises(RuntimeError, match="HS_TARGET_API_KEY"):
        with TestClient(target_app.app):
            pass


def test_health_needs_no_key(target):
    response = target.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong-key-value"}])
def test_chat_without_the_right_key_is_refused_before_any_model_call(target, fake_model, headers):
    _, calls = fake_model
    response = target.post("/chat", json={"message": "Hello"}, headers=headers)
    assert response.status_code == 401
    assert response.json() == {"detail": "unauthorized"}
    assert calls == []


def test_chat_checks_the_key_before_the_body(target, fake_model):
    response = target.post("/chat", content=b"not json")
    assert response.status_code == 401


@pytest.mark.parametrize("message", ["Stainless steel vacuum flask, 500 ml", "Hello"])
def test_chat_replies_with_text(target, fake_model, message):
    response = target.post("/chat", json={"message": message}, headers={"X-API-Key": KEY})
    assert response.status_code == 200
    reply = response.json()["reply"]
    assert isinstance(reply, str) and reply.strip()
    assert message in reply


def test_invalid_body_is_422(target, fake_model):
    response = target.post("/chat", json={"text": "Hello"}, headers={"X-API-Key": KEY})
    assert response.status_code == 422


def test_model_failure_gives_502(target, fake_model):
    client, _ = fake_model
    client.fail_on.add("Hello")
    response = target.post("/chat", json={"message": "Hello"}, headers={"X-API-Key": KEY})
    assert response.status_code == 502
    assert response.json() == {"detail": "model call failed"}
