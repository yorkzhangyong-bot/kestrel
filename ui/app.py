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
PERMISSION_LABEL = "I own this agent or have written permission to test it"
STORED_PLACEHOLDER = "Stored · leave empty to keep"
UNREADABLE_PLACEHOLDER = "Can't be read with the current key · enter it again"
NEW_TARGET = 0  # the picker's "New target" entry; saved targets have ids from 1
SIDEBAR_FIELDS = {"name", "settings.url", "settings.body_template", "settings.response_path", "permission_confirmed",
                  "terms_version", "save", "delete"}


def api_message(error: api_client.ApiError) -> str:
    return (error.body.get("error") or {}).get("message") or "Kestrel's API answered with an error."


def errors_from(error: api_client.ApiError, default_field: str) -> dict[str, str]:
    """Field errors from a 422, or one error under default_field (or the field the API names) otherwise."""
    if error.status == 422:
        return {e["field"]: e["message"] for e in error.body.get("errors", [])}
    detail = error.body.get("error") or {}
    return {detail.get("field") or default_field: api_message(error)}


def load_config() -> dict | None:
    """Fetch /api/config once per session; a failure isn't cached, so the next run retries."""
    if "config" not in st.session_state:
        try:
            st.session_state["config"] = api_client.get_config()
        except api_client.ApiError as error:
            st.error(api_message(error))
            return None
    return st.session_state["config"]


def load_targets() -> list[dict]:
    if st.session_state.get("targets") is None:
        try:
            st.session_state["targets"] = api_client.list_targets()
        except api_client.ApiError as error:
            st.session_state["notice"] = api_message(error)
            return []
    return st.session_state["targets"]


# --- Form state ------------------------------------------------------------------------------------------------

def new_form_id() -> None:
    st.session_state["form_id"] = str(uuid.uuid4())


def clear_messages() -> None:
    st.session_state["errors"] = {}
    st.session_state["notice"] = None
    st.session_state["done"] = None


def init_form(defaults: dict) -> None:
    """Fields are filled through session state, so loading a saved target can set them."""
    state = st.session_state
    for key, value in (("display_name", ""), ("url", ""), ("method", defaults["method"]),
                       ("body_template", defaults["body_template"]), ("response_path", defaults["response_path"]),
                       ("permission", False)):
        state.setdefault(key, value)


def fill_form(target: dict | None) -> None:
    """Load a saved target into the form, or reset it to a new target (None)."""
    state = st.session_state
    defaults = state["config"]["defaults"]
    reset_header_widgets()
    if target is None:
        state.update(display_name="", url="", method=defaults["method"], body_template=defaults["body_template"],
                     response_path=defaults["response_path"], permission=False, headers=[], loaded_target=None)
    else:
        state.update(display_name=target["name"], url=target["url"], method=target["method"],
                     body_template=target["body_template"], response_path=target["response_path"], permission=True,
                     loaded_target=target,
                     headers=[{"name": h["name"], "value": "", "stored": True, "readable": h["readable"]}
                              for h in target["headers"]])
    state["result"] = None
    state["confirm_delete"] = False
    new_form_id()


def select_target() -> None:
    """Picker callback: load the chosen target, or start a new one (FR-016)."""
    clear_messages()
    target_id = st.session_state.get("target_select", NEW_TARGET)
    if target_id == NEW_TARGET:
        fill_form(None)
        return
    try:
        fill_form(api_client.get_target(target_id))
    except api_client.ApiError as error:
        fill_form(None)
        st.session_state["target_select"] = NEW_TARGET
        st.session_state["notice"] = api_message(error)
        st.session_state["targets"] = None


def url_changed() -> None:
    """The permission covers one endpoint: a new URL clears the tick until it's given again (FR-018)."""
    loaded = st.session_state.get("loaded_target")
    if loaded and (st.session_state.get("url") or "").strip() != loaded["url"]:
        st.session_state["permission"] = False


# --- Header rows -----------------------------------------------------------------------------------------------

def header_rows() -> list[dict]:
    return st.session_state.setdefault("headers", [])


