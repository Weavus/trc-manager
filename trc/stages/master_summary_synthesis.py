from __future__ import annotations

from typing import Any

from .base import RunContext, StageOutput


<<<<<<<< HEAD:trc/stages/master_summary_synthesis.py
class MasterSummarySynthesisStage:
    name = "master_summary_synthesis"
========
class MasterSummaryStage:
    """DEPRECATED: replaced by `MasterSummarySynthesisStage`.

    Prefer `trc.stages.master_summary_synthesis.MasterSummarySynthesisStage`.
    """
    name = "master_summary"
>>>>>>>> origin/main:trc/stages/master_summary.py
    requires: list[str] = []

    def run(self, ctx: RunContext, params: dict[str, Any] | None = None) -> StageOutput:
        summaries = [
            t.get("pipeline_outputs", {}).get("summarisation", "")
            for t in ctx.incident.get("trcs", [])
        ]
        summaries = [s for s in summaries if s]
        ms = "\n\n".join(summaries)
        raw = ms
        return StageOutput(
            incident_updates={"master_summary": ms},
            incident_artifacts_text={"master_summary_raw": raw},
            input_info=f"Summaries: {len(summaries)}",
            output_info=f"Master summary: {len(ms)} chars",
        )
