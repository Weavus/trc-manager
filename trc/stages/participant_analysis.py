from __future__ import annotations

import logging
import re
from typing import Any

from ..llm import PromptTemplate, create_client_from_config
from .base import RunContext, Stage, StageOutput

logger = logging.getLogger(__name__)


class ParticipantAnalysisStage(Stage):
    name = "participant_analysis"
    inputs = ["noise_reduction"]

    def run(self, ctx: RunContext, params: dict[str, Any] | None = None) -> StageOutput:
        logger.info(
            f"Starting participant analysis for incident {ctx.incident_id}, TRC {ctx.trc_id}"
        )
        text = ctx.trc.get("pipeline_outputs", {}).get("noise_reduction", "")
        logger.debug(f"Input text length: {len(text)} chars")
        cfg = params or {}
        llm_config = cfg.get("llm")

        # Load role_taxonomy from config
        import json
        from pathlib import Path

        role_taxonomy = {}
        try:
            config_path = Path(__file__).parent.parent.parent / "config.json"
            with config_path.open("r", encoding="utf-8") as f:
                global_config = json.load(f)
            role_taxonomy = global_config.get("role_taxonomy", {})
        except Exception as e:
            logger.warning(f"Failed to load role_taxonomy from config: {e}")

        # Extract participants and their texts
        participants = self._extract_participants(text)
        logger.debug(f"Extracted {len(participants)} participants")

        roles = []
        knowledge = []

        if llm_config and participants:
            logger.debug("Using LLM for participant analysis")
            try:
                llm_client = create_client_from_config(ctx.llm_config or {})
                prompt_file = llm_config["prompt_file"]
                template = PromptTemplate(prompt_file)

                out_dir = ctx.artifacts_dir / ctx.incident_id / ctx.trc_id
                out_dir.mkdir(parents=True, exist_ok=True)

                for participant, participant_text in participants.items():
                    logger.debug(f"Analyzing participant: {participant}")
                    rendered_prompt = template.render(
                        participant_name=participant,
                        role_taxonomy=self._format_role_taxonomy(role_taxonomy),
                        participant_dialogue=participant_text,
                    )
                    llm_params = template.get_llm_params()

                    request_file = out_dir / f"participant_analysis_{participant}_llm_request.txt"
                    request_file.write_text(rendered_prompt, encoding="utf-8")

                    response = llm_client.call_llm(prompt=rendered_prompt, **llm_params)
                    payload = json.loads(response)

                    # The payload is {"role": {...}, "knowledge": {...}}
                    role_data = payload.get("role", {})
                    if role_data:
                        role_entry = {
                            "raw_name": participant.lower(),
                            "display_name": participant,
                            "role": role_data.get("name", "Unknown"),
                            "reasoning": role_data.get("reasoning", ""),
                            "confidence_score": role_data.get("confidence_score", 0.0),
                        }
                        roles.append(role_entry)

                    knowledge_data = payload.get("knowledge", {})
                    if knowledge_data:
                        knowledge_entry = {
                            "raw_name": participant.lower(),
                            "display_name": participant,
                            "knowledge": knowledge_data.get("areas", "General TRC context"),
                            "reasoning": knowledge_data.get("reasoning", ""),
                            "confidence_score": knowledge_data.get("confidence_score", 0.0),
                        }
                        knowledge.append(knowledge_entry)

                logger.debug(
                    f"LLM identified {len(roles)} roles and {len(knowledge)} knowledge entries"
                )

            except Exception as e:
                logger.warning(f"LLM participant analysis failed: {e}, falling back to heuristic")
                roles, knowledge = self._heuristic_analysis(participants)

        else:
            roles, knowledge = self._heuristic_analysis(participants)

        payload = {"roles": roles, "knowledge": knowledge}

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
        logger.info(
            f"Participant analysis completed: {len(roles)} roles, {len(knowledge)} knowledge"
        )
        return StageOutput(
            trc_outputs={"participant_analysis": payload},
            trc_artifacts_json={"participant_analysis_llm_output": payload},
            trc_artifacts_text={"participant_analysis_llm_output_raw": raw_llm_output},
            people_directory_updates=updates,
            input_info=f"Input: {len(text)} chars",
            output_info=f"Roles: {len(roles)}, Knowledge: {len(knowledge)}",
            messages=["Used LLM for participant analysis"]
            if llm_config
            else ["Used heuristic for participant analysis"],
        )

    def _extract_participants(self, text: str) -> dict[str, str]:
        """Extract participants and their spoken text from the transcript."""
        participants: dict[str, list[str]] = {}
        lines = text.splitlines()
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # Match lines like "10:00 Alice Johnson: text" or "10:00: Alice Johnson: text"
            match = re.match(r"^\d{1,2}:\d{2}(?::\d{2})?\s+([^:]+?):\s*(.*)$", line)
            if match:
                speaker = match.group(1).strip()
                dialogue = match.group(2).strip()
                if speaker and dialogue:
                    participants.setdefault(speaker, []).append(dialogue)
            else:
                logger.debug(f"No match for line: {line[:100]}")
        # Concatenate dialogues for each participant
        result = {
            speaker: " ".join(dialogues) for speaker, dialogues in participants.items() if dialogues
        }
        logger.debug(f"Extracted participants: {list(result.keys())}")
        return result

    def _heuristic_analysis(
        self, participants: dict[str, str]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Fallback heuristic analysis."""
        roles = []
        knowledge = []
        for participant in participants:
            raw = participant.lower()
            roles.append(
                {
                    "raw_name": raw,
                    "display_name": participant,
                    "role": "Participant",
                    "reasoning": "Heuristic extraction placeholder.",
                    "confidence_score": 5.0,
                }
            )
            knowledge.append(
                {
                    "raw_name": raw,
                    "display_name": participant,
                    "knowledge": "General TRC context",
                    "reasoning": "Heuristic extraction placeholder.",
                    "confidence_score": 4.0,
                }
            )
        return roles, knowledge

    def _format_role_taxonomy(self, role_taxonomy: dict[str, Any]) -> str:
        """Format role taxonomy as a concise string to reduce token usage."""
        lines = []
        for role, data in role_taxonomy.items():
            desc = data.get("description", "")
            aliases = data.get("aliases", [])
            aliases_str = ", ".join(aliases) if aliases else "None"
            lines.append(f"- {role}: {desc} Aliases: {aliases_str}")
        return "\n".join(lines)