def sync_header_rows() -> None:
    """Copy the header widgets' current values into the rows."""
    for i, row in enumerate(header_rows()):
        row["name"] = st.session_state.get(f"header_name_{i}", row["name"])
        row["value"] = st.session_state.get(f"header_value_{i}", row["value"])


def reset_header_widgets() -> None:
    """Drop the header widgets' state, so they redraw from the rows after rows change."""
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


# --- Actions ---------------------------------------------------------------------------------------------------

def current_settings() -> dict:
    state = st.session_state
    headers = []
    for row in header_rows():
        name, value = row["name"].strip(), row["value"]
        if not name and not value and not row.get("stored"):
            continue  # an untouched empty row
        # An empty stored value means "keep the stored one" (FR-017).
        headers.append({"name": name, "value": None if row.get("stored") and value == "" else value})
    return {"url": (state.get("url") or "").strip(), "method": state.get("method") or "POST", "headers": headers,
            "body_template": state.get("body_template") or "", "response_path": (state.get("response_path") or "").strip()}


def loaded_id() -> int | None:
    loaded = st.session_state.get("loaded_target")
    return loaded["id"] if loaded else None


def start_test() -> None:
    """Button callback: capture the form now; the test runs on the next pass, with the button disabled."""
    sync_header_rows()
    clear_messages()
    st.session_state["pending_test"] = {
        "form_id": st.session_state["form_id"],
        "target_id": loaded_id(),  # lets the API use kept header values (FR-016)
        "display_name": (st.session_state.get("display_name") or "").strip(),
        "settings": current_settings(),
    }


def run_pending_test() -> None:
    payload = st.session_state.get("pending_test")
    if payload is None:
        return
    # Claim the test before calling: Streamlit can start a new pass while this one waits on the API (for example
    # when Save is clicked mid-test), and that pass must not send the same test again.
    st.session_state["pending_test"] = None
    try:
        with st.spinner("Testing the connection…"):
            st.session_state["result"] = api_client.test_connection(payload)
    except api_client.ApiError as error:
        st.session_state["result"] = None
        if error.status == 422:
            st.session_state["errors"] = errors_from(error, "test")
        else:
            st.session_state["notice"] = api_message(error)
    st.rerun()


def save() -> None:
    """Save-button callback: a new target, or an edit of the loaded one (FR-011, FR-012, FR-029)."""
    sync_header_rows()
    clear_messages()
    state = st.session_state
    payload = {
        "form_id": state["form_id"],
        "name": (state.get("display_name") or "").strip(),
        "settings": current_settings(),
        "permission_confirmed": bool(state.get("permission")),
        "terms_version": state["config"]["terms"]["version"],
    }
    target_id = loaded_id()
    try:
        if target_id is None:
            saved = api_client.save_target(payload)
        else:
            saved = api_client.update_target(target_id, payload)
    except api_client.ApiError as error:
        state["errors"] = errors_from(error, "save")
        return
    # The typed header values leave the session: the saved target is loaded, its values stored and hidden.
    state["targets"] = None
    fill_form(saved)
    state["target_select"] = saved["id"]
    state["done"] = "Target saved."


def ask_delete() -> None:
    st.session_state["confirm_delete"] = True


def cancel_delete() -> None:
    st.session_state["confirm_delete"] = False


def confirm_delete() -> None:
    clear_messages()
    target_id = loaded_id()
    try:
        api_client.delete_target(target_id)
    except api_client.ApiError as error:
        st.session_state["confirm_delete"] = False
        st.session_state["errors"] = errors_from(error, "delete")
        return
    st.session_state["targets"] = None
    fill_form(None)
    st.session_state["target_select"] = NEW_TARGET
    st.session_state["done"] = "Target deleted."


# --- Rendering -------------------------------------------------------------------------------------------------

def show_error(field: str) -> None:
    message = st.session_state.get("errors", {}).get(field)
    if message:
        st.error(message)


