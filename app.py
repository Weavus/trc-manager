from __future__ import annotations

import contextlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st
from st_diff_viewer import diff_viewer
from streamlit_sortables import sort_items

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


def _format_trc_datetime(iso_datetime: str) -> str:
    """Format ISO datetime to 'Wednesday 5th June 2025 18:01' format."""
    try:
        # Parse ISO datetime (e.g., "2025-06-05T10:01:00Z")
        dt = datetime.fromisoformat(iso_datetime.replace("Z", "+00:00"))
        # Format as requested
        day_name = dt.strftime("%A")  # Wednesday
        day = dt.day
        # Add ordinal suffix
        suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
        day_with_suffix = f"{day}{suffix}"
        month_name = dt.strftime("%B")  # June
        year = dt.year
        time_24h = dt.strftime("%H:%M")  # 18:01
        return f"{day_name} {day_with_suffix} {month_name} {year} {time_24h}"
    except Exception:
        return iso_datetime  # Fallback to original if parsing fails


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
        # Header section with branding
        col1, col2 = st.columns([3, 1])
        with col1:
            st.markdown("## 🔧 TRC Manager")
            st.caption("Technical Recovery Call Processor")
        with col2:
            # Status indicator
            total_incidents = len(list_incidents())
            st.metric("Incidents", total_incidents, delta=None, delta_color="normal")

        st.divider()

        # Navigation sections
        nav_items = [
            {
                "name": "TRC Upload",
                "icon": "📤",
                "description": "Upload and process new TRC files",
                "badge": None
            },
            {
                "name": "TRC Library",
                "icon": "📚",
                "description": "Browse and manage processed TRCs",
                "badge": f"{total_incidents} incidents"
            },
            {
                "name": "People Directory",
                "icon": "👥",
                "description": "Manage participant information",
                "badge": f"{len(load_people_directory())} people"
            },
            {
                "name": "Configuration",
                "icon": "⚙️",
                "description": "System settings and pipeline config",
                "badge": None
            }
        ]

        current = st.session_state.get("page", nav_items[0]["name"])

        # Navigation buttons with improved styling
        for item in nav_items:
            is_active = item["name"] == current

            # Create button with custom styling
            button_label = f"{item['icon']} {item['name']}"
            if item["badge"]:
                button_label += f" ({item['badge']})"

            # Use different styling for active vs inactive
            if is_active:
                st.markdown(f"""
                <div style="
                    background-color: #e3f2fd;
                    border-left: 4px solid #1976d2;
                    padding: 12px 16px;
                    border-radius: 0 8px 8px 0;
                    margin: 4px 0;
                    font-weight: 600;
                    color: #1976d2;
                ">
                    {item['icon']} {item['name']} {f"({item['badge']})" if item["badge"] else ""}
                </div>
                """, unsafe_allow_html=True)
                st.caption(f"📍 {item['description']}")
            else:
                if st.button(
                    button_label,
                    key=f"nav_{item['name'].replace(' ', '_').lower()}",
                    use_container_width=True,
                    help=item["description"]
                ):
                    st.session_state["page"] = item["name"]
                    st.rerun()

        st.divider()

        # Quick actions section
        st.markdown("### 🚀 Quick Actions")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("📊 Stats", help="View system statistics"):
                st.info("Feature coming soon!")
        with col2:
            if st.button("🔍 Search", help="Search across all content"):
                st.info("Feature coming soon!")

        # Footer
        st.markdown("---")
        st.caption("v0.1.0 | Built with Streamlit")


