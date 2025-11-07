from __future__ import annotations

import contextlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st

from trc.pipeline import (
    CONFIG_PATH,
    DATA_DIR,
    INCIDENTS_DIR,
    list_incidents,
    load_people_directory,
    process_pipeline,
    save_people_directory,
    setup_logging,
)
from trc.pipeline import (
    parse_filename as parse_filename_info,
)


def _format_chars_and_size(text: str) -> str:
    try:
        chars = len(text or "")
        bytes_len = len((text or "").encode("utf-8"))
        if bytes_len >= 1024 * 1024:
            size = f"{int(round(bytes_len / (1024 * 1024)))} MB"
        elif bytes_len >= 1024:
            size = f"{int(round(bytes_len / 1024))} KB"
        else:
            size = f"{bytes_len} B"
        return f"{chars:,} characters ({size})"
    except Exception:
        return ""


def _copy_script(content: str) -> None:
    try:
        js = json.dumps(content or "")
        st.markdown(
            f"<script>navigator.clipboard.writeText({js});</script>",
            unsafe_allow_html=True,
        )
    except Exception:
        pass


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
            st.error("Error: Filename must include INC id and DDMMYYYY-HHMM time.")
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

        go = True
        # Overwrite handling
        if match:
            go = False
            old_hash = match.get("file_hash")
            if old_hash and old_hash == new_hash:
                st.warning(f"An identical TRC for {inc_id} at {start_iso} already exists.")
                col1, col2 = st.columns(2)
                with col1:
                    if st.button(
                        f"Proceed and overwrite {inc_id} {start_iso}",
                        key=f"overwrite_same_{inc_id}_{start_iso}_{name}",
                    ):
                        go = True
                with col2:
                    if st.button(
                        f"Cancel {inc_id} {start_iso}",
                        key=f"cancel_same_{inc_id}_{start_iso}_{name}",
                    ):
                        go = False
                if not go:
                    continue
            else:
                st.warning(
                    f"A different TRC for {inc_id} at {start_iso} already exists. "
                    "Overwrite and re-process?"
                )
                col1, col2 = st.columns(2)
                go = False
                with col1:
                    if st.button(
                        f"Overwrite {inc_id} {start_iso}",
                        key=f"overwrite_diff_{inc_id}_{start_iso}_{name}",
                    ):
                        go = True
                with col2:
                    if st.button(
                        f"Cancel {inc_id} {start_iso}",
                        key=f"cancel_diff_{inc_id}_{start_iso}_{name}",
                    ):
                        go = False
                if not go:
                    continue
            # If overwriting existing TRC, update raw_vtt and file_hash before processing
            try:
                inc_doc = existing if existing else json.loads(inc_path.read_text())
            except Exception:
                inc_doc = existing
            for t in inc_doc.get("trcs", []):
                if t.get("start_time") == start_iso:
                    t.setdefault("pipeline_outputs", {})["raw_vtt"] = content.decode(
                        "utf-8", errors="ignore"
                    )
                    t["file_hash"] = new_hash
                    break
            inc_path.write_text(json.dumps(inc_doc, indent=2))

        if not go:
            # Skip saving & processing until user confirms overwrite
            continue

        # Save upload now that we are cleared to proceed
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
            # Load fresh incident + trc for displaying inputs/outputs
            inc_view = json.loads(inc_path.read_text())
            trc_view = next(t for t in inc_view.get("trcs", []) if t.get("trc_id") == result.trc_id)

            # Helper mapping for stage input/output keys
            input_key_map: dict[str, str] = {
                "transcription_parsing": "raw_vtt",
                "text_enhancement": "transcription_parsing",
                "noise_reduction": "text_enhancement",
                "participant_analysis": "noise_reduction",
                "summarisation": "noise_reduction",
                "keyword_extraction": "noise_reduction",
            }

            for log in result.stage_logs:
                prefix = (
                    "✅ "
                    if log.status == "Completed"
                    else ("❌ " if log.status == "Failed" else "⏭️ ")
                )
                title = prefix + f"{log.name}"
                open_key = f"stage_open_{result.trc_id}_{log.name}"
                if open_key not in st.session_state:
                    st.session_state[open_key] = False
                with st.expander(title, expanded=st.session_state[open_key]):
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        st.text(f"Status: {log.status}")
                    with c2:
                        st.text(f"Duration: {log.duration_s:.2f}s")
                    with c3:
                        st.text(f"Messages: {len(log.messages)}")

                    in_col, out_col = st.columns(2)
                    stage = log.name

                    # Inputs
                    with in_col:
                        # Header with copy button
                        hc1, hc2 = st.columns([0.9, 0.1])
                        with hc1:
                            st.markdown("**Inputs**")
                        # Compute input text to copy
                        input_text = ""
                        if stage == "master_summary_synthesis":
                            summaries = [
                                t.get("pipeline_outputs", {}).get("summarisation", "")
                                for t in inc_view.get("trcs", [])
                            ]
                            agg = "\n\n".join([s for s in summaries if s])
                            input_text = agg
                            label_ms_in = f"summarisation (all TRCs) {_format_chars_and_size(agg)}"
                            st.text_area(
                                label_ms_in,
                                value=agg,
                                height=400,
                                disabled=True,
                                key=f"in_ms_agg_{inc_id}_{result.trc_id}",
                            )
                        else:
                            key = input_key_map.get(stage)
                            if key:
                                val = trc_view.get("pipeline_outputs", {}).get(key, "")
                                if isinstance(val, (dict, list)):
                                    input_text = json.dumps(val, indent=2)
                                    st.json(val)
                                else:
                                    input_text = val or ""
                                    label = f"{key} {_format_chars_and_size(val or '')}"
                                    st.text_area(
                                        label,
                                        value=val or "",
                                        height=400,
                                        disabled=True,
                                        key=f"in_{stage}_{key}_{result.trc_id}",
                                    )
                        with hc2:
                            if st.button(
                                "📋",
                                key=f"copy_in_{result.trc_id}_{stage}",
                                help="Copy inputs to clipboard",
                            ):
                                _copy_script(input_text or "")
                                st.session_state[open_key] = True

                    # Outputs
                    with out_col:
                        # Header with copy button
                        hoc1, hoc2 = st.columns([0.9, 0.1])
                        with hoc1:
                            st.markdown("**Outputs**")
                        out_text = ""
                        if stage == "master_summary_synthesis":
                            ms_text = inc_view.get("master_summary", "")
                            st.text_area(
                                f"master_summary {_format_chars_and_size(ms_text)}",
                                value=ms_text,
                                height=400,
                                disabled=True,
                                key=f"out_ms_{inc_id}_{result.trc_id}",
                            )
                            out_text += ms_text or ""

                            # Incident-level artifacts
                            inc_art = inc_view.get("pipeline_artifacts", {}) or {}
                            ms_art = inc_art.get("master_summary_raw_llm_output")
                            if ms_art:
                                try:
                                    with open(ms_art, encoding="utf-8") as f:
                                        raw = f.read()
                                    label_ms_raw = (
                                        "master_summary_raw_llm_output "
                                        f"{_format_chars_and_size(raw)}"
                                    )
                                    st.text_area(
                                        label_ms_raw,
                                        value=raw,
                                        height=400,
                                        disabled=True,
                                        key=f"ms_raw_{inc_id}_{result.trc_id}",
                                    )
                                    out_text += "\n\n" + (raw or "")
                                except Exception:
                                    st.caption("master_summary_raw_llm_output: (unavailable)")
                        else:
                            po = trc_view.get("pipeline_outputs", {})
                            # primary outputs per stage
                            out_key = None
                            if stage in (
                                "transcription_parsing",
                                "text_enhancement",
                                "noise_reduction",
                                "summarisation",
                            ):
                                out_key = stage if stage != "summarisation" else "summarisation"
                            elif stage == "participant_analysis":
                                out_key = "participant_analysis"
                            elif stage == "keyword_extraction":
                                out_key = "keywords"

                            if out_key and out_key in po:
                                val = po[out_key]
                                if isinstance(val, (dict, list)):
                                    st.json(val)
                                    out_text += json.dumps(val, indent=2)
                                else:
                                    st.text_area(
                                        f"{out_key} {_format_chars_and_size(val or '')}",
                                        value=val or "",
                                        height=400,
                                        disabled=True,
                                        key=f"out_{out_key}_{trc_view.get('trc_id')}_{result.trc_id}",
                                    )
                                    out_text += val or ""

                            # Show stage artifacts if present
                            arts = trc_view.get("pipeline_artifacts", {}) or {}
                            artifact_keys: list[str] = []
                            if stage == "summarisation":
                                artifact_keys = ["summarisation_llm_output"]
                            elif stage == "participant_analysis":
                                artifact_keys = [
                                    "participant_analysis_llm_output",
                                    "participant_analysis_llm_output_raw",
                                ]
                            elif stage == "text_enhancement":
                                artifact_keys = ["text_enhancement_diffs"]
                            for ak in artifact_keys:
                                path = arts.get(ak)
                                if not path:
                                    continue
                                try:
                                    if (
                                        ak.endswith("_raw")
                                        or ak.endswith("_llm_output")
                                        and path.endswith(".txt")
                                    ) and path.endswith(".txt"):
                                        with open(path, encoding="utf-8") as f:
                                            raw = f.read()
                                        st.text_area(
                                            f"{ak} {_format_chars_and_size(raw)}",
                                            value=raw,
                                            height=400,
                                            disabled=True,
                                            key=f"art_{ak}_{trc_view.get('trc_id')}_{result.trc_id}",
                                        )
                                        out_text += "\n\n" + (raw or "")
                                    elif path.endswith(".json"):
                                        with open(path, encoding="utf-8") as f:
                                            data = json.loads(f.read())
                                        st.json(data)
                                        out_text += "\n\n" + json.dumps(data, indent=2)
                                except Exception:
                                    st.caption(f"{ak}: (unavailable)")
                        with hoc2:
                            if st.button(
                                "📋",
                                key=f"copy_out_{result.trc_id}_{stage}",
                                help="Copy outputs to clipboard",
                            ):
                                _copy_script(out_text or "")
                                st.session_state[open_key] = True

                    # Any log messages
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
            orig_title = inc.get("title", "")
            title_key = f"title_{inc['incident_id']}"
            new_title = st.text_input("Incident Title", value=orig_title, key=title_key)
            if new_title != orig_title:
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Save Title", key=f"save_title_{inc['incident_id']}"):
                        inc["title"] = new_title
                        inc_path = INCIDENTS_DIR / f"{inc['incident_id']}.json"
                        inc_path.write_text(json.dumps(inc, indent=2))
                        st.success("Title saved")
                with c2:
                    if st.button("Revert", key=f"revert_title_{inc['incident_id']}"):
                        st.session_state[title_key] = orig_title
                        st.info("Reverted")
                        st.rerun()

            orig_ms = inc.get("master_summary", "")
            ms_key = f"ms_{inc['incident_id']}"
            ms = st.text_area(
                "Master Summary",
                value=orig_ms,
                key=ms_key,
                height=500,
            )
            if ms != orig_ms:
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Save Master Summary", key=f"save_ms_{inc['incident_id']}"):
                        inc["master_summary"] = ms
                        (INCIDENTS_DIR / f"{inc['incident_id']}.json").write_text(
                            json.dumps(inc, indent=2)
                        )
                        st.success("Master Summary saved")
                with c2:
                    if st.button("Revert", key=f"revert_ms_{inc['incident_id']}"):
                        st.session_state[ms_key] = orig_ms
                        st.info("Reverted")
                        st.rerun()

            st.subheader("TRC Calls")
            trcs = inc.get("trcs", [])
            if not trcs:
                st.info("No TRCs for this incident")
                continue
            tab_labels = [f"Call {i + 1}: {t.get('start_time')}" for i, t in enumerate(trcs)]
            tabs = st.tabs(tab_labels)
            for _idx, (tab, trc) in enumerate(zip(tabs, trcs, strict=False)):
                with tab:
                    stage_tabs = st.tabs(
                        [
                            "transcription_parsing",
                            "text_enhancement",
                            "noise_reduction",
                            "participant_analysis",
                            "summarisation",
                            "keyword_extraction",
                            "master_summary_synthesis",
                        ]
                    )

                    # Helper mapping for stage inputs
                    input_key_map = {
                        "transcription_parsing": "raw_vtt",
                        "text_enhancement": "transcription_parsing",
                        "noise_reduction": "text_enhancement",
                        "participant_analysis": "noise_reduction",
                        "summarisation": "noise_reduction",
                        "keyword_extraction": "noise_reduction",
                    }

                    for _s, tab_stage in enumerate(
                        [
                            "transcription_parsing",
                            "text_enhancement",
                            "noise_reduction",
                            "participant_analysis",
                            "summarisation",
                            "keyword_extraction",
                            "master_summary_synthesis",
                        ]
                    ):
                        with stage_tabs[_s]:
                            in_col, out_col = st.columns(2)

                            # Inputs
                            with in_col:
                                ih1, ih2 = st.columns([0.9, 0.1])
                                with ih1:
                                    st.markdown("**Inputs**")
                                input_text = ""
                                if tab_stage == "master_summary_synthesis":
                                    summaries = [
                                        t.get("pipeline_outputs", {}).get("summarisation", "")
                                        for t in inc.get("trcs", [])
                                    ]
                                    agg = "\n\n".join([s for s in summaries if s])
                                    input_text = agg
                                    label_ms_in = (
                                        f"summarisation (all TRCs) {_format_chars_and_size(agg)}"
                                    )
                                    st.text_area(
                                        label_ms_in,
                                        value=agg,
                                        height=400,
                                        disabled=True,
                                        key=f"lib_in_ms_agg_{inc['incident_id']}_{trc['trc_id']}",
                                    )
                                else:
                                    key = input_key_map.get(tab_stage)
                                    if key:
                                        val = trc.get("pipeline_outputs", {}).get(key, "")
                                        if isinstance(val, (dict, list)):
                                            input_text = json.dumps(val, indent=2)
                                            st.json(val)
                                        else:
                                            input_text = val or ""
                                            label = f"{key} {_format_chars_and_size(val or '')}"
                                            st.text_area(
                                                label,
                                                value=val or "",
                                                height=400,
                                                disabled=True,
                                                key=f"lib_in_{tab_stage}_{key}_{trc['trc_id']}",
                                            )
                                with ih2:
                                    if st.button(
                                        "📋",
                                        key=f"lib_copy_in_{trc['trc_id']}_{tab_stage}",
                                        help="Copy inputs to clipboard",
                                    ):
                                        _copy_script(input_text or "")

                            # Outputs
                            with out_col:
                                oh1, oh2 = st.columns([0.9, 0.1])
                                with oh1:
                                    st.markdown("**Outputs**")
                                out_text = ""
                                if tab_stage == "master_summary_synthesis":
                                    ms_text = inc.get("master_summary", "")
                                    st.text_area(
                                        f"master_summary {_format_chars_and_size(ms_text)}",
                                        value=ms_text,
                                        height=400,
                                        disabled=True,
                                        key=f"lib_out_ms_{inc['incident_id']}_{trc['trc_id']}",
                                    )
                                    out_text += ms_text or ""
                                    inc_art = inc.get("pipeline_artifacts", {}) or {}
                                    ms_art = inc_art.get("master_summary_raw_llm_output")
                                    if ms_art:
                                        try:
                                            with open(ms_art, encoding="utf-8") as f:
                                                raw = f.read()
                                            label_ms_raw = (
                                                "master_summary_raw_llm_output "
                                                f"{_format_chars_and_size(raw)}"
                                            )
                                            st.text_area(
                                                label_ms_raw,
                                                value=raw,
                                                height=400,
                                                disabled=True,
                                                key=f"lib_ms_raw_{inc['incident_id']}_{trc['trc_id']}",
                                            )
                                            out_text += "\n\n" + (raw or "")
                                        except Exception:
                                            st.caption(
                                                "master_summary_raw_llm_output: (unavailable)"
                                            )
                                else:
                                    po = trc.get("pipeline_outputs", {})
                                    out_key = None
                                    if tab_stage in (
                                        "transcription_parsing",
                                        "text_enhancement",
                                        "noise_reduction",
                                        "summarisation",
                                    ):
                                        out_key = (
                                            tab_stage
                                            if tab_stage != "summarisation"
                                            else "summarisation"
                                        )
                                    elif tab_stage == "participant_analysis":
                                        out_key = "participant_analysis"
                                    elif tab_stage == "keyword_extraction":
                                        out_key = "keywords"
                                    if out_key and out_key in po:
                                        val = po[out_key]
                                        if isinstance(val, (dict, list)):
                                            st.json(val)
                                            out_text += json.dumps(val, indent=2)
                                        else:
                                            st.text_area(
                                                f"{out_key} {_format_chars_and_size(val or '')}",
                                                value=val or "",
                                                height=400,
                                                disabled=True,
                                                key=f"lib_out_{out_key}_{trc['trc_id']}",
                                            )
                                            out_text += val or ""
                                    arts = trc.get("pipeline_artifacts", {}) or {}
                                    artifact_keys: list[str] = []
                                    if tab_stage == "summarisation":
                                        artifact_keys = ["summarisation_llm_output"]
                                    elif tab_stage == "participant_analysis":
                                        artifact_keys = [
                                            "participant_analysis_llm_output",
                                            "participant_analysis_llm_output_raw",
                                        ]
                                    elif tab_stage == "text_enhancement":
                                        artifact_keys = ["text_enhancement_diffs"]
                                    for ak in artifact_keys:
                                        path = arts.get(ak)
                                        if not path:
                                            continue
                                        try:
                                            if (
                                                ak.endswith("_raw")
                                                or ak.endswith("_llm_output")
                                                and path.endswith(".txt")
                                            ) and path.endswith(".txt"):
                                                with open(path, encoding="utf-8") as f:
                                                    raw = f.read()
                                                st.text_area(
                                                    f"{ak} {_format_chars_and_size(raw)}",
                                                    value=raw,
                                                    height=400,
                                                    disabled=True,
                                                    key=f"lib_art_{ak}_{trc['trc_id']}",
                                                )
                                                out_text += "\n\n" + (raw or "")
                                            elif path.endswith(".json"):
                                                with open(path, encoding="utf-8") as f:
                                                    data = json.loads(f.read())
                                                st.json(data)
                                                out_text += "\n\n" + json.dumps(data, indent=2)
                                        except Exception:
                                            st.caption(f"{ak}: (unavailable)")
                                with oh2:
                                    if st.button(
                                        "📋",
                                        key=f"lib_copy_out_{trc['trc_id']}_{tab_stage}",
                                        help="Copy outputs to clipboard",
                                    ):
                                        _copy_script(out_text or "")

                    # Rerun controls
                    st.divider()
                    start_from = st.selectbox(
                        "Rerun pipeline from:",
                        options=[
                            "Start",
                            "transcription_parsing",
                            "text_enhancement",
                            "noise_reduction",
                            "participant_analysis",
                            "summarisation",
                            "keyword_extraction",
                        ],
                        key=f"rerun_from_{trc['trc_id']}",
                    )
                    if st.button("Go", key=f"rerun_{trc['trc_id']}"):
                        start_stage = None if start_from == "Start" else start_from
                        raw_vtt = trc.get("pipeline_outputs", {}).get("raw_vtt", "")
                        inc_id_val = inc.get("incident_id")
                        start_time = trc.get("start_time")
                        if not inc_id_val or not start_time:
                            st.error(
                                "Missing incident_id or start_time for this TRC; cannot rerun."
                            )
                        else:
                            result = process_pipeline(
                                raw_vtt,
                                inc_id_val,
                                start_time,
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
            if isinstance(r.get("role"), str)
        }
    )
    skills_set = sorted(
        {
            k.get("knowledge")
            for p in directory.values()
            for k in p.get("discovered_knowledge", [])
            if isinstance(k.get("knowledge"), str)
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
        dict(p, raw_name=k) for k, p in directory.items() if person_matches(dict(p, raw_name=k))
    ]

    if not filtered:
        st.info("No people in directory")
        return

    for person in filtered:
        with st.expander(person.get("display_name") or person.get("raw_name")):
            orig_dn = person.get("display_name", "")
            orig_ro = person.get("role_override") or ""
            dn_key = f"dn_{person['raw_name']}"
            ro_key = f"ro_{person['raw_name']}"
            dn = st.text_input("Display Name", value=orig_dn, key=dn_key)
            ro = st.text_input(
                "Canonical Role (Override)",
                value=orig_ro,
                key=ro_key,
            )
            if dn != orig_dn or ro != orig_ro:
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Save Changes", key=f"save_p_{person['raw_name']}"):
                        directory[person["raw_name"]]["display_name"] = dn
                        directory[person["raw_name"]]["role_override"] = ro or None
                        save_people_directory(directory)
                        st.success("Saved")
                with c2:
                    if st.button("Revert", key=f"revert_p_{person['raw_name']}"):
                        st.session_state[dn_key] = orig_dn
                        st.session_state[ro_key] = orig_ro
                        st.info("Reverted")
                        st.rerun()

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
                reasoning = st.text_area("Reasoning", key=f"role_reason_{person['raw_name']}")
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
                reasoning2 = st.text_area("Reasoning", key=f"know_reason_{person['raw_name']}")
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
                "transcription_parsing",
                "text_enhancement",
                "noise_reduction",
                "participant_analysis",
                "summarisation",
                "keyword_extraction",
                "master_summary_synthesis",
            ],
            "stages": {
                s: {"enabled": True, "params": {}}
                for s in [
                    "transcription_parsing",
                    "text_enhancement",
                    "noise_reduction",
                    "participant_analysis",
                    "summarisation",
                    "keyword_extraction",
                    "master_summary_synthesis",
                ]
            },
        }

    st.subheader("Pipeline Order and Stages")
    st.caption("Drag to reorder; toggle to enable/disable; edit params JSON.")

    order = cfg.get("pipeline_order", [])
    # Manual reordering via selectboxes
    new_order: list[str] = []
    for i, _s in enumerate(order):
        new_order.append(st.selectbox(f"Position {i + 1}", options=order, index=i, key=f"ord_{i}"))
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
    # People maintenance
    st.markdown("**People Directory**")
    confirm_del_all_people = st.checkbox(
        "Confirm delete ALL people (roles & knowledge will be lost).",
        key="confirm_del_all_people",
    )
    btn_delete_all_people = st.button(
        "Delete ALL People",
        disabled=not confirm_del_all_people,
        key="btn_delete_all_people",
    )
    if btn_delete_all_people:
        save_people_directory({})
        st.success("People directory cleared")
        st.rerun()
    people_dir = load_people_directory()
    people_names = sorted(list(people_dir.keys()))
    if people_names:
        del_person = st.selectbox(
            "Delete Individual Person",
            options=["(select)"] + people_names,
            key="delete_person_select",
        )
        delete_person_disabled = del_person == "(select)"
        confirm_del_person = st.checkbox(
            f"Confirm delete person '{del_person}'", key=f"confirm_del_person_{del_person}"
        )
        if (
            st.button(
                "Delete Person",
                disabled=delete_person_disabled or not confirm_del_person,
                key="btn_delete_person",
            )
            and not delete_person_disabled
            and confirm_del_person
        ):
            people_dir.pop(del_person, None)
            save_people_directory(people_dir)
            st.success(f"Deleted person: {del_person}")
            st.rerun()

    st.markdown("---")
    # TRC / Incident maintenance
    st.markdown("**TRC / Incident Library**")
    incidents = list_incidents()
    incident_ids = [i.get("incident_id") for i in incidents]

    confirm_del_all_incidents = st.checkbox(
        "Confirm delete ALL incidents, TRCs, artifacts & uploads.",
        key="confirm_del_all_incidents",
    )
    if (
        st.button(
            "Delete ALL Incidents & TRCs",
            disabled=not confirm_del_all_incidents,
            key="btn_delete_all_incidents",
        )
        and confirm_del_all_incidents
    ):
        # Remove incident JSONs
        for f in INCIDENTS_DIR.glob("*.json"):
            with contextlib.suppress(Exception):
                f.unlink()
        # Remove artifacts + uploads directories
        artifacts_root = DATA_DIR / "artifacts"
        uploads_root = DATA_DIR / "uploads"
        for root in [artifacts_root, uploads_root]:
            if root.exists():
                for p in root.glob("*"):
                    with contextlib.suppress(Exception):
                        if p.is_dir():
                            import shutil

                            shutil.rmtree(p, ignore_errors=True)
                        else:
                            p.unlink(missing_ok=True)  # type: ignore[arg-type]
        st.success("All incidents/TRCs removed")
        st.rerun()

    if incident_ids:
        sel_inc = st.selectbox(
            "Select Incident",
            options=["(select)"] + incident_ids,
            key="maintenance_select_incident",
        )
        if sel_inc != "(select)":
            # Load selected incident
            inc_path = INCIDENTS_DIR / f"{sel_inc}.json"
            inc_doc = json.loads(inc_path.read_text()) if inc_path.exists() else {}
            trcs = inc_doc.get("trcs", [])
            trc_labels = [t.get("trc_id") for t in trcs]
            sel_trc = st.selectbox(
                "Select TRC to Delete (optional)",
                options=["(none)"] + trc_labels,
                key=f"maintenance_select_trc_{sel_inc}",
            )
            c1, c2 = st.columns(2)
            with c1:
                delete_trc_disabled = sel_trc == "(none)"
                if (
                    st.button(
                        "Delete Selected TRC",
                        disabled=delete_trc_disabled,
                        key=f"btn_delete_trc_{sel_inc}",
                    )
                    and not delete_trc_disabled
                    and st.checkbox(
                        f"Confirm delete TRC '{sel_trc}'", key=f"confirm_del_trc_{sel_trc}"
                    )
                ):
                    # Remove TRC entry
                    new_trcs = [t for t in trcs if t.get("trc_id") != sel_trc]
                    inc_doc["trcs"] = new_trcs
                    inc_path.write_text(json.dumps(inc_doc, indent=2))
                    # Remove artifacts dir for that TRC
                    art_dir = DATA_DIR / "artifacts" / sel_inc / sel_trc
                    if art_dir.exists():
                        import shutil

                        shutil.rmtree(art_dir, ignore_errors=True)
                    # Remove original upload file if present
                    for t in trcs:
                        if t.get("trc_id") == sel_trc:
                            orig_fp = t.get("original_filepath")
                            if orig_fp:
                                with contextlib.suppress(Exception):
                                    Path(orig_fp).unlink(missing_ok=True)
                            break
                    st.success(f"Deleted TRC: {sel_trc}")
                    st.rerun()
            with c2:
                if st.button("Delete Entire Incident") and st.checkbox(
                    f"Confirm delete incident '{sel_inc}' and ALL its TRCs",
                    key=f"confirm_del_inc_{sel_inc}",
                ):
                    # Delete incident file
                    with contextlib.suppress(Exception):
                        inc_path.unlink()
                    # Delete incident-level artifacts dir
                    inc_art_dir = DATA_DIR / "artifacts" / sel_inc
                    if inc_art_dir.exists():
                        import shutil

                        shutil.rmtree(inc_art_dir, ignore_errors=True)
                    # Delete uploads dir
                    inc_uploads_dir = DATA_DIR / "uploads" / sel_inc
                    if inc_uploads_dir.exists():
                        import shutil

                        shutil.rmtree(inc_uploads_dir, ignore_errors=True)
                    st.success(f"Deleted incident: {sel_inc}")
                    st.rerun()

    if st.button("Save Configuration"):
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
        st.success("Configuration saved")


def main() -> None:
    setup_logging()
    # Use full-width layout
    st.set_page_config(page_title="TRC Manager", layout="wide")
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