def render_picker(targets: list[dict]) -> None:
    labels = {t["id"]: f"{t['name']} · {t['url']}" for t in targets}
    if st.session_state.get("target_select") not in labels:
        st.session_state["target_select"] = NEW_TARGET
    st.selectbox("Target", [NEW_TARGET, *labels], key="target_select", on_change=select_target,
                 format_func=lambda target_id: "New target" if target_id == NEW_TARGET else labels[target_id])


def render_form(config: dict, targets: list[dict]) -> None:
    render_picker(targets)
    st.text_input("Display name", key="display_name", placeholder="My agent")
    show_error("name")

    method_col, url_col = st.columns([3, 5])
    method_col.selectbox("Method", METHODS, key="method")
    url_col.text_input("Endpoint URL", key="url", placeholder="https://my-agent.example.com/chat", on_change=url_changed)
    show_error("settings.url")

    st.markdown("**Auth headers**")
    st.caption("stored encrypted, never shown in report")
    for i, row in enumerate(header_rows()):
        name_col, value_col, remove_col = st.columns([4, 5, 2], vertical_alignment="bottom")
        name_col.text_input("Header name", value=row["name"], key=f"header_name_{i}", placeholder="Header name",
                            label_visibility="collapsed")
        placeholder = "Value"
        if row.get("stored"):
            placeholder = STORED_PLACEHOLDER if row.get("readable", True) else UNREADABLE_PLACEHOLDER
        value_col.text_input("Header value", value=row["value"], key=f"header_value_{i}", type="password",
                             placeholder=placeholder, label_visibility="collapsed")
        remove_col.button("✕", key=f"header_remove_{i}", help="Remove this header", on_click=remove_header_row,
                          args=(i,))
        show_error(f"settings.headers.{i}.name")
        show_error(f"settings.headers.{i}.value")
    st.button("Add header", key="add_header", on_click=add_header_row)

    st.text_input("Request body template", key="body_template")
    show_error("settings.body_template")
    st.text_input("Response path", key="response_path")
    show_error("settings.response_path")

    st.button("Test connection", key="test_button", on_click=start_test,
              disabled=st.session_state.get("pending_test") is not None)

    st.checkbox(PERMISSION_LABEL, key="permission")
    show_error("permission_confirmed")
    terms = config["terms"]
    with st.expander(f"Terms of service (version {terms['version']})"):
        st.text(terms["text"])
    show_error("terms_version")
    st.button("Save target", key="save_button", type="primary", on_click=save)
    show_error("save")

    if loaded_id() is not None:
        if st.session_state.get("confirm_delete"):
            st.warning("Delete this target and its stored auth headers?")
            confirm_col, cancel_col = st.columns(2)
            confirm_col.button("Confirm delete", key="delete_confirm", on_click=confirm_delete)
            cancel_col.button("Cancel", key="delete_cancel", on_click=cancel_delete)
        else:
            st.button("Delete target", key="delete_button", on_click=ask_delete)
        show_error("delete")


def render_result() -> None:
    st.subheader("Connection test")
    if st.session_state.get("notice"):
        st.warning(st.session_state["notice"])
    for field, message in st.session_state.get("errors", {}).items():
        if field not in SIDEBAR_FIELDS and not field.startswith("settings.headers."):
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


def render_targets(targets: list[dict]) -> None:
    st.subheader("Saved targets")
    if st.session_state.get("done"):
        st.success(st.session_state["done"])
    if not targets:
        st.caption("No saved targets yet.")
        return
    st.dataframe([{"Name": t["name"], "URL": t["url"], "Method": t["method"],
                   "Permission confirmed": t["permission_confirmed_at"][:10], "Terms version": t["terms_version"]}
                  for t in targets], hide_index=True)


def main() -> None:
    st.set_page_config(page_title="Kestrel", layout="wide")
    st.sidebar.title("Kestrel")
    config = load_config()
    if config is None:
        st.stop()
    st.session_state.setdefault("form_id", str(uuid.uuid4()))
    st.session_state.setdefault("errors", {})
    init_form(config["defaults"])
    targets = load_targets()

    with st.sidebar:
        render_form(config, targets)
        st.caption(MODE_CAPTIONS.get(config["mode"], config["mode"]))
    run_pending_test()
    render_result()
    render_targets(targets)


main()
