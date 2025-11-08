from __future__ import annotations

import logging
from typing import Any

from ..llm import PromptTemplate, create_client_from_config
from .base import RunContext, StageOutput

logger = logging.getLogger(__name__)


class MasterSummarySynthesisStage:
    name = "master_summary_synthesis"
    inputs = []  # This stage reads from incident-level data, not pipeline_outputs
    outputs = ["master_summary_synthesis"]
    depends_on = ["summarisation"]  # Depends on all TRCs having summarisation completed

    def run(self, ctx: RunContext, params: dict[str, Any] | None = None) -> StageOutput:
        logger.info(
            f"Starting master summary synthesis for incident {ctx.incident_id}, TRC {ctx.trc_id}"
        )
        current_summary = ctx.trc.get("pipeline_outputs", {}).get("summarisation", "")
        existing_master = ctx.incident.get("master_summary", "")
        logger.debug(
            f"Current summary length: {len(current_summary)}, "
            f"existing master length: {len(existing_master)}"
        )
        cfg = params or {}
        llm_config = cfg.get("llm")

        if not current_summary:
            logger.warning("No current summary for this TRC, skipping master summary synthesis")
            return StageOutput(
                input_info="No current summary",
                output_info="Skipped",
            )

        if llm_config:
            llm_client = create_client_from_config(ctx.llm_config or {})
            prompt_file = llm_config["prompt_file"]
            template = PromptTemplate(prompt_file)

            if existing_master:
                # Synthesize with existing master
                logger.debug("Synthesizing with existing master summary")
                rendered_prompt = template.render(
                    previous_master_summary=existing_master,
                    current_reconvene_summary=current_summary,
                )
            else:
                # First summary, just use it as master
                logger.debug("Setting first summary as master")
                return StageOutput(
                    incident_updates={"master_summary": current_summary},
                    incident_artifacts_text={"master_summary_raw_llm_output": current_summary},
                    input_info="First summary",
                    output_info=f"Master summary: {len(current_summary)} chars (first)",
                    messages=["Set first summary as master"],
                )

            params = template.get_llm_params()

            out_dir = ctx.artifacts_dir / ctx.incident_id / ctx.trc_id
            out_dir.mkdir(parents=True, exist_ok=True)
            request_file = out_dir / "master_summary_synthesis_llm_request.txt"
            request_file.write_text(rendered_prompt, encoding="utf-8")

            master_summary = llm_client.call_llm(prompt=rendered_prompt, **params).strip()

            logger.info(
                f"Master summary synthesis completed using LLM: {len(master_summary)} chars output"
            )
            return StageOutput(
                incident_updates={"master_summary": master_summary},
                incident_artifacts_text={"master_summary_raw_llm_output": master_summary},
                input_info=f"Previous: {len(existing_master)} chars, "
                f"Current: {len(current_summary)} chars",
                output_info=f"Master summary: {len(master_summary)} chars (LLM processed)",
                messages=["Used LLM for master summary synthesis"],
            )
        else:
            logger.warning("No LLM config for master summary synthesis, using fallback")
            if not existing_master:
                # First summary
                return StageOutput(
                    incident_updates={"master_summary": current_summary},
                    incident_artifacts_text={"master_summary_raw_llm_output": current_summary},
                    input_info="No LLM, setting current as master",
                    output_info=f"Master summary: {len(current_summary)} chars (no LLM)",
                )
            else:
                # Concatenate for fallback
                combined = existing_master + "\n\n" + current_summary
                return StageOutput(
                    incident_updates={"master_summary": combined},
                    incident_artifacts_text={"master_summary_raw_llm_output": combined},
                    input_info="No LLM, concatenated summaries",
                    output_info=f"Master summary: {len(combined)} chars (concatenated)",
                )
