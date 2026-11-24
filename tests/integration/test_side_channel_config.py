"""Registering a cooperating target's side channel (013/FR-019, FR-020, FR-021, FR-022, FR-071, SC-008; US4).

Through the API, with the offline `ModelTransport` answering the stub target and the scripted side channel: the
header value is stored encrypted and never returned; the connection test checks the side channel only after the
chat test passes and reports each of the six named steps with its exact message - the timeout one carrying the
configured timeout the API substitutes, asserted at two different values so the number is provably not fixed in
the text; a save is refused until a test with exactly these side-channel settings passed; a target without a side
channel sends exactly today's requests and no correlation header; and the decrypted side-channel header value
joins the run's mask list beside the target's own. Placeholder messages only; no attack text."""
from __future__ import annotations

import dataclasses
import sqlite3
import uuid

import pytest

from kestrel.secrets import MASK
from kestrel.settings import Settings
from tests.support import SECRET, SIDE_CHANNEL_URL, TARGET_URL, StubJudge, fixture_library

FEATURE = "013"

SIDE_SECRET = "side-channel-secret-9c2e"
HONEYPOT = "approve_duty_refund"
CORRELATION_HEADER = "X-Kestrel-Correlation-Id"
TIMEOUT_MESSAGE = "The side channel didn't answer within {n} seconds."
UNREADABLE_MESSAGE = ("The stored side-channel auth header can't be read with the current encryption key. Re-enter "
                      "it, or restore the old key.")
PRIVATE_MESSAGE = ("The side-channel address is on a local or private network. Such addresses only work when "
                   "Kestrel runs on your own machine.")


def connection(**changes) -> dict:
    base = {"url": TARGET_URL, "method": "POST", "headers": [{"name": "X-API-Key", "value": SECRET}],
            "body_template": '{"message": "{{prompt}}"}', "response_path": "$.reply"}
    return {**base, **changes}


def side_channel(**changes) -> dict:
    base = {"url": SIDE_CHANNEL_URL, "header": {"name": "X-Side-Key", "value": SIDE_SECRET},
            "honeypot_tool": HONEYPOT}
    return {**base, **changes}


def request_body(form_id: str, *, target_id: int | None = None, **changes) -> dict:
    return {"form_id": form_id, "target_id": target_id, "display_name": "Agent", "settings": connection(**changes)}


def save_body(api, form_id: str, *, name: str = "HS Agent", **changes) -> dict:
    terms = api.get("/api/config", headers=api.headers).json()["terms"]["version"]
    return {"form_id": form_id, "name": name, "settings": connection(**changes), "permission_confirmed": True,
            "terms_version": terms, "canaries": ["KESTREL-CANARY-7Q4M2X"]}


@pytest.fixture
def api(make_client, model_transport):
    """A client over the offline transport; the stub side channel insists on the configured header."""
    model_transport.side_channel.expected_header = ("X-Side-Key", SIDE_SECRET)
    client = make_client(transport=model_transport.transport, library=fixture_library(),
                         judge=StubJudge(verdict="failed"))
    client.headers = {}
    return client


def tested(api, **changes) -> str:
    """A passing connection test with these settings; returns its form id."""
    form_id = str(uuid.uuid4())
    body = api.post("/api/connection-tests", json=request_body(form_id, **changes), headers=api.headers).json()
    assert body["ok"] is True, body
    return form_id


def register(api, **changes) -> dict:
    """Test, then save, a target with these settings; returns the saved detail."""
    form_id = tested(api, **changes)
    response = api.post("/api/targets", json=save_body(api, form_id, **changes), headers=api.headers)
    assert response.status_code == 201, response.text
    return response.json()


# ---- registering and reading back (FR-019, FR-021) ----


