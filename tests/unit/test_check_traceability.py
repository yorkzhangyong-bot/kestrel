"""check_traceability.py PR-rule helpers for implementation PRs (feature 006).

Traces 006/FR-002 (classification), 006/FR-009 (Spec-PR reference), 006/FR-010, 006/FR-011 (spec-change note),
006/SC-003, 006/SC-007. (No FEATURE marker — the bare ids in the samples below are not references to 006's own
requirements.) These pure helpers take plain arguments so the rules are tested without GitHub.

Added 2026-11-24, the honest Spec-PR path for refactor and bug-fix PRs: 006/FR-009 (amended), 006/FR-015,
006/FR-016, 006/FR-017, 006/FR-018, 006/FR-020, 006/FR-022, 006/FR-024, 006/SC-008, 006/SC-009 — the decision
matrix of specs/006-human-approved-spec/contracts/pr-rules.md over ``spec_pr_rule_problems``, ``parse_pr_state``,
``pr_state``, ``parse_issue_lookup``, ``issue_exists_in_repo`` and ``pr_rule_problems``.
"""
import time

import check_traceability as ct
import pytest


def test_is_spec_only_depends_only_on_code_dirs():
    assert ct.is_spec_only(["specs/006-x/spec.md", "docs/qa-pipeline.md"]) is True
    assert ct.is_spec_only([".github/workflows/qa.yml", "specs/006-x/plan.md"]) is True   # non-code config is ok
    assert ct.is_spec_only(["specs/006-x/spec.md", "src/kestrel/store.py"]) is False
    assert ct.is_spec_only(["tests/unit/test_x.py"]) is False
    assert ct.is_spec_only(["scripts/check_spec.py"]) is False


def test_spec_pr_rule_fires_only_for_src_or_ui_changes_on_any_branch():
    # 006/FR-009: a Spec-PR reference is required when a PR changes application code, whatever the branch is named.
    assert ct.changes_app_code(["src/kestrel/store.py"]) is True
    assert ct.changes_app_code(["ui/app.py", "tests/unit/test_x.py"]) is True
    # tests-only, scripts-only or docs-only changes do not require a Spec-PR reference.
    assert ct.changes_app_code(["tests/unit/test_x.py", "scripts/check_spec.py", "docs/x.md"]) is False


def test_spec_change_note_required_only_with_a_spec_and_src_change():
    both = ["specs/006-x/spec.md", "src/kestrel/store.py"]
    assert ct.needs_spec_change_note(both) is True
    assert ct.spec_change_ok(both, "just a description") is False
    assert ct.spec_change_ok(both, "spec-change: narrowed FR-003\n") is True
    # Not required when src is untouched, or when no spec file changed.
    assert ct.needs_spec_change_note(["specs/006-x/spec.md", "scripts/check_spec.py"]) is False
    assert ct.spec_change_ok(["src/kestrel/store.py"], "") is True


def test_has_spec_pr_reference():
    assert ct.has_spec_pr_reference("Implements the thing.\nSpec-PR: #2\n") is True
    assert ct.has_spec_pr_reference("Spec-PR:#12") is True
    assert ct.has_spec_pr_reference("no reference at all") is False
    assert ct.has_spec_pr_reference("") is False
    assert ct.has_spec_pr_reference(None) is False


def test_justified_identifiers_parses_feature_scoped_lines():
    # A requirement counts as traced when justified as a feature-scoped line "<prefix>/FR-00x: <reason>".
    # Sample ids are outside the 006 range so this test does not itself trace real requirements.
    text = ("# Traceability\n\n"
            "- 006/FR-900: justified outside unit tests\n"
            "- 006-SC-901: enforced by branch protection\n"
            "006/FR-902: manual settings in a doc\n"
            "007/FR-903: belongs to another feature\n"
            "FR-904: no feature prefix, not counted\n")
    assert ct.justified_identifiers(text, "006") == {"FR-900", "SC-901", "FR-902"}


