from __future__ import annotations

import contextlib
import re
from typing import Any

from .base import RunContext, StageOutput


class NoiseReductionStage:
    name = "noise_reduction"
    requires = ["text_enhancement"]

    FILLER_PATTERNS = [
        r"\buh\b",
        r"\bumm?\b",
        r"\bmm+h?\b",
        r"\bhmm+\b",
        r"\bokay+\b",
        r"\bya+h\b",
    ]

    def run(self, ctx: RunContext, params: dict[str, Any] | None = None) -> StageOutput:
        text = ctx.trc.get("pipeline_outputs", {}).get("text_enhancement", "")
        if not text:
            return StageOutput(
                trc_outputs={"noise_reduction": ""},
                input_info="Input: 0 chars",
                output_info="Output: 0 chars",
            )

        cfg = params or {}
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
        msgs = []
        if total:
            msgs.append(f"Removed {total} filler tokens")
        return StageOutput(
            trc_outputs={"noise_reduction": out_text},
            input_info=f"Input: {len(text)} chars",
            output_info=f"Output: {len(out_text)} chars; fillers removed: {total}",
            messages=msgs,
        )
