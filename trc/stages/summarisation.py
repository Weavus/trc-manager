from __future__ import annotations

from typing import Any

from ..llm import create_client_from_config
from .base import RunContext, StageOutput


class SummarisationStage:
    name = "summarisation"
    inputs = ["noise_reduction"]
    outputs = ["summarisation"]
    depends_on = []

    def run(self, ctx: RunContext, params: dict[str, Any] | None = None) -> StageOutput:
        text = ctx.trc.get("pipeline_outputs", {}).get("noise_reduction", "")
        cfg = params or {}
        llm_config = cfg.get("llm")

        if llm_config:
            # Use LLM for summarization
            try:
                llm_client = create_client_from_config(ctx.incident.get("llm", {}))
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
                print(f"LLM summarization failed: {e}, falling back to simple extraction")

        # Fallback: simple text-based summarization
        incident_title = ctx.incident.get("title") or None
        title: str | None = None
        if not incident_title:
            title = (text[:60] + "...") if len(text) > 60 else text
        summary = f"{title or incident_title or 'Incident'} - Summary:\n\n" + text[:2000]
        raw = summary
        incident_updates: dict[str, Any] = {}
        if title and not (ctx.incident.get("title") or ""):
            incident_updates["title"] = title
        return StageOutput(
            trc_outputs={"summarisation": summary},
            trc_artifacts_text={"summarisation_llm_output": raw},
            incident_updates=incident_updates,
            input_info=f"Input: {len(text)} chars",
            output_info=f"Summary: {len(summary)} chars",
        )
