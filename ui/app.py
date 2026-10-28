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


def load_families() -> list[dict]:
    """Attack families from the API, once per session. Empty when no library is available (FR-021 spirit)."""
    if "families" not in st.session_state:
        try:
            st.session_state["families"] = api_client.attack_families().get("families", [])
        except api_client.ApiError:
            st.session_state["families"] = []
    return st.session_state["families"]


def load_prompts(family: str) -> list[dict]:
    """The prompts in a family, cached per family so switching families reloads (FR-008)."""
    cache = st.session_state.setdefault("prompts", {})
    if family not in cache:
        try:
            cache[family] = api_client.attack_prompts(family).get("prompts", [])
        except api_client.ApiError:
            cache[family] = []
    return cache[family]


def load_runs(target_id: int) -> list[dict]:
    """Runs for the selected target, cached until a new run or a target change clears them (FR-028)."""
    if st.session_state.get("runs") is None:
        try:
            st.session_state["runs"] = api_client.list_runs(target_id)
        except api_client.ApiError as error:
            st.session_state["notice"] = api_message(error)
            return []
    return st.session_state["runs"]


# --- Form state ------------------------------------------------------------------------------------------------

def new_form_id() -> None:
    st.session_state["form_id"] = str(uuid.uuid4())


def clear_messages() -> None:
    st.session_state["errors"] = {}
    st.session_state["notice"] = None
    st.session_state["done"] = None
    st.session_state["run_notice"] = None


def init_form(defaults: dict) -> None:
    """Fields are filled through session state, so loading a saved target can set them."""
    state = st.session_state
    for key, value in (("display_name", ""), ("url", ""), ("method", defaults["method"]),
                       ("body_template", defaults["body_template"]), ("response_path", defaults["response_path"]),
                       ("permission", False), ("description", "")):
        state.setdefault(key, value)


def fill_form(target: dict | None) -> None:
    """Load a saved target into the form, or reset it to a new target (None)."""
    state = st.session_state
    defaults = state["config"]["defaults"]
    reset_header_widgets()
    reset_canary_widgets()
    if target is None:
        state.update(display_name="", url="", method=defaults["method"], body_template=defaults["body_template"],
                     response_path=defaults["response_path"], permission=False, description="", headers=[],
                     canaries=[], loaded_target=None)
    else:
        state.update(display_name=target["name"], url=target["url"], method=target["method"],
                     body_template=target["body_template"], response_path=target["response_path"], permission=True,
                     description=target.get("description") or "", loaded_target=target,
                     headers=[{"name": h["name"], "value": "", "stored": True, "readable": h["readable"]}
                              for h in target["headers"]],
                     canaries=[{"value": c} for c in target.get("canaries", [])])
    state["result"] = None
    state["run_result"] = None
    state["runs"] = None  # reload the runs list for the newly selected target
    state["report_md"] = None  # a report belongs to one target; drop it on switch
    state["report_html"] = None
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


# --- Canary rows -----------------------------------------------------------------------------------------------

def canary_rows() -> list[dict]:
    return st.session_state.setdefault("canaries", [])


def sync_canary_rows() -> None:
    for i, row in enumerate(canary_rows()):
        row["value"] = st.session_state.get(f"canary_{i}", row["value"])


def reset_canary_widgets() -> None:
    for key in [k for k in st.session_state if str(k).startswith("canary_")]:
        del st.session_state[key]


def add_canary_row() -> None:
    sync_canary_rows()
    canary_rows().append({"value": ""})
    reset_canary_widgets()


def remove_canary_row(index: int) -> None:
    sync_canary_rows()
    del canary_rows()[index]
    reset_canary_widgets()


def current_canaries() -> list[str]:
    sync_canary_rows()
    return [row["value"].strip() for row in canary_rows() if row["value"].strip()]


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


