from __future__ import annotations

import contextlib
import logging
import re
from typing import Any

from ..llm import create_client_from_config
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
            try:
                llm_client = create_client_from_config(ctx.incident.get("llm", {}))
                prompt_file = llm_config["prompt_file"]

                # For noise reduction, we need to provide known_terms and transcript
                # Get known terms from text_enhancement stage or use empty
                known_terms = ctx.trc.get("pipeline_outputs", {}).get("text_enhancement", "")
                if not known_terms:
                    known_terms = "No specific terms provided."

                cleaned_text = llm_client.call_llm_with_prompt_file(
                    prompt_file=prompt_file,
                    known_terms=known_terms,
                    transcript=text,
                ).strip()

                logger.info(
                    f"Noise reduction completed using LLM: {len(cleaned_text)} chars output"
                )
                return StageOutput(
                    trc_outputs={"noise_reduction": cleaned_text},
                    trc_artifacts_text={"noise_reduction_llm_output": cleaned_text},
                    input_info=f"Input: {len(text)} chars",
                    output_info=f"Output: {len(cleaned_text)} chars (LLM processed)",
                    messages=["Used LLM for noise reduction"],
                )
            except Exception as e:
                # Fallback to regex-based approach if LLM fails
                logger.warning(f"LLM noise reduction failed: {e}, falling back to regex")

        # Fallback: regex-based noise reduction
        logger.debug("Using regex-based noise reduction")
        filler_patterns = list(self.FILLER_PATTERNS)
        for p in cfg.get("extra_fillers", []):
            with contextlib.suppress(Exception):
                filler_patterns.append(str(p))

        compiled = []
        for p in filler_patterns:
            try:
                compiled.append(re.compile(p, re.IGNORECASE))
            except re.error:
                continue

        logger.debug(f"Compiled {len(compiled)} filler patterns")
        total = 0
        out_lines: list[str] = []
        for line in (text or "").splitlines():
            for rx in compiled:
                line, n = rx.subn("", line)
                total += n
            # collapse excess spaces introduced
            line = re.sub(r"\s{2,}", " ", line).strip()
            out_lines.append(line)

        out_text = "\n".join(out_lines).strip()
        logger.info(
            f"Noise reduction completed using regex: {len(out_text)} chars output, "
            f"{total} fillers removed"
        )
        msgs = []
        if total:
            msgs.append(f"Removed {total} filler tokens")
        return StageOutput(
            trc_outputs={"noise_reduction": out_text},
            input_info=f"Input: {len(text)} chars",
            output_info=f"Output: {len(out_text)} chars; fillers removed: {total}",
            messages=msgs,
        )
