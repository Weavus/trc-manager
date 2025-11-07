from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Any, TypedDict

from .base import RunContext, StageOutput

logger = logging.getLogger(__name__)


class VTTDialogueSegment(TypedDict):
    vtt_timestamp_str: str
    raw_speaker: str
    raw_dialogue: str


class TranscriptionParsingStage:
    name = "transcription_parsing"
    requires = ["raw_vtt"]

    FOUR_HOURS_TD = timedelta(hours=4)

    _vtt_timestamp_cue_pattern = re.compile(
        r"^\s*(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3})"
    )
    _vtt_speaker_dialogue_pattern = re.compile(r"<v\s+([^>]+)>(.*?)</v>", re.DOTALL)
    _vtt_metadata_or_id_pattern = re.compile(
        r"^(?:NOTE|STYLE|REGION|WEBVTT|[0-9a-f]{8}-[0-9a-f]{4}-)", re.IGNORECASE
    )

    def run(self, ctx: RunContext, params: dict[str, Any] | None = None) -> StageOutput:
        raw_vtt_content = ctx.trc.get("pipeline_outputs", {}).get("raw_vtt", "")
        if not raw_vtt_content:
            return StageOutput(
                trc_outputs={"transcription_parsing": ""},
                input_info="Input: 0 chars",
                output_info="Output: 0 chars",
            )

        replacement_rules = (params or {}).get("replacement_rules", {})
        flat_replacements = self._flatten_replacement_rules(replacement_rules)
        strip_patterns_conf = (params or {}).get("strip_patterns", [])
        strip_patterns = []
        for p in strip_patterns_conf:
            try:
                strip_patterns.append(re.compile(str(p), re.IGNORECASE))
            except re.error:
                logger.warning("Invalid strip pattern skipped: %r", p)

        raw_segments = self._parse_vtt_to_raw_segments(raw_vtt_content)
        if not raw_segments:
            logger.info("No dialogue segments parsed from VTT content.")
            return StageOutput(
                trc_outputs={"transcription_parsing": ""},
                input_info=f"Input: {len(raw_vtt_content)} chars",
                output_info="Output: 0 chars",
            )

        consolidated: list[dict[str, Any]] = []
        last_minute_key: int | None = None
        last_speaker: str | None = None

        meeting_start_dt = ctx.start_dt
        last_vtt_offset_td: timedelta | None = None
        current_total_rollover_offset = timedelta(0)

        for seg in raw_segments:
            speaker = self._normalize_speaker_name(seg.get("raw_speaker", "") or "Unknown Speaker")
            dialogue = seg.get("raw_dialogue", "")

            if flat_replacements:
                for old, new in flat_replacements.items():
                    try:
                        pattern = re.compile(re.escape(old), re.IGNORECASE)
                        dialogue = pattern.sub(new, dialogue)
                    except re.error:
                        logger.debug("Bad replacement rule skipped: %r -> %r", old, new)

            if strip_patterns:
                kept_lines = []
                for ln in dialogue.splitlines():
                    if not any(p.search(ln) for p in strip_patterns):
                        kept_lines.append(ln)
                dialogue = "\n".join(kept_lines)

            dialogue = dialogue.strip()
            if not dialogue or not any(ch.isalnum() for ch in dialogue):
                continue

            current_vtt_offset_td = self._parse_vtt_timestamp_to_timedelta(
                seg.get("vtt_timestamp_str", "00:00:00.000")
            )

            display_dt = None
            if current_vtt_offset_td is None:
                logger.warning(
                    "Invalid VTT timestamp %r, using previous/meeting start time.",
                    seg.get("vtt_timestamp_str"),
                )
                if consolidated and consolidated[-1].get("display_dt") is not None:
                    display_dt = consolidated[-1]["display_dt"]
                else:
                    display_dt = meeting_start_dt
                current_vtt_offset_td = timedelta(0)
            else:
                if last_vtt_offset_td is not None and current_vtt_offset_td < last_vtt_offset_td:
                    current_total_rollover_offset += self.FOUR_HOURS_TD
                    logger.debug(
                        "VTT time rollover detected. Prev: %s Curr: %s Total adjustment: %s",
                        last_vtt_offset_td,
                        current_vtt_offset_td,
                        current_total_rollover_offset,
                    )
                if meeting_start_dt is not None:
                    actual_offset = current_vtt_offset_td + current_total_rollover_offset
                    display_dt = meeting_start_dt + actual_offset
                last_vtt_offset_td = current_vtt_offset_td

            if display_dt is not None:
                minute_key = int(display_dt.timestamp() // 60)
                hhmm = display_dt.strftime("%H:%M")
            else:
                total_seconds = int(current_vtt_offset_td.total_seconds())
                minute_key = total_seconds // 60
                hh = total_seconds // 3600
                mm = (total_seconds % 3600) // 60
                hhmm = f"{hh:02d}:{mm:02d}"

            if consolidated and last_speaker == speaker and last_minute_key == minute_key:
                consolidated[-1]["text"] += " " + dialogue
            else:
                consolidated.append(
                    {
                        "hhmm": hhmm,
                        "speaker": speaker,
                        "text": dialogue,
                        "display_dt": display_dt,
                    }
                )
                last_speaker = speaker
                last_minute_key = minute_key

        if not consolidated:
            return StageOutput(
                trc_outputs={"transcription_parsing": ""},
                input_info=f"Input: {len(raw_vtt_content)} chars",
                output_info="Output: 0 chars",
            )

        out_lines: list[str] = []
        for entry in consolidated:
            lines = entry["text"].splitlines()
            first = lines[0].strip() if lines else ""
            prefix = f"{entry['hhmm']} {entry['speaker']}:"
            if first:
                out_lines.append(f"{prefix} {first}")
            else:
                out_lines.append(prefix)
            for extra in lines[1:]:
                extra = extra.strip()
                if extra:
                    out_lines.append(extra)

        out_text = "\n".join(out_lines)
        return StageOutput(
            trc_outputs={"transcription_parsing": out_text},
            input_info=f"Input: {len(raw_vtt_content)} chars",
            output_info=f"Output: {len(out_text)} chars",
        )

    def _clean_vtt_content_newlines_in_voice_tags(self, vtt_content: str) -> str:
        return re.sub(
            r"(<v[^>]*>)(.*?)(</v>)",
            lambda m: m.group(1) + m.group(2).replace("\n", " ").replace("\r", "") + m.group(3),
            vtt_content,
            flags=re.DOTALL,
        )

    def _parse_vtt_timestamp_to_timedelta(self, ts_str: str) -> timedelta | None:
        try:
            h, m, s_ms = ts_str.split(":")
            s, ms = s_ms.split(".")
            return timedelta(hours=int(h), minutes=int(m), seconds=int(s), milliseconds=int(ms))
        except Exception:
            logger.warning("Could not parse VTT timestamp string to timedelta: %r", ts_str)
            return None

    def _normalize_speaker_name(self, name: str) -> str:
        name = (name or "").strip()
        if not name:
            return "Unknown Speaker"
        name = re.sub(r"\s+", " ", name)
        return name.strip()

    def _extract_vtt_cue_info(self, line: str) -> tuple[str, str] | None:
        match = self._vtt_timestamp_cue_pattern.match(line)
        return (match.group(1), match.group(2)) if match else None

    def _parse_vtt_to_raw_segments(self, vtt_content: str) -> list[VTTDialogueSegment]:
        segments: list[VTTDialogueSegment] = []
        cleaned = self._clean_vtt_content_newlines_in_voice_tags(vtt_content)
        lines = cleaned.splitlines()

        active_speaker: str | None = None
        active_dialogue_parts: list[str] = []
        active_cue_start_timestamp_str: str = "00:00:00.000"

        for raw_line in lines:
            line = raw_line.strip()
            if not line or self._vtt_metadata_or_id_pattern.match(line) or line == "WEBVTT":
                continue

            cue_info = self._extract_vtt_cue_info(line)
            if cue_info:
                if active_speaker and active_dialogue_parts:
                    segments.append(
                        {
                            "vtt_timestamp_str": active_cue_start_timestamp_str,
                            "raw_speaker": active_speaker,
                            "raw_dialogue": " ".join(active_dialogue_parts).strip(),
                        }
                    )
                active_cue_start_timestamp_str, _ = cue_info
                active_dialogue_parts = []
                active_speaker = None
                continue

            current_pos = 0
            while current_pos < len(line):
                m = self._vtt_speaker_dialogue_pattern.search(line, current_pos)
                if m:
                    plain_before = line[current_pos : m.start()].strip()
                    spk = m.group(1).strip()
                    dlg = m.group(2).strip()
                    if active_speaker and active_speaker != spk and active_dialogue_parts:
                        segments.append(
                            {
                                "vtt_timestamp_str": active_cue_start_timestamp_str,
                                "raw_speaker": active_speaker,
                                "raw_dialogue": " ".join(active_dialogue_parts).strip(),
                            }
                        )
                        active_dialogue_parts = []
                    if plain_before and (not active_speaker or active_speaker != spk):
                        active_dialogue_parts.append(plain_before)
                    active_speaker = spk
                    if dlg:
                        active_dialogue_parts.append(dlg)
                    current_pos = m.end()
                else:
                    remaining = line[current_pos:].strip()
                    if remaining:
                        if not active_speaker:
                            active_speaker = "Unknown Speaker"
                        active_dialogue_parts.append(remaining)
                    current_pos = len(line)

            if not active_speaker and active_dialogue_parts:
                active_speaker = "Unknown Speaker"

        if active_speaker and active_dialogue_parts:
            segments.append(
                {
                    "vtt_timestamp_str": active_cue_start_timestamp_str,
                    "raw_speaker": active_speaker,
                    "raw_dialogue": " ".join(active_dialogue_parts).strip(),
                }
            )
        return segments

    def _flatten_replacement_rules(self, obj: Any) -> dict[str, str]:
        out: dict[str, str] = {}
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, dict):
                    out.update(self._flatten_replacement_rules(v))
                elif isinstance(k, str) and isinstance(v, str):
                    out[k] = v
        return out
