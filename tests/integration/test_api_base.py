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
    import dataclasses
    settings = dataclasses.replace(hosted_settings, api_token="hosted-token")  # hosted is fail-closed without a token
    response = make_client(settings).get("/api/config", headers={"X-Kestrel-Token": "hosted-token"})
    assert response.json()["mode"] == "hosted"


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


# ---- feature 011: the config reports the retrieval controls (011/FR-012) ----


def test_config_reports_the_retrieval_controls_defaults(client):  # 011/FR-012
    experience = client.get("/api/config").json()["experience"]
    assert experience["pattern_k"] == 5 and experience["memory_cap"] == 10
    assert experience["distance_floor"] == 1.8 and experience["dedupe_threshold"] == 0.15


def test_config_reports_a_control_switched_off_as_null(make_client, settings):  # 011/FR-012
    import dataclasses
    off = dataclasses.replace(settings, experience_distance_floor=None, experience_dedupe_threshold=None)
    experience = make_client(off).get("/api/config").json()["experience"]
    assert experience["distance_floor"] is None and experience["dedupe_threshold"] is None
    one_off = dataclasses.replace(settings, experience_dedupe_threshold=None)
    experience = make_client(one_off).get("/api/config").json()["experience"]
    assert experience["distance_floor"] == 1.8 and experience["dedupe_threshold"] is None
