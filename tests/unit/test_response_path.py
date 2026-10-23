import pytest

from kestrel.connection.response_path import PathNotFound, PathSyntaxError, extract, parse


@pytest.mark.parametrize("path, steps", [
    ("$", []),
    ("$.reply", ["reply"]),
    ("$.choices[0].message.content", ["choices", 0, "message", "content"]),
    ("$.a.b[2][0]", ["a", "b", 2, 0]),
])
def test_valid_paths_parse(path, steps):
    assert parse(path) == steps


@pytest.mark.parametrize("path", ["reply", "$.", "$..a", "$.a[", "$.a[-1]", "$.a[x]", ""])
def test_invalid_paths_are_refused(path):
    with pytest.raises(PathSyntaxError):
        parse(path)


def test_extract_returns_the_matched_value():
    doc = {"choices": [{"message": {"content": "hi"}}], "n": 3}
    assert extract(doc, "$.choices[0].message.content") == "hi"
    assert extract(doc, "$.n") == 3
    assert extract(doc, "$") == doc


@pytest.mark.parametrize("path", ["$.missing", "$.choices[5]", "$.n.x", "$.choices[0].message.content.x", "$.n[0]"])
def test_extract_raises_path_not_found(path):
    doc = {"choices": [{"message": {"content": "hi"}}], "n": 3}
    with pytest.raises(PathNotFound):
        extract(doc, path)
