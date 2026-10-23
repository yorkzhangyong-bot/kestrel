"""Shared fixtures for the sacrificial target's offline tests."""
import pytest


@pytest.fixture(autouse=True)
def no_real_chat_model():
    """Force the classifier fallback by default, so no test reaches a real model even when a key is in the env.

    Teeth tests opt in by calling app.set_chat_model(a fake). Reset to pristine afterwards.
    """
    import app as target_app

    target_app.set_chat_model(None)
    yield
    target_app._chat_model = None
    target_app._chat_model_set = False