# ---- the honest Spec-PR path (feature 006, added 2026-11-24) ----
#
# Existing assertions above stay untouched (SC-009). The cases below mirror the row list of
# contracts/pr-rules.md one-for-one; a case's expected marker is a distinctive substring of the row's own
# message (never a synthetic tag the shipped code has to emit), so the production messages stay plain prose.


def _stub(answer: bool):
    """A fixed-answer issue_exists callable; the call-discipline tests below use their own counting stub."""
    return lambda number: answer


def _counting_stub(answer: bool):
    calls: list[str] = []

    def stub(number: str) -> bool:
        calls.append(number)
        return answer

    stub.calls = calls
    return stub


_ROW2 = "conflicting declaration"
_ROW3 = "must carry a Spec-PR declaration"
_ROW4 = "needs exactly one 'Spec-PR:' line"
_ROW5 = "needs a 'Spec-PR-reason:' line"
_ROW6 = "more than one 'Spec-PR-reason:' line"
_ROW7 = "malformed reason"
_ROW8 = "(FR-015, FR-016)"
_ROW9 = "contradicts the reason"
_ROW10 = "is not an issue of this repository"
_HINT_ROWS = {_ROW2, _ROW4, _ROW6}
_ALL_ROWS = (_ROW2, _ROW3, _ROW4, _ROW5, _ROW6, _ROW7, _ROW8, _ROW9, _ROW10)

