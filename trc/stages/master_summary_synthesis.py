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
            llm_client = create_client_from_config(ctx.llm_config or {})
            prompt_file = llm_config["prompt_file"]

            summaries_text = "\n\n".join(
                f"TRC {i + 1}:\n{summary}" for i, summary in enumerate(summaries)
            )

            template = PromptTemplate(prompt_file)
            rendered_prompt = template.render(summaries=summaries_text)
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
                input_info=f"Summaries: {len(summaries)}",
                output_info=f"Master summary: {len(master_summary)} chars (LLM processed)",
                messages=["Used LLM for master summary synthesis"],
            )
        else:
            logger.warning("No LLM config for master summary synthesis or no summaries, skipping")
            return StageOutput(
                incident_updates={"master_summary": ""},
                input_info=f"Summaries: {len(summaries)}",
                output_info="Master summary: 0 chars (no LLM or no summaries)",
            )
