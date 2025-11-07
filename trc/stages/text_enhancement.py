from __future__ import annotations

import difflib
import html
import re
from typing import Any

from .base import RunContext, StageOutput


class TextEnhancementStage:
    name = "text_enhancement"
    inputs = ["transcription_parsing"]
    outputs = ["text_enhancement"]
    depends_on = []

    def run(self, ctx: RunContext, params: dict[str, Any] | None = None) -> StageOutput:
        parsed = ctx.trc.get("pipeline_outputs", {}).get("transcription_parsing", "")
        if not parsed:
            return StageOutput(
                trc_outputs={"text_enhancement": ""},
                input_info="Input: 0 chars",
                output_info="Output: 0 chars",
            )

        replacement_rules = (params or {}).get("replacement_rules", {})
        flat_rules = self._flatten_replacement_rules(replacement_rules)
        ordered_rules = sorted(flat_rules.items(), key=lambda kv: len(kv[0]), reverse=True)

        prefix_pattern = re.compile(r"^(\d{2}:\d{2})\s+([^:]+):\s*(.*)$")
        total_replacements = 0
        out_lines: list[str] = []
        changes: list[dict[str, Any]] = []
        for raw_line in parsed.splitlines():
            line = raw_line.rstrip()
            if not line:
                out_lines.append(line)
                continue
            m = prefix_pattern.match(line)
            if m:
                hhmm, speaker, dialogue = m.groups()
                new_dialogue, rep_count = self._apply_replacements(dialogue, ordered_rules)
                total_replacements += rep_count
                if new_dialogue:
                    new_line = f"{hhmm} {speaker}: {new_dialogue}".rstrip()
                else:
                    new_line = f"{hhmm} {speaker}:".rstrip()
                out_lines.append(new_line)
                if rep_count:
                    changes.append(
                        {
                            "hhmm": hhmm,
                            "speaker": speaker,
                            "old_dialogue": dialogue,
                            "new_dialogue": new_dialogue,
                            "old_line": line,
                            "new_line": new_line,
                            "diff_html": self._inline_diff_html(dialogue, new_dialogue),
                        }
                    )
            else:
                new_line, rep_count = self._apply_replacements(line, ordered_rules)
                total_replacements += rep_count
                out_lines.append(new_line)
                if rep_count:
                    changes.append(
                        {
                            "hhmm": None,
                            "speaker": None,
                            "old_dialogue": line,
                            "new_dialogue": new_line,
                            "old_line": line,
                            "new_line": new_line,
                            "diff_html": self._inline_diff_html(line, new_line),
                        }
                    )

        enhanced_text = "\n".join(out_lines).strip()
        messages = []
        if total_replacements:
            messages.append(f"Applied {total_replacements} replacements")
        return StageOutput(
            trc_outputs={"text_enhancement": enhanced_text},
            trc_artifacts_json={
                "text_enhancement_diffs": {
                    "total_replacements": total_replacements,
                    "changes": changes,
                }
            },
            input_info=f"Input: {len(parsed)} chars",
            output_info=f"Output: {len(enhanced_text)} chars; replacements: {total_replacements}",
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

    def _apply_replacements(
        self, text: str, ordered_rules: list[tuple[str, str]]
    ) -> tuple[str, int]:
        replaced_total = 0
        for old, new in ordered_rules:
            try:
                pattern = re.compile(re.escape(old), re.IGNORECASE)
                text, n = pattern.subn(new, text)
                replaced_total += n
            except re.error:
                continue
        return text, replaced_total

    def _inline_diff_html(self, old: str, new: str) -> str:
        # Produce a simple inline diff highlighting changed tokens
        old_words = old.split()
        new_words = new.split()
        sm = difflib.SequenceMatcher(None, old_words, new_words)
        out: list[str] = []
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                out.extend(html.escape(w) for w in new_words[j1:j2])
            elif tag == "replace":
                del_text = " ".join(html.escape(w) for w in old_words[i1:i2])
                ins_text = " ".join(html.escape(w) for w in new_words[j1:j2])
                if del_text:
                    out.append(f"<del>{del_text}</del>")
                if ins_text:
                    out.append(f"<ins>{ins_text}</ins>")
            elif tag == "delete":
                del_text = " ".join(html.escape(w) for w in old_words[i1:i2])
                if del_text:
                    out.append(f"<del>{del_text}</del>")
            elif tag == "insert":
                ins_text = " ".join(html.escape(w) for w in new_words[j1:j2])
                if ins_text:
                    out.append(f"<ins>{ins_text}</ins>")
        return " ".join(out)