# (title, body, labels, issue_exists stub, expected marker substring or None for a pass) — contracts/pr-rules.md
# "Tests" section; row 1 and row 11 are both "pass".
SPEC_PR_RULE_CASES = [
    ("numbered + none, no reason line", "Spec-PR: #12\nSpec-PR: none\n", [], _stub(True), _ROW2),
    ("valid none + 'none because' line + reason + label",
     "Spec-PR: none\nSpec-PR: none because it is a refactor\nSpec-PR-reason: refactor\n",
     ["refactor"], _stub(True), _ROW4),
    ("valid none + 'TBD' line + reason + label",
     "Spec-PR: none\nSpec-PR: TBD\nSpec-PR-reason: refactor\n", ["refactor"], _stub(True), _ROW4),
    ("numbered + 'none because x'", "Spec-PR: #12\nSpec-PR: none because x\n", [], _stub(True), _ROW2),
    ("reason 'bugfix:#12' (spaces optional)",
     "Spec-PR: none\nSpec-PR-reason: bugfix:#12\n", ["bugfix"], _stub(True), None),
    ("reason 'bugfix:<tab>#12'",
     "Spec-PR: none\nSpec-PR-reason: bugfix:\t  #12\n", ["bugfix"], _stub(True), None),
    ("non-ASCII digits", "Spec-PR: none\nSpec-PR-reason: bugfix: #١٢\n", ["bugfix"], _stub(True), _ROW7),
    ("CRLF body, label case", "Spec-PR: none\r\nSpec-PR-reason: refactor\r\n", ["Refactor"], _stub(True), None),
    ("numbered value on the next line (unchanged \\s* tolerance)", "Spec-PR:\n#12\n", [], _stub(True), None),
    ("indented none line", "  Spec-PR: none\n  Spec-PR-reason: refactor\n", ["refactor"], _stub(True), _ROW3),
    ("bulleted none line", "- Spec-PR: none\n- Spec-PR-reason: refactor\n", ["refactor"], _stub(True), _ROW3),
    ("reason line, no Spec-PR line", "Spec-PR-reason: refactor\n", ["refactor"], _stub(True), _ROW3),
    ("valid refactor path", "Spec-PR: none\nSpec-PR-reason: refactor\n", ["refactor"], _stub(True), None),
    ("honest-path lines inside a multi-line <!-- --> block, keyed lines in column 1 (raw read: they count)",
     "Fixes it.\n<!--\nSpec-PR: none\nSpec-PR-reason: refactor\n-->\n", ["refactor"], _stub(True), None),
    ("honest-path lines after an unterminated '<!--' (raw read: they count)",
     "Summary\n<!-- oops\nSpec-PR: none\nSpec-PR-reason: refactor\n", ["refactor"], _stub(True), None),
    ("numbered only inside a multi-line <!-- --> block, column 1 (raw read: it counts)",
     "<!--\nSpec-PR: #12\n-->\n", [], _stub(True), None),
    ("reason line inside a multi-line <!-- --> block, column 1, beside a numbered line (raw read: a conflict)",
     "Spec-PR: #12\n<!--\nSpec-PR-reason: refactor\n-->\n", [], _stub(True), _ROW2),
    ("one-line comment '<!-- Spec-PR: #12 -->' is not a keyed line",
     "<!-- Spec-PR: #12 -->\n", [], _stub(True), _ROW3),
    ("one-line honest-path pair in comments is not keyed",
     "<!-- Spec-PR: none -->\n<!-- Spec-PR-reason: refactor -->\n", ["refactor"], _stub(True), _ROW3),
    ("numbered + one-line reason comment (not a keyed line: no conflict)",
     "Spec-PR: #12\n<!-- Spec-PR-reason: refactor -->\n", [], _stub(True), None),
    ("numbered PR quoting 'Spec-PR: none' in a fenced block (conflict, with the hint)",
     "Spec-PR: #12\n\n```text\nSpec-PR: none\n```\n", [], _stub(True), _ROW2),
    ("code span with '<!--' before an honest declaration",
     "The bug was in handling `<!--` at a line start.\n\nSpec-PR: none\nSpec-PR-reason: bugfix: #77\n",
     ["bugfix"], _stub(True), None),
    ("fenced code block holding an unterminated '<!--', numbered after",
     "Template head:\n\n```html\n<!-- start of the template\n```\n\nSpec-PR: #12\n", [], _stub(True), None),
    ("mid-line unterminated '<!--', numbered after", "Some text <!-- oops\n\nSpec-PR: #12\n", [], _stub(True), None),
    ("comment glued to the key is not column 1 (as today)", "<!-- c -->Spec-PR: #12\n", [], _stub(True), _ROW3),
    ("'nonetheless' beside a number (starts with none: conflict)",
     "Spec-PR: #12\nSpec-PR: nonetheless\n", [], _stub(True), _ROW2),
    ("bugfix #37 with the label, lookup says yes",
     "Spec-PR: none\nSpec-PR-reason: bugfix: #37\n", ["bugfix"], _stub(True), None),
    ("bugfix #37 with the label, lookup says no (not an issue here)",
     "Spec-PR: none\nSpec-PR-reason: bugfix: #37\n", ["bugfix"], _stub(False), _ROW10),
    ("bugfix #999999 with the label, lookup says no",
     "Spec-PR: none\nSpec-PR-reason: bugfix: #999999\n", ["bugfix"], _stub(False), _ROW10),
    ("bugfix #49 (a pull request) with the label, lookup says no",
     "Spec-PR: none\nSpec-PR-reason: bugfix: #49\n", ["bugfix"], _stub(False), _ROW10),
    ("bugfix without the label (row 8 first, lookup never reached)",
     "Spec-PR: none\nSpec-PR-reason: bugfix: #37\n", [], _stub(False), _ROW8),
    ("bugfix with both labels (row 9 first, lookup never reached)",
     "Spec-PR: none\nSpec-PR-reason: bugfix: #37\n", ["bugfix", "refactor"], _stub(False), _ROW9),
    ("refactor path, lookup stub says no (never called)",
     "Spec-PR: none\nSpec-PR-reason: refactor\n", ["refactor"], _stub(False), None),
    ("numbered form, lookup stub says no (never called)", "Spec-PR: #12\n", ["bugfix"], _stub(False), None),
    ("numbered, no labels", "Spec-PR: #12\n", [], _stub(True), None),
    ("numbered, refactor label alone", "Spec-PR: #12\n", ["refactor"], _stub(True), None),
    ("numbered, both labels", "Spec-PR: #12\n", ["refactor", "bugfix"], _stub(True), None),
    ("numbered + second number", "Spec-PR: #12\nSpec-PR: #13\n", [], _stub(True), None),
    ("numbered + TBD", "Spec-PR: #12\nSpec-PR: TBD\n", [], _stub(True), None),
    ("numbered + reason line", "Spec-PR: #12\nSpec-PR-reason: refactor\n", ["refactor"], _stub(True), _ROW2),
    ("no Spec-PR line", "Just a description.\n", ["refactor"], _stub(True), _ROW3),
    ("TBD alone", "Spec-PR: TBD\n", [], _stub(True), _ROW3),
    ("empty value", "Spec-PR:\n", [], _stub(True), _ROW3),
    ("'none because' alone", "Spec-PR: none because x\nSpec-PR-reason: refactor\n", ["refactor"], _stub(True), _ROW4),
    ("two none lines",
     "Spec-PR: none\nSpec-PR: none\nSpec-PR-reason: refactor\n", ["refactor"], _stub(True), _ROW4),
    ("CR injection in the none value",
     "Spec-PR: none\r::warning::x\nSpec-PR-reason: refactor\n", ["refactor"], _stub(True), _ROW4),
    ("none alone", "Spec-PR: none\n", ["refactor"], _stub(True), _ROW5),
    ("two identical reasons",
     "Spec-PR: none\nSpec-PR-reason: refactor\nSpec-PR-reason: refactor\n", ["refactor"], _stub(True), _ROW6),
    ("two different reasons",
     "Spec-PR: none\nSpec-PR-reason: refactor\nSpec-PR-reason: bugfix: #1\n", ["refactor"], _stub(True), _ROW6),
    ("malformed 'refactoring'", "Spec-PR: none\nSpec-PR-reason: refactoring\n", ["refactor"], _stub(True), _ROW7),
    ("malformed 'bugfix'", "Spec-PR: none\nSpec-PR-reason: bugfix\n", ["bugfix"], _stub(True), _ROW7),
    ("malformed 'bugfix: 12'", "Spec-PR: none\nSpec-PR-reason: bugfix: 12\n", ["bugfix"], _stub(True), _ROW7),
    ("malformed 'bugfix: #'", "Spec-PR: none\nSpec-PR-reason: bugfix: #\n", ["bugfix"], _stub(True), _ROW7),
    ("malformed 'refactor of the graph'",
     "Spec-PR: none\nSpec-PR-reason: refactor of the graph\n", ["refactor"], _stub(True), _ROW7),
    ("reason, no labels", "Spec-PR: none\nSpec-PR-reason: refactor\n", [], _stub(True), _ROW8),
    ("refactor + label bugfix only", "Spec-PR: none\nSpec-PR-reason: refactor\n", ["bugfix"], _stub(True), _ROW8),
    ("bugfix + label refactor only", "Spec-PR: none\nSpec-PR-reason: bugfix: #12\n", ["refactor"], _stub(True), _ROW8),
    ("refactor + both labels",
     "Spec-PR: none\nSpec-PR-reason: refactor\n", ["refactor", "bugfix"], _stub(True), _ROW9),
    ("bugfix #999999 + label, lookup stub says yes (form is the rule's business)",
     "Spec-PR: none\nSpec-PR-reason: bugfix: #999999\n", ["bugfix"], _stub(True), None),
    ("case variants", "spec-pr: NONE\nSPEC-PR-REASON: Refactor\n", ["Refactor"], _stub(True), None),
    ("extra blanks", "Spec-PR:   none   \nSpec-PR-reason:\tbugfix:  #7 \n", ["bugfix"], _stub(True), None),
]