def start_run() -> None:
    """Run-button callback: capture the attack now; it runs on the next pass with the button disabled (FR-010)."""
    clear_messages()
    st.session_state["pending_run"] = {
        "target_id": loaded_id(),
        "family": st.session_state.get("attack_family"),
        "prompt_id": st.session_state.get("attack_prompt") or None,
        "mode": "adaptive" if st.session_state.get("attack_mode") == "Adaptive" else "single_turn",
        "use_prior_experience": bool(st.session_state.get("use_prior_experience", True)),
    }


def run_pending_run() -> None:
    payload = st.session_state.get("pending_run")
    if payload is None:
        return
    # Claim before calling, so a rerun while the API works can't send the attack twice (mirrors run_pending_test).
    st.session_state["pending_run"] = None
    try:
        with st.spinner("Running the attack… (an adaptive attack can take a few minutes)"):
            st.session_state["run_result"] = api_client.run_attack(payload)
        st.session_state["runs"] = None  # reload the runs list for this target
    except api_client.ApiError as error:
        st.session_state["run_result"] = None
        st.session_state["run_notice"] = api_message(error)
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
        "canaries": current_canaries(),
        "description": (state.get("description") or "").strip() or None,
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

    st.text_input("What is this agent for?", key="description", placeholder="e.g. a customs-classification assistant")
    st.caption("Optional, one line. No sensitive info — it is stored in plain and shown to the attacker.")
    show_error("description")

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

    st.markdown("**Canary strings**")
    st.caption("put these in your agent, so a leak is provable")
    for i, row in enumerate(canary_rows()):
        value_col, remove_col = st.columns([9, 2], vertical_alignment="bottom")
        value_col.text_input("Canary", value=row["value"], key=f"canary_{i}", placeholder="A string to plant",
                             label_visibility="collapsed")
        remove_col.button("✕", key=f"canary_remove_{i}", help="Remove this canary", on_click=remove_canary_row,
                          args=(i,))
        show_error(f"canaries.{i}")
    st.button("Add canary", key="add_canary", on_click=add_canary_row)

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


RUN_BLOCK_MESSAGES = {"permission_missing", "terms_outdated", "run_in_progress"}


def render_attack(config: dict, families: list[dict]) -> None:
    st.subheader("Attack")
    judge = config.get("judge") or {}
    have_target = loaded_id() is not None

    if not families:
        st.caption("The attack library isn't available, so no attacks can be run.")
        return
    # Single-turn (feature 002) or Adaptive multi-turn (feature 003), reusing the same family/prompt controls.
    attacker = config.get("attacker") or {}
    adaptive = config.get("adaptive") or {}
    st.radio("Mode", ["Single-turn", "Adaptive"], key="attack_mode", horizontal=True)
    is_adaptive = st.session_state.get("attack_mode") == "Adaptive"
    experience = config.get("experience") or {}
    st.session_state.setdefault("use_prior_experience", experience.get("use_prior_experience_default", True))
    st.toggle("Use prior experience", key="use_prior_experience")
    st.caption("On: the attacker is primed with similar past patterns and this target's memory, as hints. "
               "Off: a cold run, like before.")
    if is_adaptive:
        if attacker.get("configured"):
            st.caption(f"Adaptive: attacker {attacker.get('model')}, up to {adaptive.get('max_turns')} turns")
        else:
            st.caption("No attacker model is configured, so an adaptive attack can't run.")

    labels = {f["key"]: f"{f['label']} · {f['owasp_category']} ({f['prompt_count']} prompts)" for f in families}
    st.selectbox("Attack family", list(labels), key="attack_family", format_func=lambda key: labels[key])

    # Optionally pick an exact prompt; by default Kestrel picks one from the family (FR-007, FR-008).
    prompts = load_prompts(st.session_state.get("attack_family") or next(iter(labels)))
    titles = {p["id"]: p["title"] for p in prompts}
    if st.session_state.get("attack_prompt") not in titles:
        st.session_state["attack_prompt"] = None
    st.selectbox("Prompt", [None, *titles], key="attack_prompt",
                 format_func=lambda pid: "Kestrel picks one" if pid is None else titles[pid])
    chosen_prompt = next((p for p in prompts if p["id"] == st.session_state.get("attack_prompt")), None)
    if chosen_prompt:
        st.code(chosen_prompt["text"], language=None, wrap_lines=True)

    running = st.session_state.get("pending_run") is not None
    adaptive_blocked = is_adaptive and not attacker.get("configured")
    st.button("Run attack", key="run_button", type="primary", on_click=start_run,
              disabled=running or not have_target or adaptive_blocked)
    if not have_target:
        st.caption("Pick a saved target, choose an attack family, and click Run attack.")

    if st.session_state.get("run_notice"):
        st.error(st.session_state["run_notice"])
    render_run_result(st.session_state.get("run_result"), judge)


