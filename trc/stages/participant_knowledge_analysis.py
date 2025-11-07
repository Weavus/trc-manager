from __future__ import annotations

import json
import re
from typing import Any

from ..llm import create_client_from_config
from .base import RunContext, StageOutput


class ParticipantKnowledgeAnalysisStage:
    name = "participant_knowledge_analysis"
    inputs = ["noise_reduction", "participant_role_analysis"]
    outputs = ["participant_knowledge_analysis", "participant_analysis"]
    depends_on = ["participant_role_analysis"]

    def run(self, ctx: RunContext, params: dict[str, Any] | None = None) -> StageOutput:
        text = ctx.trc.get("pipeline_outputs", {}).get("noise_reduction", "")
        # Get roles from the previous stage
        role_analysis = ctx.trc.get("pipeline_outputs", {}).get("participant_role_analysis", {})
        existing_roles = role_analysis.get("roles", [])

        cfg = params or {}
        llm_config = cfg.get("llm")

        if llm_config:
            # Use LLM for participant knowledge analysis
            try:
                llm_client = create_client_from_config(ctx.incident.get("llm", {}))
                prompt_file = llm_config["prompt_file"]

                # Pass both transcript and existing roles for context
                roles_context = (
                    json.dumps(existing_roles, indent=2)
                    if existing_roles
                    else "No roles identified yet."
                )

                payload = llm_client.call_llm_json_with_prompt_file(
                    prompt_file=prompt_file,
                    transcript=text,
                    existing_roles=roles_context,
                )

                knowledge = payload.get("knowledge", [])

                # Build people directory updates for knowledge only
                updates: dict[str, dict[str, Any]] = {}
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

                raw_llm_output = json.dumps({"knowledge": knowledge}, indent=2)

                # Combine with role analysis for backward compatibility
                combined_payload = {"roles": existing_roles, "knowledge": knowledge}

                return StageOutput(
                    trc_outputs={
                        "participant_knowledge_analysis": {"knowledge": knowledge},
                        "participant_analysis": combined_payload,  # Maintain backward compatibility
                    },
                    trc_artifacts_json={
                        "participant_knowledge_analysis_llm_output": {"knowledge": knowledge},
                        "participant_analysis_llm_output": combined_payload,
                    },
                    trc_artifacts_text={
                        "participant_knowledge_analysis_llm_output_raw": raw_llm_output,
                        "participant_analysis_llm_output_raw": json.dumps(
                            combined_payload, indent=2
                        ),
                    },
                    people_directory_updates=updates,
                    input_info=f"Input: {len(text)} chars, Roles: {len(existing_roles)}",
                    output_info=f"Knowledge: {len(knowledge)} (LLM processed)",
                    messages=["Used LLM for participant knowledge analysis"],
                )
            except Exception as e:
                # Fallback to heuristic approach if LLM fails
                print(f"LLM participant knowledge analysis failed: {e}, falling back to heuristic")

        # Fallback: heuristic-based participant knowledge analysis
        names = set(re.findall(r"([A-Z][a-z]+\s+[A-Z][a-z]+)", text))
        knowledge: list[dict[str, Any]] = []
        updates: dict[str, dict[str, Any]] = {}
        for n in names:
            raw = n.lower()
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
        for entry in knowledge:
            entry_copy = dict(entry)
            entry_copy["incident_id"] = ctx.incident_id
            entry_copy["trc_id"] = ctx.trc_id
            updates[entry["raw_name"]].setdefault("discovered_knowledge", []).append(entry_copy)

        raw_llm_output = json.dumps({"knowledge": knowledge}, indent=2)

        # Combine with role analysis for backward compatibility
        combined_payload = {"roles": existing_roles, "knowledge": knowledge}

        return StageOutput(
            trc_outputs={
                "participant_knowledge_analysis": {"knowledge": knowledge},
                "participant_analysis": combined_payload,  # Maintain backward compatibility
            },
            trc_artifacts_json={
                "participant_knowledge_analysis_llm_output": {"knowledge": knowledge},
                "participant_analysis_llm_output": combined_payload,
            },
            trc_artifacts_text={
                "participant_knowledge_analysis_llm_output_raw": raw_llm_output,
                "participant_analysis_llm_output_raw": json.dumps(combined_payload, indent=2),
            },
            people_directory_updates=updates,
            input_info=f"Input: {len(text)} chars, Roles: {len(existing_roles)}",
            output_info=f"Knowledge: {len(knowledge)}",
        )
