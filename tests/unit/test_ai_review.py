"""redact() and drop_env_hunks() strip secrets from the diff and spec before the AI review prompt is built.

Every credential below is a fake, clearly-marked sample (FAKE…), not a real key; these tests check the scrubbing,
not any live secret. The file is allowlisted in .gitleaks.toml so the scanner ignores these deliberate fixtures.
"""
from ai_review import drop_env_hunks, redact


def test_openai_and_openrouter_keys_are_redacted():
    out = redact("a = sk-FAKEFAKEFAKEFAKEFAKE0000 and b = sk-or-FAKEFAKEFAKEFAKEFAKE0000")
    assert "sk-" not in out and out.count("[REDACTED]") >= 2


def test_github_tokens_are_redacted():
    for token in ("ghp_FAKEFAKEFAKEFAKEFAKE0000", "gho_FAKEFAKEFAKEFAKEFAKE0000",
                  "github_pat_FAKEFAKEFAKEFAKEFAKE0000"):
        out = redact(f"the value is {token} here")
        assert token not in out and "[REDACTED]" in out


def test_aws_access_key_is_redacted():
    out = redact("aws id AKIAFAKEFAKEFAKE0000 in the config")
    assert "AKIAFAKEFAKEFAKE0000" not in out and "[REDACTED]" in out


def test_bearer_token_in_authorization_header_is_redacted():
    out = redact("Authorization: Bearer FAKE0000.FAKE1111.FAKE2222")
    assert "FAKE0000" not in out and "Bearer [REDACTED]" in out


def test_api_key_token_password_secret_assignments_are_redacted():
    assert "FAKEKEY0000" not in redact('api_key = "FAKEKEY0000"')
    assert "FAKETOKEN0000" not in redact("token: FAKETOKEN0000")
    assert "FAKEPASS0000" not in redact("password=FAKEPASS0000")
    assert "FAKESECRET0000" not in redact('secret: "FAKESECRET0000"')
    for sample in ('api_key = "FAKEKEY0000"', "token: FAKETOKEN0000", "password=FAKEPASS0000",
                   'secret: "FAKESECRET0000"'):
        assert "[REDACTED]" in redact(sample)


def test_url_with_user_password_is_redacted():
    out = redact("clone https://fakeuser:FAKEPASS0000@github.com/acme/repo.git")
    assert "FAKEPASS0000" not in out and "fakeuser" not in out and "[REDACTED]@github.com" in out


def test_env_file_hunks_are_dropped():
    diff = (
        "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-x\n+y\n"
        "diff --git a/.env b/.env\n--- a/.env\n+++ b/.env\n@@ -1 +1 @@\n-API_KEY=old\n+API_KEY=sk-FAKEFAKEFAKEFAKE0000\n"
        "diff --git a/config/.env.local b/config/.env.local\n"
        "--- a/config/.env.local\n+++ b/config/.env.local\n@@ -1 +1 @@\n-A=1\n+A=2\n")
    out = drop_env_hunks(diff)
    assert "app.py" in out                                   # the ordinary file stays
    assert ".env" not in out and "API_KEY" not in out        # the .env and .env.local sections are gone


def test_clean_text_passes_through_unchanged():
    clean = "def greet(name):\n    return f'Hello, {name}!'\n\nresult = compute(1, 2)\n"
    assert redact(clean) == clean
