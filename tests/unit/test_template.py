import json

import pytest

from kestrel.connection.template import TemplateError, build_request, validate

DEFAULT = '{"message": "{{prompt}}"}'


def field_of(method, url, template):
    with pytest.raises(TemplateError) as info:
        validate(method, url, template)
    return info.value.field


def test_default_post_template_is_valid():
    validate("POST", "http://h/chat", DEFAULT)


@pytest.mark.parametrize("template", ['{"message": "hi"}', '{"a": "{{prompt}}", "b": "{{prompt}}"}'])
def test_post_needs_exactly_one_placeholder(template):
    assert field_of("POST", "http://h/chat", template) == "settings.body_template"


@pytest.mark.parametrize("template", ['{"m": {{prompt}}}', '{"{{prompt}}": "x"}'])
def test_post_placeholder_must_sit_inside_a_string_value(template):
    assert field_of("POST", "http://h/chat", template) == "settings.body_template"


def test_post_template_must_be_valid_json():
    assert field_of("POST", "http://h/chat", '{"m": "{{prompt}}"') == "settings.body_template"


def test_post_placeholder_in_the_url_is_refused():
    assert field_of("POST", "http://h/chat?q={{prompt}}", DEFAULT) == "settings.url"


def test_get_with_one_placeholder_in_the_query_is_valid_and_ignores_the_template():
    validate("GET", "http://h/chat?q={{prompt}}", "not json at all")


@pytest.mark.parametrize("url", ["http://h/chat", "http://h/chat?q={{prompt}}&r={{prompt}}",
                                 "http://h/{{prompt}}/chat", "http://h/chat#{{prompt}}"])
def test_get_needs_exactly_one_placeholder_in_the_query_string(url):
    assert field_of("GET", url, DEFAULT) == "settings.url"


@pytest.mark.parametrize("prompt", ['say "hi"', "back\\slash", "line\nbreak", "{{ and }}", "漢字 ü", "Hello"])
def test_post_body_is_valid_json_whatever_the_prompt(prompt):
    url, body = build_request("POST", "http://h/chat", DEFAULT, prompt)
    assert url == "http://h/chat"
    assert json.loads(body.decode("utf-8")) == {"message": prompt}


def test_placeholder_inside_a_longer_string_and_nested_values():
    template = '{"messages": [{"role": "user", "content": "Q: {{prompt}}"}], "n": 1}'
    _, body = build_request("POST", "http://h/chat", template, 'say "hi"')
    assert json.loads(body) == {"messages": [{"role": "user", "content": 'Q: say "hi"'}], "n": 1}


def test_get_percent_encodes_the_prompt_and_sends_no_body():
    url, body = build_request("GET", "http://h/chat?q={{prompt}}&lang=en", DEFAULT, "a b&c=d/é")
    assert body is None
    assert url == "http://h/chat?q=a%20b%26c%3Dd%2F%C3%A9&lang=en"
