"""Kestrel's screen (contracts/ui-form.md). It only renders and calls the API; it never imports kestrel.

Text that comes from a target (reply_text, detail) is shown only with st.code, never as markdown (FR-007, SC-008);
st.success and st.error carry only Kestrel's own wording.
"""
from __future__ import annotations

import uuid

import streamlit as st

import api_client

MODE_CAPTIONS = {
    "local": "Running locally",
    "hosted": "Running hosted: local and private addresses are blocked",
}
METHODS = ["POST", "GET"]
FORM_FIELDS = {"settings.url", "settings.body_template", "settings.response_path"}


def api_message(error: api_client.ApiError) -> str:
    return (error.body.get("error") or {}).get("message") or "Kestrel's API answered with an error."


def load_config() -> dict | None:
    """Fetch /api/config once per session; a failure isn't cached, so the next run retries."""
    if "config" not in st.session_state:
        try:
            st.session_state["config"] = api_client.get_config()
        except api_client.ApiError as error:
            st.error(api_message(error))
            return None
    return st.session_state["config"]


# --- Header rows -----------------------------------------------------------------------------------------------

def header_rows() -> list[dict]:
    return st.session_state.setdefault("headers", [])


def sync_header_rows() -> None:
    """Copy the header widgets' current values into the rows."""
    for i, row in enumerate(header_rows()):
        row["name"] = st.session_state.get(f"header_name_{i}", row["name"])
        row["value"] = st.session_state.get(f"header_value_{i}", row["value"])


def reset_header_widgets() -> None:
    """Drop the header widgets' state, so they redraw from the rows after a row is added or removed."""
    for key in [k for k in st.session_state if str(k).startswith(("header_name_", "header_value_"))]:
        del st.session_state[key]


def add_header_row() -> None:
    sync_header_rows()
    header_rows().append({"name": "", "value": "", "stored": False})
    reset_header_widgets()


def remove_header_row(index: int) -> None:
    sync_header_rows()
    del header_rows()[index]
    reset_header_widgets()


# --- Test connection -------------------------------------------------------------------------------------------

def current_settings() -> dict:
    state = st.session_state
    headers = []
    for row in header_rows():
        name, value = row["name"].strip(), row["value"]
        if not name and not value and not row.get("stored"):
            continue  # an untouched empty row
        headers.append({"name": name, "value": None if row.get("stored") and value == "" else value})
    return {"url": (state.get("url") or "").strip(), "method": state.get("method") or "POST", "headers": headers,
            "body_template": state.get("body_template") or "", "response_path": (state.get("response_path") or "").strip()}


def start_test() -> None:
    """Button callback: capture the form now; the test runs on the next pass, with the button disabled."""
    sync_header_rows()
    st.session_state["pending_test"] = {
        "form_id": st.session_state["form_id"],
        "target_id": None,
        "display_name": (st.session_state.get("display_name") or "").strip(),
        "settings": current_settings(),
    }
    st.session_state["errors"] = {}
    st.session_state["notice"] = None


def run_pending_test() -> None:
    payload = st.session_state.get("pending_test")
    if payload is None:
        return
    try:
        with st.spinner("Testing the connection…"):
            st.session_state["result"] = api_client.test_connection(payload)
    except api_client.ApiError as error:
        st.session_state["result"] = None
        if error.status == 422:
            st.session_state["errors"] = {e["field"]: e["message"] for e in error.body.get("errors", [])}
        else:
            st.session_state["notice"] = api_message(error)
    finally:
        st.session_state["pending_test"] = None
    st.rerun()


# --- Rendering -------------------------------------------------------------------------------------------------

def show_error(field: str) -> None:
    message = st.session_state.get("errors", {}).get(field)
    if message:
        st.error(message)


def render_form(config: dict) -> None:
    defaults = config["defaults"]
    st.text_input("Display name", key="display_name", placeholder="My agent")

    method_col, url_col = st.columns([2, 5])
    method_col.selectbox("Method", METHODS, index=METHODS.index(defaults["method"]), key="method")
    url_col.text_input("Endpoint URL", key="url", placeholder="https://my-agent.example.com/chat")
    show_error("settings.url")

    st.markdown("**Auth headers**")
    st.caption("stored encrypted, never shown in report")
    for i, row in enumerate(header_rows()):
        name_col, value_col, remove_col = st.columns([4, 5, 3], vertical_alignment="bottom")
        name_col.text_input("Header name", value=row["name"], key=f"header_name_{i}", placeholder="Header name",
                            label_visibility="collapsed")
        value_col.text_input("Header value", value=row["value"], key=f"header_value_{i}", type="password",
                             placeholder="Stored · leave empty to keep" if row.get("stored") else "Value",
                             label_visibility="collapsed")
        remove_col.button("Remove", key=f"header_remove_{i}", on_click=remove_header_row, args=(i,))
        show_error(f"settings.headers.{i}.name")
        show_error(f"settings.headers.{i}.value")
    st.button("Add header", key="add_header", on_click=add_header_row)

    st.text_input("Request body template", value=defaults["body_template"], key="body_template")
    show_error("settings.body_template")
    st.text_input("Response path", value=defaults["response_path"], key="response_path")
    show_error("settings.response_path")

    st.button("Test connection", key="test_button", on_click=start_test,
              disabled=st.session_state.get("pending_test") is not None)


def render_result() -> None:
    st.subheader("Connection test")
    if st.session_state.get("notice"):
        st.warning(st.session_state["notice"])
    for field, message in st.session_state.get("errors", {}).items():
        if field not in FORM_FIELDS and not field.startswith("settings.headers."):
            st.error(message)

    result = st.session_state.get("result")
    if not result:
        st.caption("Fill in the form and click Test connection.")
        return
    if result["ok"]:
        st.success(f"Connection works · status {result['status_code']} · {result['duration_ms'] / 1000:.1f} s")
        if result["reply_text"]:
            st.code(result["reply_text"], language=None, wrap_lines=True)
        else:
            st.caption("(empty reply)")
        if result["reply_truncated"]:
            st.caption("Showing the first 2,000 characters of the reply.")
    else:
        st.error(result["message"])
        if result.get("detail"):
            st.code(result["detail"], language=None, wrap_lines=True)


def main() -> None:
    st.set_page_config(page_title="Kestrel", layout="wide")
    st.sidebar.title("Kestrel")
    config = load_config()
    if config is None:
        st.stop()
    st.session_state.setdefault("form_id", str(uuid.uuid4()))
    st.session_state.setdefault("errors", {})

    with st.sidebar:
        render_form(config)
        st.caption(MODE_CAPTIONS.get(config["mode"], config["mode"]))
    run_pending_test()
    render_result()


main()
