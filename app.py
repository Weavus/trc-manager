from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import streamlit as st

from trc.pipeline import (
    CONFIG_PATH,
    DATA_DIR,
    INCIDENTS_DIR,
    PEOPLE_PATH,
    list_incidents,
    load_people_directory,
    process_pipeline,
    save_people_directory,
    setup_logging,
)
from trc.pipeline import (
    parse_filename as parse_filename_info,
)


def init_state() -> None:
    st.session_state.setdefault("page", "TRC Upload")
    st.session_state.setdefault(
        "filters",
        {
            "incident_ids": [],
            "titles": [],
            "people": [],
            "date_range": None,
        },
    )


def sidebar_nav() -> None:
    with st.sidebar:
        st.title("TRC Manager")
        pages = ["TRC Upload", "TRC Library", "People Directory", "Configuration"]
        current = st.session_state.get("page", pages[0])
        for p in pages:
            is_active = p == current
            label = ("• " + p) if is_active else p
            if st.button(
                label,
                key=f"nav_{p.replace(' ', '_').lower()}",
                use_container_width=True,
                disabled=is_active,
            ):
                st.session_state["page"] = p
                st.rerun()


def page_upload() -> None:
    st.header("TRC Upload")
    files = st.file_uploader(
        "Upload one or more TRC .vtt files",
        type=["vtt"],
        accept_multiple_files=True,
    )
    if not files:
        st.info("Select .vtt files to process.")
        return

    for up in files:
        name = up.name
        content = up.read()
        inc_id, dt_token = parse_filename_info(name)
        if not inc_id or not dt_token:
            st.error(
                "Error: Filename must include INC id and DDMMYYYY-HHMM time."
            )
            continue

        # derive ISO time from ddmmyyyy-hhmm
        try:
            dt = datetime.strptime(dt_token, "%d%m%Y-%H%M")
            start_iso = dt.strftime("%Y-%m-%dT%H:%M:00Z")
        except Exception:
            st.error("Error: Invalid date-time in filename; expected DDMMYYYY-HHMM.")
            continue

        inc_path = INCIDENTS_DIR / f"{inc_id}.json"
        existing: dict[str, Any] = {}
        if inc_path.exists():
            existing = json.loads(inc_path.read_text())
        trcs = existing.get("trcs", [])
        match = next((t for t in trcs if t.get("start_time") == start_iso), None)
        new_hash = __import__("hashlib").sha256(content).hexdigest()

        if match:
            old_hash = match.get("file_hash")
            if old_hash and old_hash == new_hash:
                st.warning(
                    f"This file for {inc_id} at {start_iso} already processed."
                )
                continue
            else:
                st.warning(
                    f"Different TRC file for {inc_id} at {start_iso} exists. "
                    "Overwrite and re-process?"
                )
                col1, col2 = st.columns(2)
                go = False
                with col1:
                    if st.button(f"Overwrite {inc_id} {start_iso}"):
                        go = True
                with col2:
                    if st.button(f"Cancel {inc_id} {start_iso}"):
                        go = False
                if not go:
                    continue

        # Save upload
        upload_dir = DATA_DIR / "uploads" / inc_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        save_name = f"{inc_id}-{dt_token}.vtt"
        save_path = upload_dir / save_name
        save_path.write_bytes(content)

        with st.spinner(f"Processing Incident {inc_id}..."):
            result = process_pipeline(content.decode("utf-8", errors="ignore"), inc_id, start_iso)
        if result.success:
            st.success(f"Successfully processed {inc_id}!")
            # update incident file with origin meta
            inc = json.loads(inc_path.read_text())
            trc = next(t for t in inc["trcs"] if t["trc_id"] == result.trc_id)
            trc["original_filename"] = save_name
            trc["original_filepath"] = str(save_path)
            trc["file_hash"] = new_hash
            inc_path.write_text(json.dumps(inc, indent=2))

            if st.button("View Incident in Library"):
                st.session_state["page"] = "TRC Library"
                st.session_state["filters"]["incident_ids"] = [inc_id]
                st.rerun()

            # Stage logs expanders
            st.subheader("Pipeline Stages")
            for log in result.stage_logs:
                prefix = (
                    "✅ "
                    if log.status == "Completed"
                    else ("❌ " if log.status == "Failed" else "⏭️ ")
                )
                title = prefix + f"{log.name}"
                with st.expander(title, expanded=False):
                    st.text(f"Time taken: {log.duration_s:.2f}s")
                    st.text(f"Status: {log.status}")
                    if log.input_info:
                        st.text(log.input_info)
                    if log.output_info:
                        st.text(log.output_info)
                    for m in log.messages:
                        st.info(m)
            if not result.success:
                st.error(
                    f"Processing failed for {inc_id} at stage: {result.failed_stage}. "
                    "See details above."
                )
        else:
            st.error(f"Processing failed for {inc_id} at stage: {result.failed_stage}.")


