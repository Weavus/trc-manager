from __future__ import annotations

import json
import logging
from typing import Any

from ..llm import PromptTemplate, create_client_from_config
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
            llm_client = create_client_from_config(ctx.llm_config or {})
            prompt_file = llm_config["prompt_file"]

            template = PromptTemplate(prompt_file)
            rendered_prompt = template.render(transcript=text)
            params = template.get_llm_params()

            out_dir = ctx.artifacts_dir / ctx.incident_id / ctx.trc_id
            out_dir.mkdir(parents=True, exist_ok=True)
            request_file = out_dir / "participant_analysis_llm_request.txt"
            request_file.write_text(rendered_prompt, encoding="utf-8")

            response = llm_client.call_llm(prompt=rendered_prompt, **params)
            payload = json.loads(response)

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
        else:
            logger.warning("No LLM config for participant analysis, skipping")
            return StageOutput(
                trc_outputs={"participant_analysis": {"roles": [], "knowledge": []}},
                input_info=f"Input: {len(text)} chars",
                output_info="Roles: 0, Knowledge: 0 (no LLM)",
            )
