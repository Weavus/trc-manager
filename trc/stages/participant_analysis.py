from __future__ import annotations

import json
import re
from typing import Any

from ..llm import create_client_from_config, PromptTemplate
from .base import RunContext, StageOutput

logger = logging.getLogger(__name__)


class ParticipantAnalysisStage:
    name = "participant_analysis"
    requires = ["noise_reduction"]

    def run(self, ctx: RunContext, params: dict[str, Any] | None = None) -> StageOutput:
        text = ctx.trc.get("pipeline_outputs", {}).get("noise_reduction", "")
        cfg = params or {}
        llm_config = cfg.get("llm")

        if llm_config:
            # Use LLM for participant analysis
            try:
                llm_client = create_client_from_config(ctx.llm_config or {})
                prompt_file = llm_config["prompt_file"]

                template = PromptTemplate(prompt_file)
                rendered_prompt = template.render(transcript=text)
                params = template.get_llm_params()

                if logger.isEnabledFor(logging.DEBUG):
                    # Save debug input
                    out_dir = ctx.artifacts_dir / ctx.incident_id / ctx.trc_id
                    out_dir.mkdir(parents=True, exist_ok=True)
                    input_file = out_dir / f"participant_analysis.{ctx.incident_id}.input"
                    input_file.write_text(rendered_prompt, encoding="utf-8")

                payload = llm_client.call_llm_json(prompt=rendered_prompt, **params)

                if logger.isEnabledFor(logging.DEBUG):
                    # Save debug output
                    output_file = out_dir / f"participant_analysis.{ctx.incident_id}.output"
                    output_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

                roles = payload.get("roles", [])
                knowledge = payload.get("knowledge", [])

                # Build people directory updates
                updates: dict[str, dict[str, Any]] = {}
                for entry in roles:
                    raw_name = entry["raw_name"]
                    updates.setdefault(
                        raw_name,
                        {
                            "raw_name": raw_name,
                            "display_name": entry["display_name"],
                            "role_override": None,
                            "discovered_roles": [],
                            "discovered_knowledge": [],
                        },
                    )
                    entry_copy = dict(entry)
                    entry_copy["incident_id"] = ctx.incident_id
                    entry_copy["trc_id"] = ctx.trc_id
                    updates[raw_name].setdefault("discovered_roles", []).append(entry_copy)

                for entry in knowledge:
                    raw_name = entry["raw_name"]
                    updates.setdefault(
                        raw_name,
                        {
                            "raw_name": raw_name,
                            "display_name": entry["display_name"],
                            "role_override": None,
                            "discovered_roles": [],
                            "discovered_knowledge": [],
                        },
                    )
                    entry_copy = dict(entry)
                    entry_copy["incident_id"] = ctx.incident_id
                    entry_copy["trc_id"] = ctx.trc_id
                    updates[raw_name].setdefault("discovered_knowledge", []).append(entry_copy)

                raw_llm_output = json.dumps(payload, indent=2)
                return StageOutput(
                    trc_outputs={"participant_analysis": payload},
                    trc_artifacts_json={"participant_analysis_llm_output": payload},
                    trc_artifacts_text={"participant_analysis_llm_output_raw": raw_llm_output},
                    people_directory_updates=updates,
                    input_info=f"Input: {len(text)} chars",
                    output_info=f"Roles: {len(roles)}, Knowledge: {len(knowledge)} (LLM processed)",
                    messages=["Used LLM for participant analysis"],
                )
            except Exception as e:
                # Fallback to heuristic approach if LLM fails
                print(f"LLM participant analysis failed: {e}, falling back to heuristic")

        # Fallback: heuristic-based participant analysis
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
