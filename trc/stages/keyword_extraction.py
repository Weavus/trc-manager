from __future__ import annotations

import json
import logging
from typing import Any

from ..llm import PromptTemplate, create_client_from_config
from .base import RunContext, StageOutput

logger = logging.getLogger(__name__)


class KeywordExtractionStage:
    name = "keyword_extraction"
    inputs = ["noise_reduction"]
    outputs = ["keyword_extraction"]
    depends_on = []

    def run(self, ctx: RunContext, params: dict[str, Any] | None = None) -> StageOutput:
        logger.info(f"Starting keyword extraction for incident {ctx.incident_id}, TRC {ctx.trc_id}")
        text = ctx.trc.get("pipeline_outputs", {}).get("noise_reduction", "")
        logger.debug(f"Input text length: {len(text)} chars")
        cfg = params or {}
        llm_config = cfg.get("llm")

        if llm_config:
            logger.debug("Using LLM for keyword extraction")
            llm_client = create_client_from_config(ctx.llm_config or {})
            prompt_file = llm_config["prompt_file"]

            template = PromptTemplate(prompt_file)
            rendered_prompt = template.render(transcript=text)
            params = template.get_llm_params()

            out_dir = ctx.artifacts_dir / ctx.incident_id / ctx.trc_id
            out_dir.mkdir(parents=True, exist_ok=True)
            request_file = out_dir / "keyword_extraction_llm_request.txt"
            request_file.write_text(rendered_prompt, encoding="utf-8")

            response = llm_client.call_llm(prompt=rendered_prompt, **params)
            keywords = json.loads(response)

            logger.info(
                f"Keyword extraction completed using LLM: {len(keywords)} keywords extracted"
            )
            return StageOutput(
                trc_outputs={"keywords": keywords},
                trc_artifacts_json={"keyword_extraction_llm_output": keywords},
                trc_artifacts_text={
                    "keyword_extraction_llm_output_raw": json.dumps(keywords, indent=2)
                },
                incident_updates={"keywords": keywords},
                input_info=f"Input: {len(text)} chars",
                output_info=f"Keywords: {len(keywords)} (LLM processed)",
                messages=["Used LLM for keyword extraction"],
            )
        else:
            logger.warning("No LLM config for keyword extraction, skipping")
            return StageOutput(
                trc_outputs={"keywords": []},
                incident_updates={"keywords": []},
                input_info=f"Input: {len(text)} chars",
                output_info="Keywords: 0 (no LLM)",
            )
