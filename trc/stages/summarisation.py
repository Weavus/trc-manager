from __future__ import annotations

from typing import Any

from .base import RunContext, StageOutput


class SummarisationStage:
    name = "summarisation"
    requires = ["refinement"]

    def run(self, ctx: RunContext, params: dict[str, Any] | None = None) -> StageOutput:
        refined = ctx.trc.get("pipeline_outputs", {}).get("refinement", "")
        incident_title = ctx.incident.get("title") or None
        title: str | None = None
        if not incident_title:
            title = (refined[:60] + "...") if len(refined) > 60 else refined
        summary = f"{title or incident_title or 'Incident'} - Summary:\n\n" + refined[:2000]
        raw = summary
        incident_updates: dict[str, Any] = {}
        if title and not (ctx.incident.get("title") or ""):
            incident_updates["title"] = title
        return StageOutput(
            trc_outputs={"summarisation": summary},
            trc_artifacts_text={"summarisation_llm_output": raw},
            incident_updates=incident_updates,
            input_info=f"Input: {len(refined)} chars",
            output_info=f"Summary: {len(summary)} chars",
        )