STOPPED = {"turn_cap": "stopped at the turn limit", "token_budget": "stopped at the token budget",
           "time_limit": "stopped at the time limit"}


def render_run_result(run: dict | None, judge: dict) -> None:
    if not run:
        return
    if run.get("failure_step"):
        st.error(f"The attack could not be sent: {run.get('reason') or run['failure_step']}.")
        return
    verdict, by_judge = run["verdict"], run["judge_used"]
    model = run.get("judge_model") or judge.get("model") or "the judge"
    # For an adaptive run, say how it ended (e.g. stopped at the turn limit) after the verdict.
    ended = STOPPED.get(run.get("stopping_condition") or "")
    tail = f" · {ended}" if ended else ""
    if verdict == "succeeded" and run["hard_evidence"]:
        at = f" at turn {run['succeeded_turn']}" if run.get("succeeded_turn") else ""
        st.error(f"Attack succeeded · confirmed by canary{at}")
    elif verdict == "succeeded":
        st.error(f"Attack succeeded · suspected, judged by {model}")
    elif verdict == "failed":
        st.success(f"Attack failed · the agent held · judged by {model}{tail}")
    else:
        st.warning((f"Unclear · judged by {model}" if by_judge else "Unclear") + tail)

    if run.get("mode") == "adaptive" or run.get("turns"):
        _render_conversation(run)
    else:
        st.code(run["prompt_text"], language=None, wrap_lines=True)
        if run.get("reply_text"):
            st.code(run["reply_text"], language=None, wrap_lines=True)
        else:
            st.caption("(empty reply)")
        if run.get("reason"):
            st.text(run["reason"])
    # Name the attacker and the OWASP category the run maps to (Principle III, Principle VI).
    source = run.get("attacker_source")
    if source:
        owasp = run.get("owasp_category")
        st.caption(f"Attacker: {source}" + (f" · {owasp}" if owasp else ""))
    if run.get("memory_written") is False:  # FR-010: a loud, visible warning that write-back failed
        st.warning("This run's result was saved, but it could not be written to the experience store.")


def _render_conversation(run: dict) -> None:
    """Show an adaptive run turn by turn, plain text only (FR-023, FR-024)."""
    for turn in run.get("turns", []):
        st.caption(f"Turn {turn['position']} · attacker")
        st.code(turn["attacker_message"], language=None, wrap_lines=True)
        st.caption("agent")
        st.code(turn["reply_text"] if turn.get("reply_text") else "(no reply)", language=None, wrap_lines=True)
        if turn.get("judge_progress"):
            st.text(turn["judge_progress"])
    if run.get("reason"):
        st.text(run["reason"])
    # Principle III: name the attacker model, the judge, and the budget used.
    bits = []
    if run.get("attacker_model"):
        bits.append(f"attacker {run['attacker_model']}")
    if run.get("judge_used") and run.get("judge_model"):
        bits.append(f"judge {run['judge_model']}")
    if run.get("turns_used") is not None:
        bits.append(f"{run['turns_used']}/{run.get('turn_budget')} turns")
    if run.get("tokens_used") is not None:
        bits.append(f"{run['tokens_used']} tokens")
    if bits:
        st.caption(" · ".join(bits))