@pytest.mark.parametrize("title,body,labels,issue_exists,expected", SPEC_PR_RULE_CASES,
                          ids=[case[0] for case in SPEC_PR_RULE_CASES])
def test_spec_pr_rule_problems_matrix(title, body, labels, issue_exists, expected):
    problems = ct.spec_pr_rule_problems(body, labels, issue_exists)
    if expected is None:
        assert problems == [], title
        return
    assert len(problems) == 1, (title, problems)
    message = problems[0]
    assert expected in message, (title, message)
    assert message.endswith(ct._ACCEPTED_FORMS), (title, message)
    assert "\r" not in message, (title, message)   # a raw CR could start a runner log line; repr() escapes it
    assert (ct._HINT in message) == (expected in _HINT_ROWS), (title, message)


def test_row_10_message_names_the_issue_number():
    problems = ct.spec_pr_rule_problems("Spec-PR: none\nSpec-PR-reason: bugfix: #37\n", ["bugfix"], _stub(False))
    assert len(problems) == 1
    assert "37" in problems[0]


def test_cr_injection_shows_the_escaped_literal_not_a_raw_cr():
    problems = ct.spec_pr_rule_problems("Spec-PR: none\r::warning::x\nSpec-PR-reason: refactor\n",
                                        ["refactor"], _stub(True))
    assert len(problems) == 1
    assert "\\r" in problems[0]          # the two literal characters backslash + r, from repr()
    assert "::warning::x" in problems[0]   # repr() does not escape ordinary printable characters


