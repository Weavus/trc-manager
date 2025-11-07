from __future__ import annotations

import re
from typing import Any

from .base import RunContext, StageOutput


class RefinementStage:
    name = "refinement"
    requires = ["vtt_cleanup"]

    def run(self, ctx: RunContext, params: dict[str, Any] | None = None) -> StageOutput:
        cleaned = ctx.trc.get("pipeline_outputs", {}).get("vtt_cleanup", "")
        if not cleaned:
            return StageOutput(
                trc_outputs={"refinement": ""},
                input_info="Input: 0 chars",
                output_info="Output: 0 chars",
            )

        replacement_rules = (params or {}).get("replacement_rules", {})
        flat_rules = self._flatten_replacement_rules(replacement_rules)
        # Sort keys longest first to reduce partial overlaps
        ordered_rules = sorted(flat_rules.items(), key=lambda kv: len(kv[0]), reverse=True)

        prefix_pattern = re.compile(r"^(\d{2}:\d{2})\s+([^:]+):\s*(.*)$")
        total_replacements = 0
        out_lines: list[str] = []
        current_speaker = None
        for raw_line in cleaned.splitlines():
            line = raw_line.rstrip()
            if not line:
                out_lines.append(line)
                continue
            m = prefix_pattern.match(line)
            if m:
                hhmm, speaker, dialogue = m.groups()
                current_speaker = speaker  # track for continuation lines
                new_dialogue, rep_count = self._apply_replacements(dialogue, ordered_rules)
                total_replacements += rep_count
                if new_dialogue:
                    out_lines.append(f"{hhmm} {speaker}: {new_dialogue}".rstrip())
                else:
                    out_lines.append(f"{hhmm} {speaker}:".rstrip())
            else:
                # Continuation line (no time prefix) -> apply replacements across whole line
                new_line, rep_count = self._apply_replacements(line, ordered_rules)
                total_replacements += rep_count
                out_lines.append(new_line)
        refined_text = "\n".join(out_lines).strip()
        messages = []
        if total_replacements:
            messages.append(f"Applied {total_replacements} replacements")
        return StageOutput(
            trc_outputs={"refinement": refined_text},
            input_info=f"Input: {len(cleaned)} chars",
            output_info=f"Output: {len(refined_text)} chars; replacements: {total_replacements}",
            messages=messages,
        )

    def _flatten_replacement_rules(self, obj: Any) -> dict[str, str]:
        out: dict[str, str] = {}
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, dict):
                    out.update(self._flatten_replacement_rules(v))
                elif isinstance(k, str) and isinstance(v, str):
                    out[k] = v
        return out

    def _apply_replacements(self, text: str, ordered_rules: list[tuple[str, str]]) -> tuple[str, int]:
        replaced_total = 0
        for old, new in ordered_rules:
            try:
                pattern = re.compile(re.escape(old), re.IGNORECASE)
                text, n = pattern.subn(new, text)
                replaced_total += n
            except re.error:
                continue
        return text, replaced_total