def page_upload() -> None:
    st.header("TRC Upload")

    # Initialize session state for tracking processed files
    if "processed_files" not in st.session_state:
        st.session_state.processed_files = set()

    # Add a button to clear processed files list
    col1, col2 = st.columns([3, 1])
    with col1:
        st.subheader("Upload TRC Files")
    with col2:
        if st.button(
            "Clear Processed List",
            help="Clear the list of processed files to allow re-uploading"
        ):
            st.session_state.processed_files.clear()
            st.rerun()

    files = st.file_uploader(
        "Upload one or more TRC .vtt files",
        type=["vtt"],
        accept_multiple_files=True,
    )
    if not files:
        st.info("Select .vtt files to process.")
        return

    # Filter out already processed files
    unprocessed_files = []
    skipped_files = []
    for up in files:
        # Create a unique identifier for the file based on name and content hash
        content = up.read()
        file_id = f"{up.name}_{hash(content)}"
        up.seek(0)  # Reset file pointer after reading

        if file_id not in st.session_state.processed_files:
            unprocessed_files.append(up)
        else:
            skipped_files.append(up.name)

    # Show feedback about skipped files
    if skipped_files:
        st.info(
            f"Skipping {len(skipped_files)} already processed file(s): {', '.join(skipped_files)}"
        )

    if not unprocessed_files:
        st.success("All selected files have already been processed!")
        return

    files = unprocessed_files
    st.info(f"Processing {len(files)} file(s)...")

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
            # Mark this file as processed
            file_id = f"{name}_{hash(content)}"
            st.session_state.processed_files.add(file_id)

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
                    text_enhancement_diffs_data = None

                    # Helper mapping for stage input/output keys
                    input_key_map: dict[str, str] = {
                        "transcription_parsing": "raw_vtt",
                        "text_enhancement": "transcription_parsing",
                        "noise_reduction": "text_enhancement",
                        "participant_analysis": "noise_reduction",
                        "summarisation": "noise_reduction",
                        "keyword_extraction": "noise_reduction",
                    }

                    # Inputs
                    with in_col:
                        st.markdown("**Inputs**")
                        if stage == "master_summary_synthesis":
                            summaries = [
                                t.get("pipeline_outputs", {}).get("summarisation", "")
                                for t in inc_view.get("trcs", [])
                            ]
                            agg = "\n\n".join([s for s in summaries if s])
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
                                    st.json(val)
                                else:
                                    label = f"{key} {_format_chars_and_size(val or '')}"
                                    st.text_area(
                                        label,
                                        value=val or "",
                                        height=400,
                                        disabled=True,
                                        key=f"in_{stage}_{key}_{result.trc_id}",
                                    )

                    # Outputs
                    with out_col:
                        st.markdown("**Outputs**")
                        if stage == "master_summary_synthesis":
                            ms_text = inc_view.get("master_summary", "")
                            st.text_area(
                                f"master_summary {_format_chars_and_size(ms_text)}",
                                value=ms_text,
                                height=400,
                                disabled=True,
                                key=f"out_ms_{inc_id}_{result.trc_id}",
                            )

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
                                else:
                                    st.text_area(
                                        f"{out_key} {_format_chars_and_size(val or '')}",
                                        value=val or "",
                                        height=400,
                                        disabled=True,
                                        key=f"out_{out_key}_{trc_view.get('trc_id')}_{result.trc_id}",
                                    )

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
                                    elif path.endswith(".json"):
                                        with open(path, encoding="utf-8") as f:
                                            data = json.loads(f.read())
                                        if ak == "text_enhancement_diffs":
                                            text_enhancement_diffs_data = data
                                        else:
                                            st.json(data)
                                except Exception:
                                    st.caption(f"{ak}: (unavailable)")

                    # Display text enhancement diffs full-width if present
                    if text_enhancement_diffs_data and stage == "text_enhancement":
                        total_reps = text_enhancement_diffs_data.get("total_replacements", 0)
                        st.markdown(f"**Total replacements: {total_reps}**")
                        changes = text_enhancement_diffs_data.get("changes", [])
                        if changes:
                            st.markdown("**Text Enhancement Differences:**")
                            for i, change in enumerate(changes):
                                hhmm = change.get("hhmm", "N/A")
                                speaker = change.get("speaker", "N/A")
                                with st.expander(
                                    f"Change {i + 1}: {hhmm} - {speaker}",
                                    expanded=False,
                                ):
                                    old_text = change.get("old_dialogue", "")
                                    new_text = change.get("new_dialogue", "")
                                    diff_viewer(old_text=old_text, new_text=new_text)
                        else:
                            st.caption("No changes recorded")

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

    # Collect all TRCs from all incidents
    all_trcs = []
    for inc in incidents:
        for trc in inc.get("trcs", []):
            all_trcs.append({"trc": trc, "incident": inc})

    # Get dates that have TRCs for calendar widget
    trc_dates = set()
    for item in all_trcs:
        try:
            dt = datetime.fromisoformat(item["trc"].get("start_time", "").replace("Z", "+00:00"))
            trc_dates.add(dt.date())
        except Exception:
            pass

    # Convert to list and sort for calendar
    trc_dates_list = sorted(list(trc_dates))

    # Filters
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

        # Calendar widget showing dates with TRCs
        if trc_dates_list:
            min_date = min(trc_dates_list)
            max_date = max(trc_dates_list)
            selected_date = st.date_input(
                "Select Date (shows dates with TRCs)",
                value=None,
                min_value=min_date,
                max_value=max_date,
                key="selected_date",
            )
            # Highlight dates with TRCs
            if selected_date and selected_date not in trc_dates:
                st.warning("No TRCs found for selected date")
        else:
            selected_date = None

        st.session_state["filters"]["people"] = st.multiselect(
            "Filter by People",
            options=all_people,
            default=st.session_state["filters"].get("people", []),
        )

    # Filter TRCs based on current filters
    filtered_trcs = []
    f = st.session_state["filters"]
    ids = set(f.get("incident_ids") or [])
    titles = set(f.get("titles") or [])
    people = set(f.get("people") or [])

    for item in all_trcs:
        trc = item["trc"]
        inc = item["incident"]

        # Filter by incident ID
        if ids and inc.get("incident_id") not in ids:
            continue

        # Filter by title
        if titles and inc.get("title") not in titles:
            continue

        # Filter by selected date
        if selected_date:
            try:
                trc_date = datetime.fromisoformat(
                    trc.get("start_time", "").replace("Z", "+00:00")
                ).date()  # noqa: E501
                if trc_date != selected_date:
                    continue
            except Exception:
                continue

        # Filter by people
        if people:
            directory = load_people_directory()
            incident_ids: set[str] = set()
            for raw_name in people:
                p = directory.get(raw_name)
                if not p:
                    continue
                for entry in p.get("discovered_roles", []) + p.get("discovered_knowledge", []):
                    incident_ids.add(entry.get("incident_id"))
            if not incident_ids or inc.get("incident_id") not in incident_ids:
                continue

        filtered_trcs.append(item)

    if not filtered_trcs:
        st.info("No TRCs found matching the filters")
        return

    # Group TRCs by date, then by incident
    incidents_by_date = {}
    for item in filtered_trcs:
        try:
            dt = datetime.fromisoformat(item["trc"].get("start_time", "").replace("Z", "+00:00"))
            date_key = dt.date()
            incident_id = item["incident"].get("incident_id")
            if date_key not in incidents_by_date:
                incidents_by_date[date_key] = {}
            if incident_id not in incidents_by_date[date_key]:
                incidents_by_date[date_key][incident_id] = {
                    "incident": item["incident"],
                    "trcs": [],
                }
            incidents_by_date[date_key][incident_id]["trcs"].append(item["trc"])
        except Exception:
            # If parsing fails, put in a special "Unknown Date" group
            if "Unknown Date" not in incidents_by_date:
                incidents_by_date["Unknown Date"] = {}
            incident_id = item["incident"].get("incident_id")
            if incident_id not in incidents_by_date["Unknown Date"]:
                incidents_by_date["Unknown Date"][incident_id] = {
                    "incident": item["incident"],
                    "trcs": [],
                }
            incidents_by_date["Unknown Date"][incident_id]["trcs"].append(item["trc"])

    # Sort dates newest first (but keep "Unknown Date" at end)
    sorted_dates = sorted([d for d in incidents_by_date if d != "Unknown Date"], reverse=True)
    if "Unknown Date" in incidents_by_date:
        sorted_dates.append("Unknown Date")

    for date_key in sorted_dates:
        if date_key == "Unknown Date":
            st.subheader("Unknown Date")
        else:
            # Format date nicely
            day_name = date_key.strftime("%A")
            day = date_key.day
            suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
            month_name = date_key.strftime("%B")
            year = date_key.year
            date_display = f"{day_name} {day}{suffix} {month_name} {year}"
            st.subheader(date_display)

        # Get incidents for this date
        date_incidents = incidents_by_date[date_key]

        for _incident_id, incident_data in date_incidents.items():
            inc = incident_data["incident"]
            trcs = incident_data["trcs"]

            # Sort TRCs by time (oldest first)
            trcs.sort(key=lambda t: t.get("start_time", ""))

            # Use the most recent TRC time for the incident display
            try:
                latest_trc = trcs[-1]  # Last in sorted list (most recent)
                dt = datetime.fromisoformat(latest_trc.get("start_time", "").replace("Z", "+00:00"))
                time_str = dt.strftime("%H:%M")
            except Exception:
                time_str = "Unknown"

            title = f"{inc.get('incident_id')} - {time_str} - {inc.get('title') or '(no title)'}"
            with st.expander(title, expanded=False):
                # Edit incident title and master summary
                edit_title_key = f"edit_title_{inc['incident_id']}"
                edit_ms_key = f"edit_ms_{inc['incident_id']}"
                if edit_title_key not in st.session_state:
                    st.session_state[edit_title_key] = inc.get("title", "")
                if edit_ms_key not in st.session_state:
                    st.session_state[edit_ms_key] = inc.get("master_summary", "")

                # Handle revert flag
                if st.session_state.pop(f"revert_flag_{inc['incident_id']}", False):
                    st.session_state[edit_title_key] = inc.get("title", "")
                    st.session_state[edit_ms_key] = inc.get("master_summary", "")

                st.text_input("Title", key=edit_title_key)
                st.text_area("Master Summary", height=200, key=edit_ms_key)

                changed = st.session_state.get(edit_title_key, "") != inc.get(
                    "title", ""
                ) or st.session_state.get(edit_ms_key, "") != inc.get("master_summary", "")
                if changed:
                    col1, col2 = st.columns([6, 1])
                    with col2:
                        save_col, revert_col = st.columns(2)
                        with save_col:
                            if st.button("Save Changes", key=f"save_inc_{inc['incident_id']}"):
                                inc["title"] = st.session_state[edit_title_key]
                                inc["master_summary"] = st.session_state[edit_ms_key]
                                inc_path = INCIDENTS_DIR / f"{inc['incident_id']}.json"
                                inc_path.write_text(json.dumps(inc, indent=2))
                                st.success("Saved")
                                st.rerun()
                        with revert_col:
                            if st.button("Revert", key=f"revert_inc_{inc['incident_id']}"):
                                st.session_state[f"revert_flag_{inc['incident_id']}"] = True
                                st.rerun()

                # TRC calls tabs
                st.subheader("TRC Calls")
                # Sort TRCs by start_time (oldest first)
                trcs_sorted = sorted(trcs, key=lambda t: t.get("start_time", ""))

                tab_labels = [
                    f"TRC {i + 1}: {_format_trc_datetime(t.get('start_time', ''))}"
                    for i, t in enumerate(trcs_sorted)
                ]
                trc_tabs = st.tabs(tab_labels)
                for _idx, (trc_tab, trc) in enumerate(zip(trc_tabs, trcs_sorted, strict=False)):
                    with trc_tab:
                        # TRC details
                        with st.expander("Pipeline Details", expanded=False):
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
                                    text_enhancement_diffs_data = None

                                    # Inputs
                                    with in_col:
                                        st.markdown("**Inputs**")
                                        if tab_stage == "master_summary_synthesis":
                                            summaries = [
                                                t.get("pipeline_outputs", {}).get(
                                                    "summarisation", ""
                                                )
                                                for t in inc.get("trcs", [])
                                            ]
                                            agg = "\n\n".join([s for s in summaries if s])
                                            label_ms_in = f"summarisation (all TRCs) {_format_chars_and_size(agg)}"  # noqa: E501
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
                                                    st.json(val)
                                                else:
                                                    label = (
                                                        f"{key} {_format_chars_and_size(val or '')}"
                                                    )
                                                    st.text_area(
                                                        label,
                                                        value=val or "",
                                                        height=400,
                                                        disabled=True,
                                                        key=f"lib_in_{tab_stage}_{key}_{inc['incident_id']}_{trc['trc_id']}",
                                                    )

                                    # Outputs
                                    with out_col:
                                        st.markdown("**Outputs**")
                                        if tab_stage == "master_summary_synthesis":
                                            ms_text = inc.get("master_summary", "")
                                            st.text_area(
                                                f"master_summary {_format_chars_and_size(ms_text)}",
                                                value=ms_text,
                                                height=400,
                                                disabled=True,
                                                key=f"lib_out_ms_{inc['incident_id']}_{trc['trc_id']}_ms",
                                            )
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
                                                        key=f"lib_ms_raw_{inc['incident_id']}_{trc['trc_id']}_raw",
                                                    )
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
                                                else:
                                                    st.text_area(
                                                        f"{out_key} {_format_chars_and_size(val or '')}",  # noqa: E501
                                                        value=val or "",
                                                        height=400,
                                                        disabled=True,
                                                        key=f"lib_out_{out_key}_{inc['incident_id']}_{trc['trc_id']}",
                                                    )
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
                                                            key=f"lib_art_{ak}_{inc['incident_id']}_{trc['trc_id']}",
                                                        )
                                                    elif path.endswith(".json"):
                                                        with open(path, encoding="utf-8") as f:
                                                            data = json.loads(f.read())
                                                        if ak == "text_enhancement_diffs":
                                                            text_enhancement_diffs_data = data
                                                        else:
                                                            st.json(data)
                                                except Exception:
                                                    st.caption(f"{ak}: (unavailable)")

                                    # Display text enhancement diffs full-width if present
                                    if (
                                        text_enhancement_diffs_data
                                        and tab_stage == "text_enhancement"
                                    ):
                                        total_reps = text_enhancement_diffs_data.get(
                                            "total_replacements", 0
                                        )
                                        changes = text_enhancement_diffs_data.get("changes", [])
                                        if changes:
                                            st.markdown(f"**{total_reps} Replacements:**")
                                            for i, change in enumerate(changes):
                                                hhmm = change.get("hhmm", "N/A")
                                                speaker = change.get("speaker", "N/A")
                                                title = f"Change {i + 1}: {hhmm} - {speaker}"  # noqa: E501
                                                with st.expander(title, expanded=False):
                                                    old_text = change.get("old_dialogue", "")
                                                    new_text = change.get("new_dialogue", "")
                                                    diff_viewer(
                                                        old_text=old_text, new_text=new_text
                                                    )
                                        elif not changes:
                                            st.caption("No changes recorded")

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
                                key=f"rerun_from_{inc['incident_id']}_{trc['trc_id']}",
                            )
                            if st.button("Go", key=f"rerun_{inc['incident_id']}_{trc['trc_id']}"):
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

    tabs = st.tabs(["Pipeline Configuration", "People Maintenance", "Incident Maintenance"])

    with tabs[0]:
        st.subheader("Pipeline Order and Stages")
        st.caption(
            "Reorder stages using up/down buttons, toggle enable/disable, "
            "and edit parameters as JSON."
        )

        order = cfg.get("pipeline_order", [])
        st.markdown("**Pipeline Order (Drag to Reorder)**")
        sorted_order = sort_items(order, key="pipeline_sort")
        cfg["pipeline_order"] = sorted_order

        st.markdown("---")
        st.subheader("Stage Settings")
        for s in order:
            with st.expander(f"{s.replace('_', ' ').title()}", expanded=False):
                col1, col2 = st.columns([1, 3])
                with col1:
                    enabled = st.checkbox(
                        "Enabled",
                        value=cfg.get("stages", {}).get(s, {}).get("enabled", True),
                        key=f"en_{s}",
                    )
                    cfg["stages"].setdefault(s, {})["enabled"] = enabled
                with col2:
                    params_str = json.dumps(cfg["stages"][s].get("params", {}), indent=2)
                    new_params = st.text_area(
                        "Parameters (JSON)", value=params_str, height=800, key=f"pa_{s}"
                    )
                    try:
                        cfg["stages"][s]["params"] = json.loads(new_params)
                    except Exception:
                        st.error(f"Invalid JSON for {s} parameters; keeping previous")

    with tabs[1]:
        st.subheader("People Directory Maintenance")

        # Handle delete all flag
        if st.session_state.pop("delete_all_people_flag", False):
            st.session_state["confirm_del_all_people"] = False

        people_dir = load_people_directory()
        people_names = sorted(list(people_dir.keys()))

        st.markdown("**Bulk Operations**")
        confirm_del_all_people = st.checkbox(
            "Confirm delete ALL people (roles & knowledge will be lost).",
            key="confirm_del_all_people",
        )
        if st.button(
            "Delete ALL People",
            disabled=not confirm_del_all_people,
            key="btn_delete_all_people",
        ):
            save_people_directory({})
            st.success("People directory cleared")
            st.session_state["delete_all_people_flag"] = True
            st.rerun()

        if people_names:
            st.markdown("**Individual Deletion**")
            del_person = st.selectbox(
                "Select Person to Delete",
                options=["(select)"] + people_names,
                key="delete_person_select",
            )
            if del_person != "(select)":
                confirm_del_person = st.checkbox(
                    f"Confirm delete person '{del_person}'", key=f"confirm_del_person_{del_person}"
                )
                if st.button(
                    "Delete Person",
                    disabled=not confirm_del_person,
                    key="btn_delete_person",
                ):
                    people_dir.pop(del_person, None)
                    save_people_directory(people_dir)
                    st.success(f"Deleted person: {del_person}")
                    st.rerun()
        else:
            st.info("No people in directory")

    with tabs[2]:
        st.subheader("TRC / Incident Library Maintenance")

        # Handle delete all flag
        if st.session_state.pop("delete_all_incidents_flag", False):
            st.session_state["confirm_del_all_incidents"] = False

        incidents = list_incidents()
        incident_ids = [i.get("incident_id") for i in incidents]

        st.markdown("**Bulk Operations**")
        confirm_del_all_incidents = st.checkbox(
            "Confirm delete ALL incidents, TRCs, artifacts & uploads.",
            key="confirm_del_all_incidents",
        )
        if st.button(
            "Delete ALL Incidents & TRCs",
            disabled=not confirm_del_all_incidents,
            key="btn_delete_all_incidents",
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
            st.session_state["delete_all_incidents_flag"] = True
            st.rerun()

        if incident_ids:
            st.markdown("**Individual Operations**")
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

                if trc_labels:
                    trc_options = [
                        f"{t.get('trc_id')} - {inc_doc.get('title', 'No Title')}" for t in trcs
                    ]
                    sel_trc_display = st.selectbox(
                        "Select TRC to Delete",
                        options=["(none)"] + trc_options,
                        key=f"maintenance_select_trc_{sel_inc}",
                    )
                    # Extract the actual trc_id from the selection
                    if sel_trc_display != "(none)":
                        sel_trc = sel_trc_display.split(" - ")[0]
                    else:
                        sel_trc = "(none)"
                    if sel_trc != "(none)":
                        confirm_del_trc = st.checkbox(
                            f"Confirm delete TRC '{sel_trc}'", key=f"confirm_del_trc_{sel_trc}"
                        )
                        if st.button(
                            "Delete Selected TRC",
                            disabled=not confirm_del_trc,
                            key=f"btn_delete_trc_{sel_inc}",
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

                confirm_del_inc = st.checkbox(
                    f"Confirm delete incident '{sel_inc}' and ALL its TRCs",
                    key=f"confirm_del_inc_{sel_inc}",
                )
                if st.button(
                    "Delete Entire Incident",
                    disabled=not confirm_del_inc,
                    key=f"btn_delete_inc_{sel_inc}",
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
        else:
            st.info("No incidents in library")

    # Save button outside tabs
    st.markdown("---")
    if st.button("Save Configuration", type="primary"):
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