def test_issue_lookup_called_exactly_once_on_the_row_11_bugfix_pass():
    stub = _counting_stub(True)
    problems = ct.spec_pr_rule_problems("Spec-PR: none\nSpec-PR-reason: bugfix: #37\n", ["bugfix"], stub)
    assert problems == []
    assert stub.calls == ["37"]


@pytest.mark.parametrize("body,labels", [
    ("Spec-PR: none\nSpec-PR-reason: refactor\n", ["refactor"]),                     # refactor path: never bugfix
    ("Spec-PR: none\nSpec-PR-reason: bugfix: #37\n", []),                            # row 8 first: no label
    ("Spec-PR: none\nSpec-PR-reason: bugfix: #37\n", ["bugfix", "refactor"]),        # row 9 first: both labels
    ("Spec-PR: none\nSpec-PR-reason: bugfix: 12\n", ["bugfix"]),                     # row 7 first: malformed number
    ("Spec-PR: #12\n", ["bugfix"]),                                                  # the numbered form
], ids=["refactor-path", "bugfix-no-label", "bugfix-both-labels", "bugfix-malformed", "numbered-form"])
def test_issue_lookup_never_called_off_the_bugfix_path_or_before_rows_1_to_9_decide(body, labels):
    stub = _counting_stub(True)
    ct.spec_pr_rule_problems(body, labels, stub)
    assert stub.calls == []


PARSE_PR_STATE_CASES = [
    ('{"body": "Spec-PR: none", "labels": [{"name": "refactor", "color": "x"}]}', ("Spec-PR: none", ["refactor"])),
    ('{"labels": [{"name": "refactor"}]}', ("", ["refactor"])),
    ('{"body": 5, "labels": []}', ("", [])),
    ('{"body": "b", "labels": [{"name": 1}]}', ("b", [])),
    ('{"body": "b", "labels": ["refactor"]}', ("b", [])),
    ('{"body": "b", "labels": "refactor"}', ("b", [])),
    (None, ("", [])),
    ("", ("", [])),
    ("not json", ("", [])),
    ("[1, 2]", ("", [])),
]


@pytest.mark.parametrize("raw,expected", PARSE_PR_STATE_CASES)
def test_parse_pr_state(raw, expected):
    assert ct.parse_pr_state(raw) == expected


_REPO = "yorkzhangyong-bot/kestrel"
_ISSUE_JSON = ('{"number": 37, "state": "closed", '
               '"repository_url": "https://api.github.com/repos/yorkzhangyong-bot/kestrel"}')

PARSE_ISSUE_LOOKUP_CASES = [
    (_ISSUE_JSON, _REPO, "37", True),
    (_ISSUE_JSON.replace('"closed"', '"open"'), _REPO, "37", True),
    (_ISSUE_JSON.replace("yorkzhangyong-bot/kestrel", "YorkZhangYong-Bot/Kestrel"), _REPO, "37", True),
    (_ISSUE_JSON.replace('"state"', '"pull_request": {"url": "x"}, "state"'), _REPO, "37", False),
    (_ISSUE_JSON.replace("yorkzhangyong-bot/kestrel", "someone-else/kestrel"), _REPO, "37", False),
    (_ISSUE_JSON, _REPO, "38", False),
    ('{"number": 37, "state": "open"}', _REPO, "37", False),
    ('{"state": "open", "repository_url": "https://api.github.com/repos/yorkzhangyong-bot/kestrel"}',
     _REPO, "37", False),   # missing "number" entirely
    ("[1, 2]", _REPO, "37", False),
    ("not json", _REPO, "37", False),
    (None, _REPO, "37", False),
    ("", _REPO, "37", False),
]


