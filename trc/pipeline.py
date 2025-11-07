from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DATA_DIR = Path("data")
INCIDENTS_DIR = DATA_DIR / "incidents"
PEOPLE_DIR = DATA_DIR / "people"
UPLOADS_DIR = DATA_DIR / "uploads"
ARTIFACTS_DIR = DATA_DIR / "artifacts"
CONFIG_PATH = Path("config.json")
PEOPLE_PATH = PEOPLE_DIR / "people_directory.json"

LOGGER = logging.getLogger("trc.pipeline")

INC_REGEX = re.compile(r"(INC\d{10,12})")
DT_REGEX = re.compile(r"(\d{8}-\d{4})")


@dataclass
class StageLog:
    name: str
    status: str
    duration_s: float
    input_info: str = ""
    output_info: str = ""
    messages: list[str] = field(default_factory=list)


def setup_logging(log_path: Path = Path("app.log")) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_path),
            logging.StreamHandler(),
        ],
    )


# 4.2 Pipeline Stages (Placeholders)

def stage_cleanup(raw_vtt_content: str) -> str:
    # Placeholder: strip VTT cues and timestamps very naively
    lines = []
    for line in raw_vtt_content.splitlines():
        if re.match(r"^\d{2}:\d{2}:\d{2}\.\d{3} --> ", line):
            continue
        if line.strip().upper() in {"WEBVTT", "NOTE"}:
            continue
        if line.strip() == "":
            continue
        lines.append(line)
    return " ".join(lines)


def stage_refinement(cleaned_text: str) -> str:
    # Placeholder: collapse whitespace and simple fixes
    text = re.sub(r"\s+", " ", cleaned_text).strip()
    return text


def stage_people_extraction(refined_text: str) -> tuple[dict[str, Any], str]:
    # Placeholder: no LLM. Extract capitalized word pairs as names
    names = set(re.findall(r"([A-Z][a-z]+\s+[A-Z][a-z]+)", refined_text))
    roles = []
    knowledge = []
    for n in names:
        raw = n.lower()
        roles.append({
            "raw_name": raw,
            "display_name": n,
            "role": "Participant",
            "reasoning": "Heuristic extraction placeholder.",
            "confidence_score": 5.0,
        })
        knowledge.append({
            "raw_name": raw,
            "display_name": n,
            "knowledge": "General TRC context",
            "reasoning": "Heuristic extraction placeholder.",
            "confidence_score": 4.0,
        })
    payload = {"roles": roles, "knowledge": knowledge}
    raw_llm_output = json.dumps(payload, indent=2)
    return payload, raw_llm_output


def stage_summarisation(
    refined_text: str,
    current_incident_title: str | None,
) -> tuple[str | None, str, str]:
    # Placeholder: first sentence as title if not present
    title = None
    if not current_incident_title:
        title = (refined_text[:60] + "...") if len(refined_text) > 60 else refined_text
    summary = (
        f"{title or current_incident_title or 'Incident'} - Summary:\n\n"
        + refined_text[:2000]
    )
    raw = summary
    return title, summary, raw


def stage_keyword_extraction(refined_text: str) -> list[str]:
    # Placeholder: top 5 frequent words > 5 chars
    words = re.findall(r"[a-zA-Z]{6,}", refined_text.lower())
    freq: dict[str, int] = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    return [w for w, _ in sorted(freq.items(), key=lambda x: (-x[1], x[0]))[:5]]


def stage_master_summary(all_trc_summaries: list[str]) -> tuple[str, str]:
    text = "\n\n".join(all_trc_summaries)
    raw = text
    return text, raw


# Helpers