def filter_incidents(incidents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    f = st.session_state["filters"]
    ids = set(f.get("incident_ids") or [])
    titles = set(f.get("titles") or [])
    people = set(f.get("people") or [])
    date_range = f.get("date_range")

    def incident_in_people_filter(incident: dict[str, Any]) -> bool:
        if not people:
            return True
        directory = load_people_directory()
        incident_ids: set[str] = set()
        for raw_name in people:
            p = directory.get(raw_name)
            if not p:
                continue
            for entry in p.get("discovered_roles", []) + p.get("discovered_knowledge", []):
                incident_ids.add(entry.get("incident_id"))
        if not incident_ids:
            return False
        return incident.get("incident_id") in incident_ids

    def incident_in_date(incident: dict[str, Any]) -> bool:
        if not date_range:
            return True
        start, end = date_range
        # any trc within range
        for t in incident.get("trcs", []):
            try:
                ts = datetime.strptime(t.get("start_time"), "%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                continue
            if (start is None or ts.date() >= start) and (end is None or ts.date() <= end):
                return True
        return False

    out: list[dict[str, Any]] = []
    for inc in incidents:
        if ids and inc.get("incident_id") not in ids:
            continue
        if titles and inc.get("title") not in titles:
            continue
        if not incident_in_people_filter(inc):
            continue
        if not incident_in_date(inc):
            continue
        out.append(inc)
    return out


def page_library() -> None:
    st.header("TRC Library")

    incidents = list_incidents()
    all_ids = [i.get("incident_id") for i in incidents]
    all_titles = sorted({i.get("title") for i in incidents if i.get("title")})
    people_dir = load_people_directory()
    all_people = sorted(list(people_dir.keys()))

    with st.sidebar:
        st.subheader("Filters")
        st.session_state["filters"]["incident_ids"] = st.multiselect(
            "Filter by Incident ID",
            options=all_ids,
            default=st.session_state["filters"].get("incident_ids", []),
        )
        st.session_state["filters"]["titles"] = st.multiselect(
            "Filter by Title",
            options=all_titles,
            default=st.session_state["filters"].get("titles", []),
        )
        st.session_state["filters"]["date_range"] = st.date_input(
            "Filter by Date Range", value=st.session_state["filters"].get("date_range")
        )
        st.session_state["filters"]["people"] = st.multiselect(
            "Filter by People",
            options=all_people,
            default=st.session_state["filters"].get("people", []),
        )

    filtered = filter_incidents(incidents)
    if not filtered:
        st.info("No incidents found")
        return

    for inc in filtered:
        title = f"{inc.get('incident_id')}: {inc.get('title') or '(no title)'}"
        with st.expander(title, expanded=False):
            new_title = st.text_input(
                "Incident Title", value=inc.get("title", ""), key=f"title_{inc['incident_id']}"
            )
            if st.button("Save Title", key=f"save_title_{inc['incident_id']}"):
                inc["title"] = new_title
                (INCIDENTS_DIR / f"{inc['incident_id']}.json").write_text(
                    json.dumps(inc, indent=2)
                )
                st.success("Title saved")

            ms = st.text_area(
                "Master Summary",
                value=inc.get("master_summary", ""),
                key=f"ms_{inc['incident_id']}",
                height=250,
            )
            if st.button("Save Master Summary", key=f"save_ms_{inc['incident_id']}"):
                inc["master_summary"] = ms
                (INCIDENTS_DIR / f"{inc['incident_id']}.json").write_text(
                    json.dumps(inc, indent=2)
                )
                st.success("Master Summary saved")

            st.subheader("TRC Calls")
            trcs = inc.get("trcs", [])
            if not trcs:
                st.info("No TRCs for this incident")
                continue
            tab_labels = [f"Call {i+1}: {t.get('start_time')}" for i, t in enumerate(trcs)]
            tabs = st.tabs(tab_labels)
            for _idx, (tab, trc) in enumerate(zip(tabs, trcs, strict=False)):
                with tab:
                    subtabs = st.tabs(
                        ["Summary", "Refined Text", "People", "Raw Text", "Original VTT"]
                    )
                    with subtabs[0]:
                        summary_val = trc.get("pipeline_outputs", {}).get("summarisation", "")
                        new_sum = st.text_area(
                            "TRC Summary", value=summary_val, key=f"sum_{trc['trc_id']}", height=300
                        )
                        if st.button("Save Summary", key=f"save_sum_{trc['trc_id']}"):
                            trc["pipeline_outputs"]["summarisation"] = new_sum
                            (INCIDENTS_DIR / f"{inc['incident_id']}.json").write_text(
                                json.dumps(inc, indent=2)
                            )
                            st.success("Summary saved")
                    with subtabs[1]:
                        st.text_area(
                            "Refined",
                            value=trc.get("pipeline_outputs", {}).get("refinement", ""),
                            disabled=True,
                        )
                    with subtabs[2]:
                        st.json(trc.get("pipeline_outputs", {}).get("people_extraction", {}))
                    with subtabs[3]:
                        st.text_area(
                            "Raw Text",
                            value=trc.get("pipeline_outputs", {}).get("cleanup", ""),
                            disabled=True,
                        )
                    with subtabs[4]:
                        st.text_area(
                            "Original VTT",
                            value=trc.get("pipeline_outputs", {}).get("raw_vtt", ""),
                            disabled=True,
                        )

                    # Rerun controls
                    st.divider()
                    start_from = st.selectbox(
                        "Rerun pipeline from:",
                        options=[
                            "Start",
                            "cleanup",
                            "refinement",
                            "people_extraction",
                            "summarisation",
                            "keyword_extraction",
                        ],
                        key=f"rerun_from_{trc['trc_id']}",
                    )
                    if st.button("Go", key=f"rerun_{trc['trc_id']}"):
                        start_stage = None if start_from == "Start" else start_from
                        result = process_pipeline(
                            trc.get("pipeline_outputs", {}).get("raw_vtt", ""),
                            inc.get("incident_id"),
                            trc.get("start_time"),
                            start_stage=start_stage,
                        )
                        if result.success:
                            st.success("Re-run completed")
                        else:
                            st.error(f"Re-run failed at stage {result.failed_stage}")


def page_people() -> None:
    st.header("People Directory")
    directory = load_people_directory()
    names = sorted(list(directory.keys()))
    roles_set = sorted(
        {
            r.get("role")
            for p in directory.values()
            for r in p.get("discovered_roles", [])
            if r.get("role")
        }
    )
    skills_set = sorted(
        {
            k.get("knowledge")
            for p in directory.values()
            for k in p.get("discovered_knowledge", [])
            if k.get("knowledge")
        }
    )

    with st.sidebar:
        st.subheader("Filters")
        selected_names = st.multiselect("Filter by Name", options=names)
        selected_roles = st.multiselect("Filter by Role", options=roles_set)
        selected_skills = st.multiselect("Filter by Skill/Knowledge", options=skills_set)

    def person_matches(p: dict[str, Any]) -> bool:
        if selected_names and p.get("raw_name") not in selected_names:
            return False
        if selected_roles:
            roles = {r.get("role") for r in p.get("discovered_roles", [])}
            if not roles.intersection(selected_roles):
                return False
        if selected_skills:
            skills = {k.get("knowledge") for k in p.get("discovered_knowledge", [])}
            if not skills.intersection(selected_skills):
                return False
        return True

    filtered = [
        dict(p, raw_name=k)
        for k, p in directory.items()
        if person_matches(dict(p, raw_name=k))
    ]

    if not filtered:
        st.info("No people in directory")
        return

    for person in filtered:
        with st.expander(person.get("display_name") or person.get("raw_name")):
            dn = st.text_input(
                "Display Name", value=person.get("display_name", ""), key=f"dn_{person['raw_name']}"
            )
            ro = st.text_input(
                "Canonical Role (Override)",
                value=person.get("role_override") or "",
                key=f"ro_{person['raw_name']}",
            )
            if st.button("Save Changes", key=f"save_p_{person['raw_name']}"):
                directory[person["raw_name"]]["display_name"] = dn
                directory[person["raw_name"]]["role_override"] = ro or None
                save_people_directory(directory)
                st.success("Saved")


            tabs = st.tabs(["Discovered Roles", "Discovered Knowledge"])
            with tabs[0]:
                for i, entry in enumerate(person.get("discovered_roles", [])):
                    st.subheader(entry.get("role"))
                    st.caption(f"From Incident: {entry.get('incident_id')}")
                    st.progress(
                        (entry.get("confidence_score") or 0.0) / 10.0,
                        text=f"Confidence: {int((entry.get('confidence_score') or 0.0) * 10)}%",
                    )
                    st.info(f"Reasoning: {entry.get('reasoning')}")
                    if st.button("Delete Role", key=f"del_role_{person['raw_name']}_{i}"):
                        directory[person["raw_name"]]["discovered_roles"].pop(i)
                        save_people_directory(directory)
                        st.success("Role removed")
            with tabs[1]:
                for i, entry in enumerate(person.get("discovered_knowledge", [])):
                    st.subheader(entry.get("knowledge"))
                    st.caption(f"From Incident: {entry.get('incident_id')}")
                    st.progress(
                        (entry.get("confidence_score") or 0.0) / 10.0,
                        text=f"Confidence: {int((entry.get('confidence_score') or 0.0) * 10)}%",
                    )
                    st.info(f"Reasoning: {entry.get('reasoning')}")
                    if st.button("Delete Knowledge", key=f"del_know_{person['raw_name']}_{i}"):
                        directory[person["raw_name"]]["discovered_knowledge"].pop(i)
                        save_people_directory(directory)
                        st.success("Knowledge removed")

            st.subheader("Add Manual Role")
            with st.form(key=f"add_role_{person['raw_name']}"):
                role = st.text_input("Role")
                inc = st.text_input("Incident ID (optional)")
                reasoning = st.text_area("Reasoning")
                conf = st.slider("Confidence", 0.0, 10.0, 10.0)
                if st.form_submit_button("Add Role"):
                    entry = {
                        "role": role,
                        "incident_id": inc or None,
                        "reasoning": reasoning,
                        "confidence_score": conf,
                    }
                    directory[person["raw_name"]].setdefault("discovered_roles", []).append(entry)
                    save_people_directory(directory)
                    st.success("Role added")

            st.subheader("Add Manual Knowledge")
            with st.form(key=f"add_know_{person['raw_name']}"):
                know = st.text_input("Knowledge/Skill")
                inc2 = st.text_input("Incident ID (optional)")
                reasoning2 = st.text_area("Reasoning")
                conf2 = st.slider("Confidence", 0.0, 10.0, 10.0)
                if st.form_submit_button("Add Knowledge"):
                    entry = {
                        "knowledge": know,
                        "incident_id": inc2 or None,
                        "reasoning": reasoning2,
                        "confidence_score": conf2,
                    }
                    directory[person["raw_name"]].setdefault("discovered_knowledge", []).append(
                        entry
                    )
                    save_people_directory(directory)
                    st.success("Knowledge added")


def page_config() -> None:
    st.header("Configuration")

    # Load config
    if CONFIG_PATH.exists():
        cfg: dict[str, Any] = json.loads(CONFIG_PATH.read_text())
    else:
        cfg = {
            "pipeline_order": [
                "cleanup",
                "refinement",
                "people_extraction",
                "summarisation",
                "keyword_extraction",
                "master_summary",
            ],
            "stages": {
                s: {"enabled": True, "params": {}}
                for s in [
                    "cleanup",
                    "refinement",
                    "people_extraction",
                    "summarisation",
                    "keyword_extraction",
                    "master_summary",
                ]
            },
        }

    st.subheader("Pipeline Order and Stages")
    st.caption("Drag to reorder; toggle to enable/disable; edit params JSON.")

    order = cfg.get("pipeline_order", [])
    # Manual reordering via selectboxes
    new_order: list[str] = []
    for i, _s in enumerate(order):
        new_order.append(
            st.selectbox(f"Position {i+1}", options=order, index=i, key=f"ord_{i}")
        )
    if len(set(new_order)) == len(order):
        cfg["pipeline_order"] = new_order

    for s in order:
        enabled = st.checkbox(
            f"Enable {s}",
            value=cfg.get("stages", {}).get(s, {}).get("enabled", True),
            key=f"en_{s}",
        )
        cfg["stages"].setdefault(s, {})["enabled"] = enabled
        params_str = json.dumps(cfg["stages"][s].get("params", {}), indent=2)
        new_params = st.text_area(f"Params for {s}", value=params_str, key=f"pa_{s}")
        try:
            cfg["stages"][s]["params"] = json.loads(new_params)
        except Exception:
            st.warning(f"Invalid JSON for {s} params; keeping previous")

    st.subheader("Maintenance")
    if st.button("Clear People Directory") and st.checkbox(
        "Are you sure? This will delete all discovered people, roles, and knowledge."
    ):
        PEOPLE_PATH.write_text("{}\n")
        st.success("People directory cleared")

    if st.button("Save Configuration"):
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
        st.success("Configuration saved")


def main() -> None:
    setup_logging()
    init_state()
    sidebar_nav()

    page = st.session_state["page"]
    if page == "TRC Upload":
        page_upload()
    elif page == "TRC Library":
        page_library()
    elif page == "People Directory":
        page_people()
    elif page == "Configuration":
        page_config()


if __name__ == "__main__":
    main()
