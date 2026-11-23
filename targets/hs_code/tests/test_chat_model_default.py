"""The default chat model is one shared constant, read the same way by load_settings() and app.chat_model(),
so the two can never drift onto different models (app.py:56, agent/config.py:81 before this fix hard-coded the
same string twice). openai/gpt-4o-mini's only tool-capable OpenRouter endpoint is excluded by this account's
guardrail (a 404 "ZDR violation"); openai/gpt-oss-120b is a ZDR, tool-capable endpoint. No network calls:
ChatOpenAI's constructor only builds a client object, never invokes it."""
from agent.config import DEFAULT_CHAT_MODEL, load_settings


def test_load_settings_defaults_to_the_shared_constant():
    assert load_settings({}).chat_model == DEFAULT_CHAT_MODEL


def test_load_settings_honours_an_explicit_override():
    settings = load_settings({"CARGOLINT_CHAT_MODEL": "some/other-model"})
    assert settings.chat_model == "some/other-model"


def test_app_chat_model_defaults_to_the_shared_constant(monkeypatch):
    import app as target_app

    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key-no-network")
    monkeypatch.delenv("CARGOLINT_CHAT_MODEL", raising=False)
    target_app._chat_model_set = False   # undo the autouse no_real_chat_model fixture for this one test

    model = target_app.chat_model()

    assert model is not None and model._llm.model_name == DEFAULT_CHAT_MODEL


def test_app_chat_model_honours_an_explicit_override(monkeypatch):
    import app as target_app

    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-key-no-network")
    monkeypatch.setenv("CARGOLINT_CHAT_MODEL", "some/other-model")
    target_app._chat_model_set = False

    model = target_app.chat_model()

    assert model is not None and model._llm.model_name == "some/other-model"
