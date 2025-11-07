from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol


@dataclass
class RunContext:
    incident_id: str
    trc_id: str
    incident: dict[str, Any]
    trc: dict[str, Any]
    data_dir: Path
    incidents_dir: Path
    people_path: Path
    artifacts_dir: Path
    start_dt: datetime | None = None


@dataclass
class StageOutput:
    # Values to persist under trc["pipeline_outputs"]
    trc_outputs: dict[str, Any] = field(default_factory=dict)
    # Text and JSON artifacts to persist under trc-level artifacts directory
    trc_artifacts_text: dict[str, str] = field(default_factory=dict)
    trc_artifacts_json: dict[str, Any] = field(default_factory=dict)
    # Incident-level updates and artifacts
    incident_updates: dict[str, Any] = field(default_factory=dict)
    incident_artifacts_text: dict[str, str] = field(default_factory=dict)
    incident_artifacts_json: dict[str, Any] = field(default_factory=dict)
    # People directory updates: map of raw_name -> person delta structure to merge
    people_directory_updates: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Logging helpers
    input_info: str = ""
    output_info: str = ""
    messages: list[str] = field(default_factory=list)


class Stage(Protocol):
    name: str
    # Pipeline output keys that this stage consumes as inputs
    inputs: list[str]
    # Pipeline output keys that this stage produces as outputs
    outputs: list[str]
    # Stage names that must complete before this stage can run (for ordering)
    depends_on: list[str]

    def run(self, ctx: RunContext, params: dict[str, Any] | None = None) -> StageOutput:  # noqa: D401
        """Execute the stage and return structured outputs/artifacts."""
        ...
