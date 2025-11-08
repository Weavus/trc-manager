from __future__ import annotations

import logging
from typing import Any

from ..llm import PromptTemplate, create_client_from_config
from .base import RunContext, StageOutput

logger = logging.getLogger(__name__)


class NoiseReductionStage:
    name = "noise_reduction"
    inputs = ["text_enhancement"]
    outputs = ["noise_reduction"]
    depends_on = []

    FILLER_PATTERNS = [
        r"\buh\b",
        r"\bumm?\b",
        r"\bmm+h?\b",
        r"\bhmm+\b",
        r"\bokay+\b",
        r"\bya+h\b",
    ]

    def run(self, ctx: RunContext, params: dict[str, Any] | None = None) -> StageOutput:
        logger.info(f"Starting noise reduction for incident {ctx.incident_id}, TRC {ctx.trc_id}")
        text = ctx.trc.get("pipeline_outputs", {}).get("text_enhancement", "")
        logger.debug(f"Input text length: {len(text)} chars")
        if not text:
            logger.warning("No text enhancement output found, skipping noise reduction")
            return StageOutput(
                trc_outputs={"noise_reduction": ""},
                input_info="Input: 0 chars",
                output_info="Output: 0 chars",
            )

        cfg = params or {}
        llm_config = cfg.get("llm")

        if llm_config:
            logger.debug("Using LLM for noise reduction")
            # Use LLM for noise reduction
            llm_client = create_client_from_config(ctx.llm_config or {})
            prompt_file = llm_config["prompt_file"]

            # For noise reduction, we need to provide known_terms and transcript
            # Get known terms from config params
            known_terms_config = cfg.get("known_terms", {})
            if known_terms_config:
                # Format known terms by category for the prompt
                formatted_terms = []
                for category, terms in known_terms_config.items():
                    if terms:
                        category_name = category.replace("_", " ").title()
                        terms_list = ", ".join(terms)
                        formatted_terms.append(f"**{category_name}:**\n{terms_list}")
                known_terms = "\n\n".join(formatted_terms)
            else:
                known_terms = "No specific terms provided."

            template = PromptTemplate(prompt_file)
            rendered_prompt = template.render(known_terms=known_terms, transcript=text)
            params = template.get_llm_params()

            out_dir = ctx.artifacts_dir / ctx.incident_id / ctx.trc_id
            out_dir.mkdir(parents=True, exist_ok=True)
            request_file = out_dir / "noise_reduction_llm_request.txt"
            request_file.write_text(rendered_prompt, encoding="utf-8")

            cleaned_text = llm_client.call_llm(prompt=rendered_prompt, **params).strip()

            logger.info(f"Noise reduction completed using LLM: {len(cleaned_text)} chars output")
            return StageOutput(
                trc_outputs={"noise_reduction": cleaned_text},
                trc_artifacts_text={"noise_reduction_llm_output": cleaned_text},
                input_info=f"Input: {len(text)} chars",
                output_info=f"Output: {len(cleaned_text)} chars (LLM processed)",
                messages=["Used LLM for noise reduction"],
            )
        else:
            logger.warning("No LLM config for noise reduction, using input text as-is")
            return StageOutput(
                trc_outputs={"noise_reduction": text},
                input_info=f"Input: {len(text)} chars",
                output_info=f"Output: {len(text)} chars (no LLM)",
            )
