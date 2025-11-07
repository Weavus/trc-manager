from __future__ import annotations

import logging
import re
from typing import Any

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
        words = re.findall(r"[a-zA-Z]{6,}", text.lower())
        logger.debug(f"Found {len(words)} potential keywords")
        freq: dict[str, int] = {}
        for w in words:
            freq[w] = freq.get(w, 0) + 1
        keywords = [w for w, _ in sorted(freq.items(), key=lambda x: (-x[1], x[0]))[:5]]
        logger.info(f"Keyword extraction completed: {len(keywords)} keywords extracted")
        # Provide both trc-level and incident-level updates; runner will merge incident keywords
        return StageOutput(
            trc_outputs={"keywords": keywords},
            incident_updates={"keywords": keywords},
            input_info=f"Input: {len(text)} chars",
            output_info=f"Keywords: {len(keywords)}",
        )
