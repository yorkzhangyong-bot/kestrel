"""redact() and drop_env_hunks() strip secrets from the diff and spec before the AI review prompt is built.

Benign placeholder credentials stand in for real ones here; these tests check the scrubbing, not any live key.
"""
from ai_review import drop_env_hunks, redact


def test_openai_and_openrouter_keys_are_redacted():
    out = redact("a = sk-abcDEF0123456789012345 and b = sk-or-v1-0123456789abcdef0123456789abcdef")
    assert "sk-" not in out and out.count("[REDACTED]") >= 2


def test_github_tokens_are_redacted():
    for token in ("ghp_0123456789abcdefghijABCDEFGHIJ012345",
                  "gho_0123456789abcdefghijABCDEFGHIJ012345",
                  "github_pat_11ABCDE0123456789_abcdefABCDEF0123456789abcdef"):
        out = redact(f"the value is {token} here")
        assert token not in out and "[REDACTED]" in out


def test_aws_access_key_is_redacted():
    out = redact("aws id AKIAIOSFODNN7EXAMPLE in the config")
    assert "AKIAIOSFODNN7EXAMPLE" not in out and "[REDACTED]" in out


def test_bearer_token_in_authorization_header_is_redacted():
    out = redact("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.c2lnbmF0dXJl")
    assert "eyJhbGci" not in out and "Bearer [REDACTED]" in out


def test_api_key_token_password_secret_assignments_are_redacted():
    assert "hunter2value" not in redact('api_key = "hunter2value"')
    assert "abc123def456" not in redact("token: abc123def456")
    assert "p@ssw0rdxyz" not in redact("password=p@ssw0rdxyz")
    assert "topsecretval" not in redact('secret: "topsecretval"')
    for sample in ('api_key = "hunter2value"', "token: abc123def456", "password=p@ssw0rdxyz", 'secret: "topsecretval"'):
        assert "[REDACTED]" in redact(sample)


def test_url_with_user_password_is_redacted():
    out = redact("clone https://alice:s3cr3tpw@github.com/acme/repo.git")
    assert "s3cr3tpw" not in out and "alice" not in out and "[REDACTED]@github.com" in out


def test_env_file_hunks_are_dropped():
    diff = (
        "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-x\n+y\n"
        "diff --git a/.env b/.env\n--- a/.env\n+++ b/.env\n@@ -1 +1 @@\n-API_KEY=old\n+API_KEY=sk-newsecret0123456789abcd\n"
        "diff --git a/config/.env.local b/config/.env.local\n"
        "--- a/config/.env.local\n+++ b/config/.env.local\n@@ -1 +1 @@\n-A=1\n+A=2\n")
    out = drop_env_hunks(diff)
    assert "app.py" in out                                   # the ordinary file stays
    assert ".env" not in out and "API_KEY" not in out        # the .env and .env.local sections are gone


def test_clean_text_passes_through_unchanged():
    clean = "def greet(name):\n    return f'Hello, {name}!'\n\nresult = compute(1, 2)\n"
    assert redact(clean) == clean
