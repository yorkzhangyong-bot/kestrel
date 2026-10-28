#!/usr/bin/env python3
"""AI code review gate for a pull request.

Sends the review checklist (system prompt) and the feature's spec plus the PR diff against master (user message)
to an OpenRouter model, asks for JSON findings and a verdict, posts them as a PR comment, and exits 1 if any
finding is ``severe``. On any error or HTTP 429 it retries twice; if the review still cannot run it posts a
short "review unavailable" comment and exits 0 (an unreachable OpenAI gpt-5.4-mini via OpenRouter must never
block a merge).

Privacy: the model prompt contains only the checklist, the feature spec, and the diff. Environment variables and
files outside the diff and the spec are never placed in the prompt.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
CHECKLIST = ROOT / ".github" / "review" / "checklist.md"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "openai/gpt-5.4-mini"
MAX_DIFF_CHARS = 60_000           # keep the prompt within the model's context window and cost in check
RETRIES = 2                       # retry twice on any error or 429 (three attempts total)

# A change to any of these paths puts the review into strict mode (see STRICT_NOTE).
STRICT_PATHS = ("src/kestrel/attack", "src/kestrel/secrets.py", "src/kestrel/report/render.py")
STRICT_NOTE = (
    "\n\nSTRICT MODE: this diff touches security-critical code (the attack loop, the secrets vault, or the report "
    "HTML renderer). Hold it to the highest bar. Treat as SEVERE: any secret, target URL, header name or header "
    "value sent to a model or written to a log; any raw/unescaped HTML in the report renderer; any weakening of "
    "canary/hard-evidence handling; any experience-store write outside the attack flow.")


def branch_name() -> str:
    ref = os.environ.get("GITHUB_HEAD_REF") or os.environ.get("GITHUB_REF_NAME")
    if ref:
        return ref
    done = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                          cwd=ROOT, capture_output=True, text=True)
    return done.stdout.strip()


def feature_spec() -> str:
    match = re.match(r"(\d{3,})", branch_name())
    if not match:
        return ""
    specs = sorted(ROOT.glob(f"specs/{match.group(1)}-*/spec.md"))
    return specs[0].read_text(encoding="utf-8") if specs else ""


def base_ref() -> str:
    return os.environ.get("GITHUB_BASE_REF", "master")


def pr_diff() -> str:
    base = base_ref()
    # In CI the checkout is unshallow (fetch-depth: 0); fetching the base is a cheap no-op if already present.
    subprocess.run(["git", "fetch", "--quiet", "origin", base], cwd=ROOT, capture_output=True, text=True)
    for target in (f"origin/{base}...HEAD", f"{base}...HEAD"):
        done = subprocess.run(["git", "diff", target], cwd=ROOT, capture_output=True, text=True)
        if done.returncode == 0:
            return done.stdout
    return ""


def changed_files(diff: str) -> list[str]:
    return re.findall(r"^diff --git a/(.+?) b/", diff, re.MULTILINE)


def is_strict(diff: str) -> bool:
    return any(path.startswith(STRICT_PATHS) for path in changed_files(diff))


def build_messages(spec: str, diff: str) -> list[dict]:
    system = CHECKLIST.read_text(encoding="utf-8")
    if is_strict(diff):
        system += STRICT_NOTE
    system += (
        "\n\nReturn ONLY a JSON object of the form "
        '{"findings": [{"severity": "severe|major|minor", "file": "path", "line": 0, "reason": "..."}], '
        '"verdict": "one short sentence"}. Use file paths and line numbers from the diff. If the diff is clean, '
        "return an empty findings list.")
    if len(diff) > MAX_DIFF_CHARS:
        diff = diff[:MAX_DIFF_CHARS] + "\n...[diff truncated]..."
    user = f"## Feature spec\n\n{spec or '(no spec found for this branch)'}\n\n## Pull request diff\n\n{diff}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def call_model(messages: list[dict], api_key: str) -> dict:
    """Call the model and parse its JSON. Raises on any failure so the caller can retry."""
    payload = {"model": MODEL, "messages": messages, "temperature": 0,
               "response_format": {"type": "json_object"}}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    response = httpx.post(OPENROUTER_URL, json=payload, headers=headers, timeout=120.0)
    if response.status_code == 429:
        raise RuntimeError("rate limited (429)")
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        raise ValueError("model did not return a JSON object")
    return json.loads(match.group(0))


def review_with_retries(messages: list[dict], api_key: str) -> dict | None:
    last_error: Exception | None = None
    for attempt in range(RETRIES + 1):
        try:
            return call_model(messages, api_key)
        except Exception as error:  # any error or 429: wait and retry
            last_error = error
            print(f"Review attempt {attempt + 1} failed: {error}", file=sys.stderr)
            time.sleep(2 ** attempt)
    print(f"Review could not run after {RETRIES + 1} attempts: {last_error}", file=sys.stderr)
    return None


def render_comment(result: dict) -> str:
    findings = result.get("findings") or []
    verdict = str(result.get("verdict") or "").strip()
    lines = ["## 🔎 AI code review", ""]
    if not findings:
        lines.append("No findings.")
    else:
        lines += ["| Severity | File | Line | Reason |", "| --- | --- | --- | --- |"]
        for finding in findings:
            severity = str(finding.get("severity", "")).strip() or "minor"
            file = str(finding.get("file", "")).strip() or "—"
            line = str(finding.get("line", "")).strip() or "—"
            reason = str(finding.get("reason", "")).replace("|", "\\|").replace("\n", " ").strip()
            lines.append(f"| {severity} | {file} | {line} | {reason} |")
    if verdict:
        lines += ["", f"**Verdict**: {verdict}"]
    lines += ["", "_Generated by the QA pipeline's AI reviewer (OpenAI gpt-5.4-mini via OpenRouter); advisory except "
              "for severe findings._"]
    return "\n".join(lines)


def post_comment(body: str) -> None:
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    number = pr_number()
    if not (token and repo and number):
        print("No GitHub PR context; comment not posted. Body follows:\n" + body)
        return
    response = httpx.post(
        f"https://api.github.com/repos/{repo}/issues/{number}/comments",
        json={"body": body},
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        timeout=30.0)
    if response.status_code >= 400:
        print(f"Could not post PR comment (status {response.status_code}): {response.text}", file=sys.stderr)


def pr_number() -> int | None:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if event_path and Path(event_path).exists():
        data = json.loads(Path(event_path).read_text(encoding="utf-8"))
        pull = data.get("pull_request") or {}
        if pull.get("number"):
            return int(pull["number"])
    match = re.match(r"refs/pull/(\d+)/", os.environ.get("GITHUB_REF", ""))
    return int(match.group(1)) if match else None


def main() -> int:
    try:  # keep stdout UTF-8 so emoji in the comment body never crash a non-UTF-8 console
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    api_key = os.environ.get("OPENROUTER_API_KEY")
    diff = pr_diff()
    spec = feature_spec()

    result = review_with_retries(build_messages(spec, diff), api_key) if api_key else None
    if result is None:
        reason = "no OPENROUTER_API_KEY is configured" if not api_key else "the model could not be reached"
        post_comment(f"## 🔎 AI code review\n\nThe automated review was unavailable ({reason}); "
                     "it did not block this pull request.")
        return 0

    findings = result.get("findings") or []
    post_comment(render_comment(result))
    severe = [f for f in findings if str(f.get("severity", "")).lower() == "severe"]
    if severe:
        print(f"{len(severe)} severe finding(s); failing the review gate.")
        return 1
    print(f"Review complete: {len(findings)} finding(s), none severe.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
