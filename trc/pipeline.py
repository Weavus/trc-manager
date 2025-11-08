from __future__ import annotations

import importlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .stages import get_builtin_registry
from .stages.base import RunContext, Stage, StageOutput

DATA_DIR = Path("data")
INCIDENTS_DIR = DATA_DIR / "incidents"
PEOPLE_DIR = DATA_DIR / "people"
UPLOADS_DIR = DATA_DIR / "uploads"
ARTIFACTS_DIR = DATA_DIR / "artifacts"
CONFIG_PATH = Path("config.json")
STAGES_PATH = Path("stages.json")
PEOPLE_PATH = PEOPLE_DIR / "people_directory.json"

LOGGER = logging.getLogger("trc.pipeline")

INC_REGEX = re.compile(r"(INC\d{10,12})")
DT_REGEX = re.compile(r"(?<!\d)(\d{8}-\d{4})(?!\d)")


def _parse_iso_datetime_safe(s: str) -> datetime | None:
    try:
        if s and s.endswith("Z"):
            return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if s:
            return datetime.fromisoformat(s)
    except Exception:
        return None
    return None


_logging_initialized = False


def setup_logging(log_path: Path = Path("app.log"), level: str = "INFO") -> None:
    """Setup comprehensive logging configuration.

    Args:
        log_path: Path to log file
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    global _logging_initialized
    if _logging_initialized:
        return
    _logging_initialized = True

    # Convert string level to logging level
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    # Create formatters
    file_formatter = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)-30s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_formatter = logging.Formatter(
        "%(levelname)-8s %(name)-30s %(message)s"
    )

    # Setup root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Clear existing handlers
    root_logger.handlers.clear()

    # File handler - logs everything
    file_handler = logging.FileHandler(log_path)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)

    # Console handler - only INFO and above
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # Set specific loggers to DEBUG
    # Always enable debug logging for LLM interactions
    llm_logger = logging.getLogger("trc.llm")
    llm_logger.setLevel(logging.DEBUG)

    # Clear existing handlers to avoid duplicates
    llm_logger.handlers.clear()

    # Create dedicated LLM log file
    llm_log_path = Path("llm.log")
    llm_file_handler = logging.FileHandler(llm_log_path)
    llm_file_handler.setLevel(logging.DEBUG)
    llm_file_handler.setFormatter(file_formatter)
    llm_logger.addHandler(llm_file_handler)

    # Create a separate console handler for LLM debug messages
    llm_console_handler = logging.StreamHandler()
    llm_console_handler.setLevel(logging.DEBUG)
    llm_console_handler.setFormatter(console_formatter)
    llm_logger.addHandler(llm_console_handler)
    llm_logger.addHandler(file_handler)
    llm_logger.propagate = False  # Don't send to root logger

    if level.upper() == "DEBUG":
        # Enable debug logging for pipeline stages
        logging.getLogger("trc.stages").setLevel(logging.DEBUG)

    # Log the setup
    logger = logging.getLogger("trc.pipeline")
    logger.info(f"Logging initialized at level {level} to {log_path}")
    llm_logger = logging.getLogger("trc.llm")
    logger.info(f"LLM logger configured: level={llm_logger.level}, "
                f"propagate={llm_logger.propagate}, handlers={len(llm_logger.handlers)}")


# Helpers


def ensure_dirs() -> None:
    for d in (INCIDENTS_DIR, PEOPLE_DIR, UPLOADS_DIR, ARTIFACTS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def read_config() -> dict[str, Any]:
    """Read config.json with environment variable expansion."""
    # Load .env file if it exists
    load_dotenv()

    default_config = {
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

    config = read_json(CONFIG_PATH, default_config)

    # Expand environment variables in the config
    def expand_env_vars(obj: Any) -> Any:
        if isinstance(obj, str):
            return os.path.expandvars(obj)
        elif isinstance(obj, dict):
            return {k: expand_env_vars(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [expand_env_vars(item) for item in obj]
        else:
            return obj

    return expand_env_vars(config)


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


@dataclass
class PipelineResult:
    incident_id: str
    trc_id: str
    stage_logs: list[StageLog]
    success: bool
    failed_stage: str | None = None


# Dynamic stages loading


def _import_from_path(dotted: str) -> Any:
    module_path, _, attr = dotted.rpartition(".")
    if not module_path:
        raise ImportError(f"Invalid dotted path: {dotted}")
    mod = importlib.import_module(module_path)
    return getattr(mod, attr)


def load_stage_registry() -> tuple[dict[str, Stage], dict[str, dict[str, Any]]]:
    """Build a stage registry and params map from builtins + optional stages.json + config.json.

    Returns (registry, params_map)
    """
    # Start with built-in registry
    registry: dict[str, Stage] = get_builtin_registry().copy()
    params_map: dict[str, dict[str, Any]] = {}

    # Optional external stages.json: allows adding new stage impls
    spec = read_json(STAGES_PATH, {"stages": []})
    for item in spec.get("stages", []):
        name = item.get("name")
        impl = item.get("impl")
        inputs = item.get("inputs")
        outputs = item.get("outputs")
        depends_on = item.get("depends_on")
        if not name or not impl:
            continue
        cls = _import_from_path(impl)
        inst: Stage = cls()  # type: ignore[call-arg]
        # Override stage attributes if specified in stages.json
        if inputs is not None:
            if isinstance(inputs, (list, tuple)):
                inst.inputs = [str(i) for i in inputs]
            else:
                LOGGER.warning("Stage %s has invalid 'inputs' in stages.json", name)
        if outputs is not None:
            if isinstance(outputs, (list, tuple)):
                inst.outputs = [str(o) for o in outputs]
            else:
                LOGGER.warning("Stage %s has invalid 'outputs' in stages.json", name)
        if depends_on is not None:
            if isinstance(depends_on, (list, tuple)):
                inst.depends_on = [str(d) for d in depends_on]
            else:
                LOGGER.warning("Stage %s has invalid 'depends_on' in stages.json", name)
        registry[name] = inst
        if item.get("params"):
            params_map[name] = dict(item["params"])  # baseline params

    # Merge params from config.json
    config = read_config()
    for name, conf in config.get("stages", {}).items():
        if conf.get("params"):
            base = params_map.get(name, {})
            # config overrides stages.json
            params_map[name] = {**base, **conf["params"]}

    return registry, params_map


def _build_dependency_graph(registry: dict[str, Stage], enabled: set[str]) -> dict[str, set[str]]:
    """Build a dependency graph from stage inputs, outputs, and depends_on.

    Returns mapping: stage -> set(prereq_stage_names)
    """
    graph: dict[str, set[str]] = {s: set() for s in enabled if s in registry}

    # Build output-to-stage mapping for data dependencies
    output_producers: dict[str, set[str]] = {}
    for stage_name, stage in registry.items():
        if stage_name not in enabled:
            continue
        for output in getattr(stage, "outputs", []):
            output_producers.setdefault(output, set()).add(stage_name)

    # Build dependencies
    for stage_name, stage in registry.items():
        if stage_name not in graph:
            continue

        # Explicit stage dependencies
        for dep in getattr(stage, "depends_on", []):
            if dep in graph:
                graph[stage_name].add(dep)

        # Data dependencies based on inputs
        for input_key in getattr(stage, "inputs", []):
            if input_key == "raw_vtt":
                continue
            # Find stages that produce this input
            producers = output_producers.get(input_key, set())
            for producer in producers:
                if producer in graph and producer != stage_name:
                    graph[stage_name].add(producer)

    return graph


def _validate_stage_inputs(registry: dict[str, Stage], enabled: set[str]) -> list[str]:
    """Validate that all stage inputs are produced by some enabled stage.

    Returns list of error messages.
    """
    errors: list[str] = []

    # Collect all available outputs
    available_outputs: set[str] = {"raw_vtt"}  # raw_vtt is always available
    for stage_name, stage in registry.items():
        if stage_name in enabled:
            available_outputs.update(getattr(stage, "outputs", []))

    # Check each stage's inputs
    for stage_name, stage in registry.items():
        if stage_name not in enabled:
            continue
        for input_key in getattr(stage, "inputs", []):
            if input_key not in available_outputs:
                errors.append(
                    f"Stage '{stage_name}' requires input '{input_key}' "
                    "but no enabled stage produces it"
                )

    return errors


def _toposort_respecting_order(order: list[str], graph: dict[str, set[str]]) -> list[str]:
    """Return a stable topological ordering that respects the given order when possible.

    Raises ValueError if missing prereqs or cycles are detected.
    """
    nodes = [s for s in order if s in graph]
    present = set(nodes)

    errors: list[str] = []
    indeg: dict[str, int] = {s: 0 for s in nodes}
    adj: dict[str, set[str]] = {s: set() for s in nodes}

    # Build indegree/adj and check for missing prereqs
    for s in nodes:
        for p in graph[s]:
            if p not in present:
                errors.append(f"Stage '{s}' depends on missing or disabled '{p}'")
            else:
                indeg[s] += 1
                adj[p].add(s)

    if errors:
        raise ValueError("; ".join(errors))

    # Kahn's algorithm, using the given order as the queue order
    remaining: dict[str, int] = indeg.copy()
    queue = [s for s in nodes if remaining[s] == 0]
    # preserve order
    queue.sort(key=lambda x: nodes.index(x))
    out: list[str] = []

    while queue:
        n = queue.pop(0)
        out.append(n)
        for m in adj[n]:
            remaining[m] -= 1
            if remaining[m] == 0:
                queue.append(m)
                queue.sort(key=lambda x: nodes.index(x))

    if len(out) != len(nodes):
        raise ValueError("Dependency cycle detected among stages")

    return out


def _collect_prereqs(graph: dict[str, set[str]], start: str) -> set[str]:
    visited: set[str] = set()

    def dfs(n: str) -> None:
        for p in graph.get(n, set()):
            if p not in visited:
                visited.add(p)
                dfs(p)

    dfs(start)
    return visited


# 4.3 Pipeline Runner (modular)


def process_pipeline(
    vtt_content: str,
    incident_id: str,
    start_time_iso: str,
    *,
    start_stage: str | None = None,
) -> PipelineResult:
    ensure_dirs()

    # Load config and registry
    config = read_config()
    registry, params_map = load_stage_registry()

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

    # Get LLM config for stages
    llm_config = config.get("llm", {})

    trc_id = f"trc_{start_time_iso}"
    trc = next((t for t in incident.get("trcs", []) if t.get("trc_id") == trc_id), None)
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

    # Helpers to persist outputs/artifacts
    def save_trc_output(key: str, value: Any) -> None:
        trc.setdefault("pipeline_outputs", {})[key] = value
        write_json(incident_path, incident)

    def save_trc_artifact_text(key: str, content: str) -> str:
        out_dir = ARTIFACTS_DIR / incident_id / trc_id
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / f"{key}.txt"
        file_path.write_text(content, encoding="utf-8")
        trc.setdefault("pipeline_artifacts", {})[key] = str(file_path)
        write_json(incident_path, incident)
        return str(file_path)

    def save_trc_artifact_json(key: str, data: Any) -> str:
        out_dir = ARTIFACTS_DIR / incident_id / trc_id
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / f"{key}.json"
        write_json(file_path, data)
        trc.setdefault("pipeline_artifacts", {})[key] = str(file_path)
        write_json(incident_path, incident)
        return str(file_path)

    def save_incident_artifact_text(key: str, content: str) -> str:
        out_dir = ARTIFACTS_DIR / incident_id
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / f"{key}.txt"
        file_path.write_text(content, encoding="utf-8")
        incident.setdefault("pipeline_artifacts", {})[f"{key}_llm_output"] = str(file_path)
        write_json(incident_path, incident)
        return str(file_path)

    # Determine order and starting point
    enabled_order: list[str] = [
        s
        for s in config.get("pipeline_order", [])
        if config.get("stages", {}).get(s, {}).get("enabled", True)
    ]

    # Validate stage inputs and dependencies
    input_errors = _validate_stage_inputs(registry, set(enabled_order))
    if input_errors:
        msg = f"Pipeline configuration error: {'; '.join(input_errors)}"
        LOGGER.error(msg)
        return PipelineResult(
            incident_id=incident_id,
            trc_id=f"trc_{start_time_iso}",
            stage_logs=[StageLog("config", "Failed", 0.0, messages=input_errors)],
            success=False,
            failed_stage="config",
        )

    # Validate and topologically sort the enabled order
    dep_graph = _build_dependency_graph(registry, set(enabled_order))
    try:
        enabled_order = _toposort_respecting_order(enabled_order, dep_graph)
    except ValueError as ve:
        # Surface as a pipeline failure early with a clear message
        msg = f"Pipeline configuration error: {ve}"
        LOGGER.error(msg)
        return PipelineResult(
            incident_id=incident_id,
            trc_id=f"trc_{start_time_iso}",
            stage_logs=[StageLog("config", "Failed", 0.0, messages=[str(ve)])],
            success=False,
            failed_stage="config",
        )

    if start_stage and start_stage in enabled_order:
        # Backfill prerequisites: start from earliest prereq of the chosen stage
        prereqs = _collect_prereqs(dep_graph, start_stage)
        candidates = [s for s in enabled_order if s in prereqs or s == start_stage]
        start_idx = (
            enabled_order.index(candidates[0]) if candidates else enabled_order.index(start_stage)
        )
    else:
        start_idx = 0

    for stage_name in enabled_order[start_idx:]:
        t0 = time.perf_counter()
        stage = registry.get(stage_name)
        if not stage:
            stage_logs.append(
                StageLog(stage_name, "Skipped", 0.0, messages=["Unknown stage, skipped"])
            )
            continue

        # Validate that required inputs are available
        missing_inputs = []
        for input_key in getattr(stage, "inputs", []):
            if input_key not in trc.get("pipeline_outputs", {}):
                missing_inputs.append(input_key)

        if missing_inputs:
            error_msg = f"Missing required inputs: {', '.join(missing_inputs)}"
            stage_logs.append(
                StageLog(stage_name, "Failed", time.perf_counter() - t0, messages=[error_msg])
            )
            return PipelineResult(
                incident_id=incident_id,
                trc_id=trc_id,
                stage_logs=stage_logs,
                success=False,
                failed_stage=stage_name,
            )

        # Build run context
        ctx = RunContext(
            incident_id=incident_id,
            trc_id=trc_id,
            incident=incident,
            trc=trc,
            data_dir=DATA_DIR,
            incidents_dir=INCIDENTS_DIR,
            people_path=PEOPLE_PATH,
            artifacts_dir=ARTIFACTS_DIR,
            llm_config=llm_config,
            start_dt=_parse_iso_datetime_safe(start_time_iso),
        )
        params = params_map.get(stage_name, {})

        try:
            result: StageOutput = stage.run(ctx, params)
            # Persist trc outputs
            for k, v in result.trc_outputs.items():
                save_trc_output(k, v)
            # Persist trc artifacts
            for k, content in result.trc_artifacts_text.items():
                save_trc_artifact_text(k, content)
            for k, data in result.trc_artifacts_json.items():
                save_trc_artifact_json(k, data)
            # Merge incident updates
            if result.incident_updates:
                # Special handling for keywords: merge into set
                if "keywords" in result.incident_updates:
                    inc_kw = set(incident.get("keywords", []))
                    for kw in result.incident_updates.get("keywords", []) or []:
                        inc_kw.add(kw)
                    incident["keywords"] = sorted(inc_kw)
                # Title/master_summary and others override if provided
                for k, v in result.incident_updates.items():
                    if k == "keywords":
                        continue
                    incident[k] = v
                write_json(incident_path, incident)
            # Persist incident artifacts (text)
            for k, content in result.incident_artifacts_text.items():
                save_incident_artifact_text(k, content)
            # People directory delta merges
            if result.people_directory_updates:
                ppl = read_json(PEOPLE_PATH, {})
                for raw_name, delta in result.people_directory_updates.items():
                    person = ppl.setdefault(
                        raw_name,
                        {
                            "raw_name": raw_name,
                            "display_name": delta.get("display_name", raw_name.title()),
                            "role_override": None,
                            "discovered_roles": [],
                            "discovered_knowledge": [],
                        },
                    )
                    # Append new entries if present
                    for entry in delta.get("discovered_roles", []):
                        person.setdefault("discovered_roles", []).append(entry)
                    for entry in delta.get("discovered_knowledge", []):
                        person.setdefault("discovered_knowledge", []).append(entry)
                write_json(PEOPLE_PATH, ppl)

            stage_logs.append(
                StageLog(
                    stage_name,
                    "Completed",
                    time.perf_counter() - t0,
                    input_info=result.input_info,
                    output_info=result.output_info,
                    messages=result.messages,
                )
            )
        except Exception as e:  # pragma: no cover
            msg = f"Stage {stage_name} failed: {e}"
            LOGGER.exception(msg)
            stage_logs.append(
                StageLog(stage_name, "Failed", time.perf_counter() - t0, messages=[str(e)])
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


# Convenience functions used by app


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


# Stage isolation helper


def run_stage_in_isolation(
    stage_name: str,
    ctx_data: dict[str, Any],
    params: dict[str, Any] | None = None,
) -> StageOutput:
    """Run a single stage in isolation for debugging/testing.

    ctx_data must include: incident_id, trc_id, incident, trc.
    """
    registry, _ = load_stage_registry()
    stage = registry.get(stage_name)
    if not stage:
        raise ValueError(f"Unknown stage: {stage_name}")
    ctx = RunContext(
        incident_id=ctx_data["incident_id"],
        trc_id=ctx_data["trc_id"],
        incident=ctx_data["incident"],
        trc=ctx_data["trc"],
        data_dir=DATA_DIR,
        incidents_dir=INCIDENTS_DIR,
        people_path=PEOPLE_PATH,
        artifacts_dir=ARTIFACTS_DIR,
    )
    return stage.run(ctx, params or {})