def ensure_dirs() -> None:
    for d in (INCIDENTS_DIR, PEOPLE_DIR, UPLOADS_DIR, ARTIFACTS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def parse_filename(filename: str) -> tuple[str | None, str | None]:
    inc = None
    dt = None
    m1 = INC_REGEX.search(filename)
    if m1:
        inc = m1.group(1)
    m2 = DT_REGEX.search(filename)
    if m2:
        dt = m2.group(1)
    return inc, dt


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class PipelineResult:
    incident_id: str
    trc_id: str
    stage_logs: list[StageLog]
    success: bool
    failed_stage: str | None = None


# 4.3 Pipeline Runner

def process_pipeline(
    vtt_content: str,
    incident_id: str,
    start_time_iso: str,
    *,
    start_stage: str | None = None,
) -> PipelineResult:
    ensure_dirs()
    config = read_json(
        CONFIG_PATH,
        {
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
        },
    )

    incident_path = INCIDENTS_DIR / f"{incident_id}.json"
    incident = read_json(
        incident_path,
        {
            "incident_id": incident_id,
            "title": "",
            "keywords": [],
            "master_summary": "",
            "pipeline_artifacts": {},
            "trcs": [],
        },
    )

    trc_id = f"trc_{start_time_iso}"
    trc = next(
        (t for t in incident.get("trcs", []) if t.get("trc_id") == trc_id),
        None,
    )
    if not trc:
        trc = {
            "trc_id": trc_id,
            "start_time": start_time_iso,
            "original_filename": "",
            "original_filepath": "",
            "file_hash": "",
            "status": "processing",
            "pipeline_outputs": {
                "raw_vtt": vtt_content,
            },
            "pipeline_artifacts": {},
        }
        incident["trcs"].append(trc)
        write_json(incident_path, incident)

    stage_logs: list[StageLog] = []

    # helpers to set outputs
    def set_output(key: str, value: Any) -> None:
        trc["pipeline_outputs"][key] = value
        write_json(incident_path, incident)

    def set_artifact(key: str, content: str) -> str:
        out_dir = ARTIFACTS_DIR / incident_id / trc_id
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / f"{key}.txt"
        file_path.write_text(content, encoding="utf-8")
        trc["pipeline_artifacts"][key] = str(file_path)
        write_json(incident_path, incident)
        return str(file_path)

    def set_artifact_json(key: str, data: Any) -> str:
        out_dir = ARTIFACTS_DIR / incident_id / trc_id
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / f"{key}.json"
        write_json(file_path, data)
        trc["pipeline_artifacts"][key] = str(file_path)
        write_json(incident_path, incident)
        return str(file_path)

    # Determine start position
    order: list[str] = [
        s
        for s in config.get("pipeline_order", [])
        if config["stages"].get(s, {}).get("enabled", True)
    ]
    start_idx = order.index(start_stage) if start_stage and start_stage in order else 0

    # Inputs between stages
    current = vtt_content

    # If rerun starting at an intermediate stage, reuse saved output from prior stage
    if start_idx > 0:
        # Map of stage to the prior output key that feeds it
        input_map = {
            "refinement": "cleanup",
            "people_extraction": "refinement",
            "summarisation": "refinement",
            "keyword_extraction": "refinement",
        }
        start_name = order[start_idx]
        prior_key = input_map.get(start_name)
        if prior_key and prior_key in trc.get("pipeline_outputs", {}):
            current = trc["pipeline_outputs"][prior_key]

    for stage_name in order[start_idx:]:
        t0 = time.perf_counter()
        try:
            if stage_name == "cleanup":
                out = stage_cleanup(current)
                set_output("cleanup", out)
                current = out
                stage_logs.append(
                    StageLog(
                        stage_name,
                        "Completed",
                        time.perf_counter() - t0,
                        input_info=f"Input: {len(vtt_content)} chars",
                        output_info=f"Output: {len(out)} chars",
                    )
                )

            elif stage_name == "refinement":
                out = stage_refinement(current)
                set_output("refinement", out)
                current = out
                stage_logs.append(
                    StageLog(
                        stage_name,
                        "Completed",
                        time.perf_counter() - t0,
                        input_info=f"Input: {len(current)} chars",
                        output_info=f"Output: {len(out)} chars",
                    )
                )

            elif stage_name == "people_extraction":
                data, raw = stage_people_extraction(current)
                set_output("people_extraction", data)
                # Save raw LL output as JSON and text for readability
                set_artifact_json("people_extraction_llm_output", data)
                set_artifact("people_extraction_llm_output_raw", raw)
                # Side-effect: update people directory
                ppl = read_json(PEOPLE_PATH, {})
                person_keys = set()
                for k in ("roles", "knowledge"):
                    for entry in data.get(k, []):
                        raw_name = entry.get("raw_name", "").lower()
                        if not raw_name:
                            continue
                        person = ppl.setdefault(raw_name, {
                            "raw_name": raw_name,
                            "display_name": entry.get("display_name", raw_name.title()),
                            "role_override": None,
                            "discovered_roles": [],
                            "discovered_knowledge": [],
                        })
                        entry_copy = dict(entry)
                        entry_copy["incident_id"] = incident_id
                        entry_copy["trc_id"] = trc_id
                        if k == "roles":
                            person["discovered_roles"].append(entry_copy)
                        else:
                            person["discovered_knowledge"].append(entry_copy)
                        person_keys.add(raw_name)
                write_json(PEOPLE_PATH, ppl)
                stage_logs.append(
                    StageLog(
                        stage_name,
                        "Completed",
                        time.perf_counter() - t0,
                        input_info=f"Input: {len(current)} chars",
                        output_info=(
                            f"Roles: {len(data.get('roles', []))}, "
                            f"Knowledge: {len(data.get('knowledge', []))}"
                        ),
                    )
                )

            elif stage_name == "summarisation":
                new_title, summary, raw = stage_summarisation(
                    current,
                    incident.get("title") or None,
                )
                set_output("summarisation", summary)
                set_artifact("summarisation_llm_output", raw)
                if new_title and not incident.get("title"):
                    incident["title"] = new_title
                    write_json(incident_path, incident)
                stage_logs.append(
                    StageLog(
                        stage_name,
                        "Completed",
                        time.perf_counter() - t0,
                        input_info=f"Input: {len(current)} chars",
                        output_info=f"Summary: {len(summary)} chars",
                    )
                )

            elif stage_name == "keyword_extraction":
                keywords = stage_keyword_extraction(current)
                set_output("keywords", keywords)
                inc_kw = set(incident.get("keywords", []))
                for kw in keywords:
                    inc_kw.add(kw)
                incident["keywords"] = sorted(inc_kw)
                write_json(incident_path, incident)
                stage_logs.append(
                    StageLog(
                        stage_name,
                        "Completed",
                        time.perf_counter() - t0,
                        input_info=f"Input: {len(current)} chars",
                        output_info=f"Keywords: {len(keywords)}",
                    )
                )

            elif stage_name == "master_summary":
                # collect all trc summaries
                summaries = [
                    t.get("pipeline_outputs", {}).get("summarisation", "")
                    for t in incident.get("trcs", [])
                ]
                ms, raw = stage_master_summary([s for s in summaries if s])
                incident["master_summary"] = ms
                write_json(incident_path, incident)
                # store artifact at incident level
                out_dir = ARTIFACTS_DIR / incident_id
                out_dir.mkdir(parents=True, exist_ok=True)
                master_file = out_dir / "master_summary_raw.txt"
                master_file.write_text(raw, encoding="utf-8")
                incident.setdefault("pipeline_artifacts", {})[
                    "master_summary_llm_output"
                ] = str(master_file)
                write_json(incident_path, incident)
                stage_logs.append(
                    StageLog(
                        stage_name,
                        "Completed",
                        time.perf_counter() - t0,
                        input_info=f"Summaries: {len(summaries)}",
                        output_info=f"Master summary: {len(ms)} chars",
                    )
                )

            else:
                stage_logs.append(
                    StageLog(
                        stage_name,
                        "Skipped",
                        0.0,
                        messages=["Unknown stage, skipped"],
                    )
                )

        except Exception as e:
            msg = f"Stage {stage_name} failed: {e}"
            LOGGER.exception(msg)
            stage_logs.append(
                StageLog(
                    stage_name,
                    "Failed",
                    time.perf_counter() - t0,
                    messages=[str(e)],
                )
            )
            return PipelineResult(
                incident_id=incident_id,
                trc_id=trc_id,
                stage_logs=stage_logs,
                success=False,
                failed_stage=stage_name,
            )

    trc["status"] = "processed"
    write_json(incident_path, incident)

    return PipelineResult(
        incident_id=incident_id,
        trc_id=trc_id,
        stage_logs=stage_logs,
        success=True,
    )


def list_incidents() -> list[dict[str, Any]]:
    ensure_dirs()
    incidents: list[dict[str, Any]] = []
    for f in INCIDENTS_DIR.glob("*.json"):
        inc = read_json(f, {})
        if inc:
            incidents.append(inc)
    return sorted(incidents, key=lambda x: x.get("incident_id", ""))


def load_people_directory() -> dict[str, Any]:
    ensure_dirs()
    return read_json(PEOPLE_PATH, {})


def save_people_directory(data: dict[str, Any]) -> None:
    write_json(PEOPLE_PATH, data)
