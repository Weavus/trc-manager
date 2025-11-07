from __future__ import annotations

import json
import re
from typing import Any

from .base import RunContext, StageOutput


class ParticipantAnalysisStage:
    name = "participant_analysis"
    requires = ["noise_reduction"]

    def run(self, ctx: RunContext, params: dict[str, Any] | None = None) -> StageOutput:
        text = ctx.trc.get("pipeline_outputs", {}).get("noise_reduction", "")
        names = set(re.findall(r"([A-Z][a-z]+\s+[A-Z][a-z]+)", text))
        roles: list[dict[str, Any]] = []
        knowledge: list[dict[str, Any]] = []
        updates: dict[str, dict[str, Any]] = {}
        for n in names:
            raw = n.lower()
            roles.append(
                {
                    "raw_name": raw,
                    "display_name": n,
                    "role": "Participant",
                    "reasoning": "Heuristic extraction placeholder.",
                    "confidence_score": 5.0,
                }
            )
            knowledge.append(
                {
                    "raw_name": raw,
                    "display_name": n,
                    "knowledge": "General TRC context",
                    "reasoning": "Heuristic extraction placeholder.",
                    "confidence_score": 4.0,
                }
            )
            updates.setdefault(
                raw,
                {
                    "raw_name": raw,
                    "display_name": n,
                    "role_override": None,
                    "discovered_roles": [],
                    "discovered_knowledge": [],
                },
            )
        # build delta lists including incident/trc linkage
        for entry in roles:
            entry_copy = dict(entry)
            entry_copy["incident_id"] = ctx.incident_id
            entry_copy["trc_id"] = ctx.trc_id
            updates[entry["raw_name"]].setdefault("discovered_roles", []).append(entry_copy)
        for entry in knowledge:
            entry_copy = dict(entry)
            entry_copy["incident_id"] = ctx.incident_id
            entry_copy["trc_id"] = ctx.trc_id
            updates[entry["raw_name"]].setdefault("discovered_knowledge", []).append(entry_copy)

        payload = {"roles": roles, "knowledge": knowledge}
        raw_llm_output = json.dumps(payload, indent=2)
        return StageOutput(
            trc_outputs={"participant_analysis": payload},
            trc_artifacts_json={"participant_analysis_llm_output": payload},
            trc_artifacts_text={"participant_analysis_llm_output_raw": raw_llm_output},
            people_directory_updates=updates,
            input_info=f"Input: {len(text)} chars",
            output_info=(f"Roles: {len(roles)}, Knowledge: {len(knowledge)}"),
        )
