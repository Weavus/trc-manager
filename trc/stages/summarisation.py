from __future__ import annotations

import logging
from typing import Any

from ..llm import PromptTemplate, create_client_from_config
from .base import RunContext, StageOutput

logger = logging.getLogger(__name__)


class SummarisationStage:
    name = "summarisation"
    inputs = ["noise_reduction"]
    outputs = ["summarisation"]
    depends_on = []

    def run(self, ctx: RunContext, params: dict[str, Any] | None = None) -> StageOutput:
        logger.info(f"Starting summarisation for incident {ctx.incident_id}, TRC {ctx.trc_id}")
        text = ctx.trc.get("pipeline_outputs", {}).get("noise_reduction", "")
        logger.debug(f"Input text length: {len(text)} chars")
        cfg = params or {}
        llm_config = cfg.get("llm")

        if llm_config:
            logger.debug("Using LLM for summarization")
            # Use LLM for summarization
            llm_client = create_client_from_config(ctx.llm_config or {})
            prompt_file = llm_config["prompt_file"]

            template = PromptTemplate(prompt_file)
            rendered_prompt = template.render(incident_id=ctx.incident_id, meeting_dialogue=text)
            params = template.get_llm_params()

            out_dir = ctx.artifacts_dir / ctx.incident_id / ctx.trc_id
            out_dir.mkdir(parents=True, exist_ok=True)
            request_file = out_dir / "summarisation_llm_request.txt"
            request_file.write_text(rendered_prompt, encoding="utf-8")

            summary = llm_client.call_llm(prompt=rendered_prompt, **params).strip()

            incident_title = ctx.incident.get("title") or None
            title: str | None = None
            if not incident_title:
                # Try to extract title from the summary first line
                first_line = summary.split("\n", 1)[0].strip()
                if first_line.startswith(ctx.incident_id + " - "):
                    title = first_line[len(ctx.incident_id) + 3 :].strip()
                else:
                    # Fallback to text preview
                    title = (text[:60] + "...") if len(text) > 60 else text

            incident_updates: dict[str, Any] = {}
            if title and not (ctx.incident.get("title") or ""):
                incident_updates["title"] = title

            logger.info(f"Summarisation completed using LLM: {len(summary)} chars output")
            return StageOutput(
                trc_outputs={"summarisation": summary},
                trc_artifacts_text={"summarisation_llm_output": summary},
                incident_updates=incident_updates,
                input_info=f"Input: {len(text)} chars",
                output_info=f"Summary: {len(summary)} chars (LLM processed)",
                messages=["Used LLM for summarization"],
            )
        else:
            logger.warning("No LLM config for summarisation, skipping")
            return StageOutput(
                trc_outputs={"summarisation": ""},
                input_info=f"Input: {len(text)} chars",
                output_info="Summary: 0 chars (no LLM)",
            )
