from __future__ import annotations

import logging
from typing import Any

from ..llm import create_client_from_config
from .base import RunContext, StageOutput

logger = logging.getLogger(__name__)


class MasterSummarySynthesisStage:
    name = "master_summary_synthesis"
    inputs = []  # This stage reads from incident-level data, not pipeline_outputs
    outputs = ["master_summary_synthesis"]
    depends_on = ["summarisation"]  # Depends on all TRCs having summarisation completed

    def run(self, ctx: RunContext, params: dict[str, Any] | None = None) -> StageOutput:
        logger.info(f"Starting master summary synthesis for incident {ctx.incident_id}")
        summaries = [
            t.get("pipeline_outputs", {}).get("summarisation", "")
            for t in ctx.incident.get("trcs", [])
        ]
        summaries = [s for s in summaries if s]
        logger.debug(f"Found {len(summaries)} TRC summaries to synthesize")
        cfg = params or {}
        llm_config = cfg.get("llm")

        if llm_config and summaries:
            logger.debug("Using LLM for master summary synthesis")
            # Use LLM for master summary synthesis
            try:
                llm_client = create_client_from_config(ctx.incident.get("llm", {}))
                prompt_file = llm_config["prompt_file"]

                summaries_text = "\n\n".join(
                    f"TRC {i + 1}:\n{summary}" for i, summary in enumerate(summaries)
                )

                master_summary = llm_client.call_llm_with_prompt_file(
                    prompt_file=prompt_file,
                    summaries=summaries_text,
                ).strip()

                logger.info(
                    f"Master summary synthesis completed using LLM: {len(master_summary)} chars output"
                )
                return StageOutput(
                    incident_updates={"master_summary": master_summary},
                    incident_artifacts_text={"master_summary_raw_llm_output": master_summary},
                    input_info=f"Summaries: {len(summaries)}",
                    output_info=f"Master summary: {len(master_summary)} chars (LLM processed)",
                    messages=["Used LLM for master summary synthesis"],
                )
            except Exception as e:
                # Fallback to simple concatenation if LLM fails
                logger.warning(f"LLM master summary synthesis failed: {e}, falling back to concatenation")

        # Fallback: simple concatenation
        logger.debug("Using simple concatenation for master summary synthesis")
        ms = "\n\n".join(summaries)
        raw = ms
        logger.info(f"Master summary synthesis completed using concatenation: {len(ms)} chars output")
        return StageOutput(
            incident_updates={"master_summary": ms},
            incident_artifacts_text={"master_summary_raw": raw},
            input_info=f"Summaries: {len(summaries)}",
            output_info=f"Master summary: {len(ms)} chars",
        )
