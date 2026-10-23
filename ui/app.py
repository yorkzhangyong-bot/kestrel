"""Kestrel's screen (contracts/ui-form.md). It only renders and calls the API; it never imports kestrel."""
from __future__ import annotations

import streamlit as st

import api_client

MODE_CAPTIONS = {
    "local": "Running locally",
    "hosted": "Running hosted: local and private addresses are blocked",
}


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


def main() -> None:
    st.set_page_config(page_title="Kestrel")
    st.sidebar.title("Kestrel")
    config = load_config()
    if config is None:
        st.stop()
    st.sidebar.caption(MODE_CAPTIONS.get(config["mode"], config["mode"]))


main()
