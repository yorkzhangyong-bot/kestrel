import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from kestrel.api.main import create_app
from kestrel.settings import SettingsError

DEFAULTS = {"method": "POST", "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply"}


def test_config_returns_mode_and_defaults(client):
    response = client.get("/api/config")
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "local"
    assert body["defaults"] == DEFAULTS


def test_config_reports_hosted_mode(make_client, hosted_settings):
    assert make_client(hosted_settings).get("/api/config").json()["mode"] == "hosted"


class _Probe(BaseModel):
    url: str
    headers: list[dict]


def _probe_client(settings) -> TestClient:
    app = create_app(settings)

    @app.post("/_probe")
    def probe(body: _Probe) -> dict:
        return {}

    return TestClient(app)


def test_validation_errors_name_the_field_and_never_echo_input(settings):
    with _probe_client(settings) as client:
        response = client.post("/_probe", json={"headers": [{"name": "X", "value": "s3cret-value-123"}]})
    assert response.status_code == 422
    assert "s3cret-value-123" not in response.text
    assert response.json() == {"errors": [{"field": "url", "message": "Field required"}]}


def test_malformed_json_gets_the_same_error_shape(settings):
    with _probe_client(settings) as client:
        response = client.post("/_probe", content=b'{"url": "s3cret-value-123", oops',
                               headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert "s3cret-value-123" not in response.text
    assert response.json() == {"errors": [{"field": "body", "message": "The request body isn't valid JSON."}]}


def test_invalid_mode_in_the_environment_stops_create_app(monkeypatch):
    monkeypatch.setenv("KESTREL_MODE", "dev")
    with pytest.raises(SettingsError, match="KESTREL_MODE"):
        create_app()
