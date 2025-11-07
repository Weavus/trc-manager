from __future__ import annotations

import re
from typing import Any

from .base import RunContext, StageOutput


class RefinementStage:
    name = "refinement"
    requires = ["cleanup"]

    def run(self, ctx: RunContext, params: dict[str, Any] | None = None) -> StageOutput:
        cleaned = ctx.trc.get("pipeline_outputs", {}).get("cleanup", "")
        text = re.sub(r"\s+", " ", cleaned).strip()
        return StageOutput(
            trc_outputs={"refinement": text},
            input_info=f"Input: {len(cleaned)} chars",
            output_info=f"Output: {len(text)} chars",
        )