@pytest.mark.parametrize("raw,repository,number,expected", PARSE_ISSUE_LOOKUP_CASES)
def test_parse_issue_lookup(raw, repository, number, expected):
    assert ct.parse_issue_lookup(raw, repository, number) is expected


def test_parse_issue_lookup_fails_closed_on_a_number_past_pythons_int_conversion_limit():
    # Review finding 10: int(number) raises ValueError past ~4,300 digits; caught so the row-10 path still
    # reports cleanly instead of an uncaught traceback.
    huge = "9" * 5000
    assert ct.parse_issue_lookup(_ISSUE_JSON, _REPO, huge) is False


def test_spec_pr_line_re_is_linear_on_a_long_padded_line():
    # Review finding 10: the old `(.*?)[ \t\r]*$` pattern was quadratic; a 65,000-character padded value must
    # finish quickly, not in tens of seconds.
    body = "Spec-PR: x" + " " * 65_000 + "y\n"
    start = time.monotonic()
    ct.spec_pr_rule_problems(body, [], _stub(True))
    assert time.monotonic() - start < 2.0


class _Done:
    def __init__(self, returncode: int, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout


def _raise(exc):
    def run(*args, **kwargs):
        raise exc
    return run


def test_pr_state_with_no_pr_number_is_empty_and_never_calls_gh(monkeypatch, capsys):
    monkeypatch.delenv("PR_NUMBER", raising=False)
    calls: list[int] = []
    monkeypatch.setattr(ct.subprocess, "run", lambda *a, **k: (calls.append(1), _Done(0, "{}"))[1])
    assert ct.pr_state() == ("", [])
    assert calls == []
    assert "PR_NUMBER" in capsys.readouterr().out


def test_pr_state_non_zero_gh_exit_is_empty_and_leaks_no_body(monkeypatch, capsys):
    monkeypatch.setenv("PR_NUMBER", "5")
    monkeypatch.setattr(ct.subprocess, "run", lambda *a, **k: _Done(1, "Spec-PR: none SECRET-BODY-VALUE"))
    assert ct.pr_state() == ("", [])
    assert "SECRET-BODY-VALUE" not in capsys.readouterr().out


def test_pr_state_timeout_is_empty(monkeypatch, capsys):
    monkeypatch.setenv("PR_NUMBER", "5")
    monkeypatch.setattr(ct.subprocess, "run", _raise(ct.subprocess.TimeoutExpired(cmd="gh", timeout=30)))
    assert ct.pr_state() == ("", [])
    out = capsys.readouterr().out
    assert "TimeoutExpired" in out
    assert "5" not in out   # PR_NUMBER itself is never echoed into the notice


def test_pr_state_no_gh_on_path_is_empty(monkeypatch, capsys):
    monkeypatch.setenv("PR_NUMBER", "5")
    monkeypatch.setattr(ct.subprocess, "run", _raise(FileNotFoundError("gh")))
    assert ct.pr_state() == ("", [])
    out = capsys.readouterr().out
    assert "FileNotFoundError" in out
    assert "5" not in out


def test_pr_state_success_parses_stdout(monkeypatch):
    monkeypatch.setenv("PR_NUMBER", "5")
    monkeypatch.setenv("GITHUB_REPOSITORY", _REPO)
    calls = []
    monkeypatch.setattr(ct.subprocess, "run", lambda argv, **kwargs: (calls.append((argv, kwargs)), _Done(
        0, '{"body": "Spec-PR: none", "labels": [{"name": "refactor"}]}'))[1])
    assert ct.pr_state() == ("Spec-PR: none", ["refactor"])
    argv, kwargs = calls[0]
    assert argv == ["gh", "pr", "view", "5", "--repo", _REPO, "--json", "body,labels"]
    assert kwargs["timeout"] == 30


def test_issue_exists_in_repo_non_zero_gh_exit_is_false_and_leaks_no_body(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_REPOSITORY", _REPO)
    monkeypatch.setattr(ct.subprocess, "run", lambda *a, **k: _Done(1, "Spec-PR: none SECRET-BODY-VALUE"))
    assert ct.issue_exists_in_repo("37") is False
    out = capsys.readouterr().out
    assert "SECRET-BODY-VALUE" not in out
    assert "37" in out


def test_issue_exists_in_repo_timeout_is_false(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_REPOSITORY", _REPO)
    monkeypatch.setattr(ct.subprocess, "run", _raise(ct.subprocess.TimeoutExpired(cmd="gh", timeout=30)))
    assert ct.issue_exists_in_repo("37") is False
    out = capsys.readouterr().out
    assert "TimeoutExpired" in out
    assert "37" in out


def test_issue_exists_in_repo_no_gh_on_path_is_false(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_REPOSITORY", _REPO)
    monkeypatch.setattr(ct.subprocess, "run", _raise(FileNotFoundError("gh")))
    assert ct.issue_exists_in_repo("37") is False
    out = capsys.readouterr().out
    assert "FileNotFoundError" in out
    assert "37" in out


def test_issue_exists_in_repo_invalid_json_is_false(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", _REPO)
    monkeypatch.setattr(ct.subprocess, "run", lambda *a, **k: _Done(0, "not json"))
    assert ct.issue_exists_in_repo("37") is False


def test_issue_exists_in_repo_success_parses_stdout(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", _REPO)
    calls = []
    monkeypatch.setattr(ct.subprocess, "run",
                        lambda argv, **kwargs: (calls.append((argv, kwargs)), _Done(0, _ISSUE_JSON))[1])
    assert ct.issue_exists_in_repo("37") is True
    argv, kwargs = calls[0]
    assert argv == ["gh", "api", f"repos/{_REPO}/issues/37"]
    assert kwargs["timeout"] == 30


def test_issue_exists_in_repo_success_but_a_pull_request_is_false(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", _REPO)
    body = _ISSUE_JSON.replace('"state"', '"pull_request": {}, "state"')
    monkeypatch.setattr(ct.subprocess, "run", lambda *a, **k: _Done(0, body))
    assert ct.issue_exists_in_repo("37") is False


_HONEST = "Spec-PR: none\nSpec-PR-reason: refactor\n"

WIRING_CASES = [
    (["src/kestrel/x.py"], _HONEST, ["refactor"], []),
    (["src/kestrel/x.py"], _HONEST, [], [_ROW8]),
    (["tests/unit/t.py"], "Spec-PR: none\n", [], []),
    (["src/kestrel/x.py", "specs/006-x/spec.md"], _HONEST, ["refactor"], ["spec-change"]),
    (["src/kestrel/x.py", "specs/006-x/spec.md"], _HONEST + "<!-- spec-change: hidden -->\n",
     ["refactor"], ["spec-change"]),
    (["src/kestrel/x.py", "specs/006-x/spec.md"], _HONEST + "<!--\nspec-change: in a comment\n-->\n",
     ["refactor"], []),
    (["src/kestrel/x.py", "specs/006-x/spec.md"], _HONEST + "spec-change: visible\n", ["refactor"], []),
    ([], None, [], []),
]


def _tags(problems: list[str]) -> list[str]:
    return [next((row for row in _ALL_ROWS if row in p), "spec-change") for p in problems]


@pytest.mark.parametrize("files,body,labels,expected_tags", WIRING_CASES)
def test_pr_rule_problems_wiring(files, body, labels, expected_tags):
    problems = ct.pr_rule_problems(files, body, labels, _stub(True))
    assert _tags(problems) == expected_tags
