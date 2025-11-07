from __future__ import annotations

import logging
from typing import Any

from ..llm import create_client_from_config
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
            try:
                llm_client = create_client_from_config(ctx.llm_config or {})
                prompt_file = llm_config["prompt_file"]

                summary = llm_client.call_llm_with_prompt_file(
                    prompt_file=prompt_file,
                    transcript=text,
                ).strip()

                incident_title = ctx.incident.get("title") or None
                title: str | None = None
                if not incident_title:
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
            except Exception as e:
                # Fallback to simple text extraction if LLM fails
                logger.warning(f"LLM summarization failed: {e}, falling back to simple extraction")

        # Fallback: simple text-based summarization
        logger.debug("Using simple text-based summarization")
        incident_title = ctx.incident.get("title") or None
        title: str | None = None
        if not incident_title:
            title = (text[:60] + "...") if len(text) > 60 else text
        summary = f"{title or incident_title or 'Incident'} - Summary:\n\n" + text[:2000]
        raw = summary
        incident_updates: dict[str, Any] = {}
        if title and not (ctx.incident.get("title") or ""):
            incident_updates["title"] = title
        logger.info(f"Summarisation completed using simple extraction: {len(summary)} chars output")
        return StageOutput(
            trc_outputs={"summarisation": summary},
            trc_artifacts_text={"summarisation_llm_output": raw},
            incident_updates=incident_updates,
            input_info=f"Input: {len(text)} chars",
            output_info=f"Summary: {len(summary)} chars",
        )
