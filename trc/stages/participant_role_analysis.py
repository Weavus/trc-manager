from __future__ import annotations

import json
import logging
import re
from typing import Any

from ..llm import create_client_from_config
from .base import RunContext, StageOutput

logger = logging.getLogger(__name__)


class ParticipantRoleAnalysisStage:
    name = "participant_role_analysis"
    inputs = ["noise_reduction"]
    outputs = ["participant_role_analysis"]
    depends_on = []

    def run(self, ctx: RunContext, params: dict[str, Any] | None = None) -> StageOutput:
        logger.info(f"Starting participant role analysis for incident {ctx.incident_id}, TRC {ctx.trc_id}")
        text = ctx.trc.get("pipeline_outputs", {}).get("noise_reduction", "")
        logger.debug(f"Input text length: {len(text)} chars")
        cfg = params or {}
        llm_config = cfg.get("llm")

        if llm_config:
            logger.debug("Using LLM for participant role analysis")
            # Use LLM for participant role analysis
            try:
                llm_client = create_client_from_config(ctx.llm_config or {})
                prompt_file = llm_config["prompt_file"]

                payload = llm_client.call_llm_json_with_prompt_file(
                    prompt_file=prompt_file,
                    transcript=text,
                )

                roles = payload.get("roles", [])
                logger.debug(f"LLM identified {len(roles)} participant roles")

                # Build people directory updates for roles only
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

                raw_llm_output = json.dumps({"roles": roles}, indent=2)
                logger.info(f"Participant role analysis completed using LLM: {len(roles)} roles identified")
                return StageOutput(
                    trc_outputs={"participant_role_analysis": {"roles": roles}},
                    trc_artifacts_json={"participant_role_analysis_llm_output": {"roles": roles}},
                    trc_artifacts_text={"participant_role_analysis_llm_output_raw": raw_llm_output},
                    people_directory_updates=updates,
                    input_info=f"Input: {len(text)} chars",
                    output_info=f"Roles: {len(roles)} (LLM processed)",
                    messages=["Used LLM for participant role analysis"],
                )
            except Exception as e:
                # Fallback to heuristic approach if LLM fails
                logger.warning(f"LLM participant role analysis failed: {e}, falling back to heuristic")

        # Fallback: heuristic-based participant role analysis
        logger.debug("Using heuristic-based participant role analysis")
        names = set(re.findall(r"([A-Z][a-z]+\s+[A-Z][a-z]+)", text))
        logger.debug(f"Heuristic extraction found {len(names)} potential participant names")
        roles: list[dict[str, Any]] = []
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

        raw_llm_output = json.dumps({"roles": roles}, indent=2)
        logger.info(f"Participant role analysis completed using heuristic: {len(roles)} roles identified")
        return StageOutput(
            trc_outputs={"participant_role_analysis": {"roles": roles}},
            trc_artifacts_json={"participant_role_analysis_llm_output": {"roles": roles}},
            trc_artifacts_text={"participant_role_analysis_llm_output_raw": raw_llm_output},
            people_directory_updates=updates,
            input_info=f"Input: {len(text)} chars",
            output_info=f"Roles: {len(roles)}",
        )