def test_a_side_channel_is_tested_saved_and_read_back_without_its_value(api, model_transport, settings):
    # FR-019, FR-021
    form_id = str(uuid.uuid4())
    result = api.post("/api/connection-tests", json=request_body(form_id, side_channel=side_channel())).json()
    assert result["ok"] is True and result["step"] == "success" and result["message"] == "Connection works."
    assert result["side_channel_checked"] is True
    [describe] = model_transport.side_channel_requests()
    assert describe.url.path.endswith("/describe") and describe.method == "GET"
    assert describe.headers["X-Side-Key"] == SIDE_SECRET          # the configured header went with the request
    assert describe.headers["User-Agent"] == "Kestrel/0.1 (side channel)"

    saved = api.post("/api/targets", json=save_body(api, form_id, side_channel=side_channel()))
    assert saved.status_code == 201, saved.text
    detail = saved.json()
    assert detail["side_channel"] == {"url": SIDE_CHANNEL_URL, "header_name": "X-Side-Key", "has_value": True,
                                      "readable": True, "honeypot_tool": HONEYPOT}
    assert api.get(f"/api/targets/{detail['id']}").json()["side_channel"] == detail["side_channel"]
    assert SIDE_SECRET not in saved.text and SIDE_SECRET not in api.get("/api/targets").text

    # Stored encrypted (the vault), decrypted only for the tester and the checker.
    store = api.app.state.store
    resolved = store.resolve_side_channel(detail["id"])
    assert resolved.url == SIDE_CHANNEL_URL and resolved.header == ("X-Side-Key", SIDE_SECRET)
    assert resolved.honeypot_tool == HONEYPOT and SIDE_SECRET not in repr(resolved)
    with sqlite3.connect(settings.db_path) as db:
        [(stored_value,)] = db.execute("SELECT header_value_encrypted FROM target_side_channels").fetchall()
    assert stored_value and SIDE_SECRET not in stored_value


def test_a_side_channel_without_a_header_or_honeypot_is_fine(api, model_transport):  # FR-019, FR-025
    model_transport.side_channel.expected_header = None
    detail = register(api, side_channel={"url": SIDE_CHANNEL_URL})
    assert detail["side_channel"] == {"url": SIDE_CHANNEL_URL, "header_name": None, "has_value": False,
                                      "readable": True, "honeypot_tool": None}
    resolved = api.app.state.store.resolve_side_channel(detail["id"])
    assert resolved.header is None and resolved.honeypot_tool is None


def test_a_chat_only_test_does_not_cover_a_save_with_a_side_channel(api):  # FR-021
    form_id = tested(api)                                                   # no side channel in the test
    refused = api.post("/api/targets", json=save_body(api, form_id, side_channel=side_channel()))
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "not_tested"
    form_id = tested(api, side_channel=side_channel())
    assert api.post("/api/targets", json=save_body(api, form_id, side_channel=side_channel())).status_code == 201


def test_a_target_without_a_side_channel_reads_back_none(api):  # FR-019, SC-008
    detail = register(api)
    assert detail["side_channel"] is None
    assert api.app.state.store.resolve_side_channel(detail["id"]) is None


# ---- updating (FR-019) ----


def test_update_keeps_the_stored_header_value_for_null_and_removes_the_side_channel_for_null(api, model_transport):
    # FR-019
    detail = register(api, side_channel=side_channel())
    kept = side_channel(header={"name": "X-Side-Key", "value": None})      # keep the stored value
    form_id = str(uuid.uuid4())
    model_transport.requests.clear()
    result = api.post("/api/connection-tests", json=request_body(form_id, target_id=detail["id"], side_channel=kept)).json()
    assert result["ok"] is True and result["side_channel_checked"] is True
    [describe] = model_transport.side_channel_requests()
    assert describe.headers["X-Side-Key"] == SIDE_SECRET                  # the kept value was the one sent
    updated = api.put(f"/api/targets/{detail['id']}", json=save_body(api, form_id, name="Renamed", side_channel=kept))
    assert updated.status_code == 200, updated.text
    assert updated.json()["side_channel"]["has_value"] is True
    assert api.app.state.store.resolve_side_channel(detail["id"]).header == ("X-Side-Key", SIDE_SECRET)

    form_id = tested(api, target_id=detail["id"])                          # a test without the side channel
    removed = api.put(f"/api/targets/{detail['id']}", json=save_body(api, form_id, side_channel=None))
    assert removed.status_code == 200 and removed.json()["side_channel"] is None
    assert api.app.state.store.resolve_side_channel(detail["id"]) is None
    assert api.app.state.store.get_target(detail["id"]).side_channel is None


def test_a_null_header_value_needs_a_stored_side_channel_value(api):  # FR-019
    form_id = str(uuid.uuid4())
    body = request_body(form_id, side_channel=side_channel(header={"name": "X-Side-Key", "value": None}))
    response = api.post("/api/connection-tests", json=body)
    assert response.status_code == 422
    assert {e["field"]: e["message"] for e in response.json()["errors"]} == {
        "settings.side_channel.header.value": "Enter a value for this header."}


# ---- the six named failures (FR-021, FR-071) ----