def _evidence(run: dict) -> str:
    if run.get("failure_step"):
        return "—"
    if run["hard_evidence"]:
        return "canary"
    return f"judge · {run['judge_model']}" if run["judge_used"] else "—"


def render_runs(config: dict) -> None:
    st.subheader("Runs")
    target_id = loaded_id()
    if target_id is None:
        st.caption("Select a saved target to see its runs.")
        return
    runs = load_runs(target_id)
    if not runs:
        st.caption("No runs yet for this target.")
        return
    st.dataframe([{"When": r["started_at"][:19].replace("T", " "),
                   "Mode": "adaptive" if r.get("mode") == "adaptive" else "single-turn", "Family": r["family"],
                   "Prompt": r["prompt_title"], "Verdict": r["verdict"] or r["failure_step"] or "—",
                   "Evidence": _evidence(r)} for r in runs], hide_index=True)

    labels = {r["id"]: f"{r['started_at'][:19].replace('T', ' ')} · {r['prompt_title']}" for r in runs}
    chosen = st.selectbox("Open a run", [None, *labels], key="open_run",
                          format_func=lambda rid: "Choose a run to see its prompt and reply" if rid is None
                          else labels[rid])
    if chosen is not None:
        try:
            render_run_result(api_client.get_run(chosen), config.get("judge") or {})
        except api_client.ApiError as error:
            st.error(api_message(error))


def render_profile() -> None:
    """A per-target summary of its memory records, secrets-free (FR-022, FR-023)."""
    st.subheader("Profile")
    target_id = loaded_id()
    if target_id is None:
        st.caption("Select a saved target to see its profile.")
        return
    try:
        profile = api_client.get_profile(target_id)
    except api_client.ApiError as error:
        st.error(api_message(error))
        return
    if not profile.get("total_runs"):
        st.caption("No runs recorded yet.")
        return
    st.caption(f"{profile['total_runs']} run(s) recorded")
    for family_count in profile.get("by_family", []):
        st.text(f"{family_count['family']}: {family_count['count']}")
    for verdict_count in profile.get("by_verdict", []):
        st.text(f"{verdict_count['verdict']}: {verdict_count['count']}")
    for record in profile.get("recent", []):
        st.code(record["summary"], language=None, wrap_lines=True)


def render_report() -> None:
    """The OWASP-mapped report for the selected target: generate, preview, and download MD/HTML (feature 005)."""
    st.subheader("Report")
    target_id = loaded_id()
    if target_id is None:
        st.caption("Select a saved target to generate a report.")
        return
    if not load_runs(target_id):
        st.caption("No runs to report yet — attack this target first.")
        return
    if st.button("Generate report", key="generate_report"):
        try:
            st.session_state["report_md"] = api_client.get_report(target_id, "md")
            st.session_state["report_html"] = api_client.get_report(target_id, "html")
        except api_client.ApiError as error:
            st.session_state["report_md"] = None
            st.session_state["report_html"] = None
            st.error(api_message(error))
    report_md = st.session_state.get("report_md")
    if report_md:
        md_col, html_col = st.columns(2)
        md_col.download_button("Download Markdown", report_md, file_name="kestrel-report.md",
                               mime="text/markdown", key="download_report_md")
        html_col.download_button("Download HTML", st.session_state.get("report_html") or "",
                                 file_name="kestrel-report.html", mime="text/html", key="download_report_html")
        # Safe preview: run-derived content is fenced, and raw HTML is escaped (unsafe_allow_html stays False).
        st.markdown(report_md, unsafe_allow_html=False)


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
    families = load_families()

    with st.sidebar:
        render_form(config, targets)
        judge = config.get("judge") or {}
        if judge.get("configured"):
            st.caption(f"Judging uses {judge.get('model')}")
        else:
            st.caption("No judge configured: only canary evidence can decide a run")
        st.caption(MODE_CAPTIONS.get(config["mode"], config["mode"]))
    run_pending_test()
    run_pending_run()
    render_attack(config, families)
    render_runs(config)
    render_profile()
    render_report()
    render_result()
    render_targets(targets)


main()