@pytest.mark.parametrize("failure, step, message", [
    ("unreachable", "side_channel_unreachable", "Kestrel couldn't connect to the side-channel URL."),
    ("unauthorized", "side_channel_auth_rejected",
     "The side channel refused the request as unauthorized. Check its auth header."),
    ("timeout", "side_channel_timed_out", TIMEOUT_MESSAGE.format(n=10)),
    ("invalid_shape", "side_channel_invalid", "The side channel answered, but not with the shape Kestrel expects."),
    ("non_json", "side_channel_invalid", "The side channel answered, but not with the shape Kestrel expects."),
    ("error_status", "side_channel_invalid", "The side channel answered, but not with the shape Kestrel expects."),
])
def test_each_failure_names_its_step_and_exact_message(api, model_transport, failure, step, message):  # FR-021
    model_transport.side_channel.failure = failure
    form_id = str(uuid.uuid4())
    result = api.post("/api/connection-tests", json=request_body(form_id, side_channel=side_channel())).json()
    assert result["ok"] is False and result["step"] == step and result["message"] == message
    assert result["side_channel_checked"] is False
    assert len(model_transport.target_requests()) == 1              # the chat test ran first, and passed
    # No save with these settings until a test passes (FR-021).
    refused = api.post("/api/targets", json=save_body(api, form_id, side_channel=side_channel()))
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "not_tested"


@pytest.mark.parametrize("timeout_s", [3, 7])
def test_the_timeout_message_carries_the_configured_timeout(make_client, settings, model_transport, timeout_s):
    # FR-021
    model_transport.side_channel.expected_header = ("X-Side-Key", SIDE_SECRET)
    model_transport.side_channel.failure = "timeout"
    client = make_client(dataclasses.replace(settings, side_channel_timeout_s=timeout_s),
                         transport=model_transport.transport, library=fixture_library())
    result = client.post("/api/connection-tests", json=request_body(str(uuid.uuid4()), side_channel=side_channel())).json()
    assert result["step"] == "side_channel_timed_out"
    assert result["message"] == TIMEOUT_MESSAGE.format(n=timeout_s)
    assert client.get("/api/config").json()["evidence"]["side_channel_timeout_s"] == timeout_s


def test_the_side_channel_is_checked_only_after_the_chat_test_passes(api, model_transport):  # FR-021
    model_transport.target_status = 500
    result = api.post("/api/connection-tests", json=request_body(str(uuid.uuid4()), side_channel=side_channel())).json()
    assert result["ok"] is False and result["step"] == "endpoint_error"
    assert model_transport.side_channel_requests() == []           # nothing asked of the side channel
    assert "side_channel_checked" not in result or result["side_channel_checked"] is False


def test_a_stored_header_the_key_cannot_read_refuses_the_test_without_sending(make_client, settings, tmp_path,
                                                                             model_transport):  # FR-021, FR-071
    model_transport.side_channel.expected_header = ("X-Side-Key", SIDE_SECRET)
    first = make_client(transport=model_transport.transport, library=fixture_library())
    first.headers = {}
    detail = register(first, headers=[], side_channel=side_channel())   # the target itself needs no auth header

    other_key = Settings(mode="local", db_path=settings.db_path, key_file=tmp_path / "other.key", secret_key=None,
                         chroma_path=settings.chroma_path)
    client = make_client(other_key, transport=model_transport.transport, library=fixture_library())
    assert client.get(f"/api/targets/{detail['id']}").json()["side_channel"]["readable"] is False
    model_transport.requests.clear()
    kept = side_channel(header={"name": "X-Side-Key", "value": None})
    result = client.post("/api/connection-tests",
                         json=request_body(str(uuid.uuid4()), target_id=detail["id"], headers=[], side_channel=kept)).json()
    assert result["ok"] is False and result["step"] == "side_channel_header_unreadable"
    assert result["message"] == UNREADABLE_MESSAGE
    assert model_transport.side_channel_requests() == []           # no request without the header (FR-071)


def test_hosted_mode_refuses_a_private_side_channel_address_before_sending(make_client, hosted_settings,
                                                                            model_transport):  # FR-020, FR-021
    settings = dataclasses.replace(hosted_settings, api_token="hosted-token")
    private = {"sidechannel.kestrel.test": ["10.0.0.5"]}
    client = make_client(settings, transport=model_transport.transport, library=fixture_library(),
                         resolver=lambda host: private.get(host, ["93.184.216.34"]))
    token = {"X-Kestrel-Token": "hosted-token"}
    result = client.post("/api/connection-tests", json=request_body(str(uuid.uuid4()), side_channel=side_channel()),
                         headers=token).json()
    assert result["ok"] is False and result["step"] == "side_channel_address_not_allowed"
    assert result["message"] == PRIVATE_MESSAGE
    assert model_transport.side_channel_requests() == []


# ---- validation (FR-020, FR-022, FR-041) ----


@pytest.mark.parametrize("changes, field", [
    ({"url": "not a url"}, "settings.side_channel.url"),
    ({"url": "http://user:pw@sidechannel.kestrel.test/side-channel"}, "settings.side_channel.url"),
    ({"header": {"name": "Bad Name", "value": SIDE_SECRET}}, "settings.side_channel.header.name"),
    ({"header": {"name": "X-Side-Key", "value": "abc"}}, "settings.side_channel.header.value"),
    ({"honeypot_tool": "no spaces allowed"}, "settings.side_channel.honeypot_tool"),
    ({"honeypot_tool": "x" * 101}, "settings.side_channel.honeypot_tool"),
])
def test_invalid_side_channel_settings_name_their_field(api, model_transport, changes, field):  # FR-020, FR-041
    response = api.post("/api/connection-tests",
                        json=request_body(str(uuid.uuid4()), side_channel=side_channel(**changes)))
    assert response.status_code == 422
    assert [e["field"] for e in response.json()["errors"]] == [field]
    assert SIDE_SECRET not in response.text
    assert model_transport.requests == []                           # nothing was sent anywhere


def test_the_correlation_header_is_refused_as_a_user_header(api):  # FR-022
    for name in (CORRELATION_HEADER, CORRELATION_HEADER.lower()):
        body = request_body(str(uuid.uuid4()), headers=[{"name": name, "value": "abcd1234"}])
        response = api.post("/api/connection-tests", json=body)
        assert response.status_code == 422
        assert response.json()["errors"] == [{"field": "settings.headers.0.name",
                                              "message": "Kestrel sets this header itself; remove it."}]


# ---- what a run sends (FR-022, FR-071, SC-008) ----


def run_once(api, target_id: int) -> dict:
    response = api.post("/api/runs", json={"target_id": target_id, "family": "system_prompt_leak",
                                           "prompt_id": "spl-001", "mode": "single_turn"})
    assert response.status_code == 201, response.text
    return response.json()


def test_a_target_without_a_side_channel_sends_exactly_todays_requests(api, model_transport):  # FR-022, SC-008
    detail = register(api)
    model_transport.requests.clear()
    run = run_once(api, detail["id"])
    [chat] = model_transport.target_requests()
    assert model_transport.side_channel_requests() == []
    assert CORRELATION_HEADER.lower() not in {name.lower() for name in chat.headers}
    assert set(chat.headers) >= {"x-api-key", "content-type", "user-agent"}
    assert run["side_channel_status"] == "not_configured"
    assert api.app.state.store.get_run(run["id"]).correlation_id is None


def test_a_target_with_a_side_channel_sends_the_correlation_header_and_reads_the_channel(api, model_transport):
    # FR-022
    detail = register(api, side_channel=side_channel())
    model_transport.requests.clear()
    run = run_once(api, detail["id"])
    [chat] = model_transport.target_requests()
    correlation_id = chat.headers[CORRELATION_HEADER]
    assert len(correlation_id) == 32 and all(c in "0123456789abcdef" for c in correlation_id)
    assert api.app.state.store.get_run(run["id"]).correlation_id == correlation_id
    assert run["side_channel_status"] == "checked"
    # Every side-channel request of the run carries the configured header (what it reads is US5's and US7's).
    assert all(r.headers["X-Side-Key"] == SIDE_SECRET for r in model_transport.side_channel_requests())
    # The correlation id is a different value on the next run (per run, FR-022).
    model_transport.requests.clear()
    assert model_transport.target_requests() == []
    second = run_once(api, detail["id"])
    assert api.app.state.store.get_run(second["id"]).correlation_id not in (None, correlation_id)


def test_the_side_channel_header_value_is_masked_out_of_a_reply(api, model_transport):  # FR-071
    model_transport.target_reply = f"the agent echoed {SIDE_SECRET} and {SECRET} back"
    detail = register(api, side_channel=side_channel())
    run = run_once(api, detail["id"])
    assert SIDE_SECRET not in run["reply_text"] and SECRET not in run["reply_text"]
    assert run["reply_text"].count(MASK) == 2
    assert SIDE_SECRET not in api.get(f"/api/runs/{run['id']}").text
