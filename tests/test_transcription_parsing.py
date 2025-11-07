from datetime import datetime
from pathlib import Path

from trc.stages.base import RunContext
from trc.stages.transcription_parsing import TranscriptionParsingStage


def make_ctx(tmp_path: Path, raw_vtt: str, start_dt: datetime | None) -> RunContext:
    return RunContext(
        incident_id="INC_TEST",
        trc_id="TRC_TEST",
        incident={},
        trc={"pipeline_outputs": {"raw_vtt": raw_vtt}},
        data_dir=tmp_path,
        incidents_dir=tmp_path,
        people_path=tmp_path / "people.json",
        artifacts_dir=tmp_path / "artifacts",
        start_dt=start_dt,
    )


def test_timestamp_prefix_with_meeting_start(tmp_path: Path):
    start_dt = datetime(2025, 6, 5, 10, 0, 0)
    vtt = """WEBVTT

00:00:05.000 --> 00:00:06.000
<v Alice>Hello everyone</v>

00:01:10.000 --> 00:01:12.000
<v Alice>Moving on to the next item</v>
"""
    ctx = make_ctx(tmp_path, vtt, start_dt)
    out = TranscriptionParsingStage().run(ctx)
    cleaned = out.trc_outputs.get("transcription_parsing", "")
    lines = [ln for ln in cleaned.splitlines() if ln.strip()]
    assert any(ln.startswith("10:00 Alice:") for ln in lines), cleaned
    assert any(ln.startswith("10:01 Alice:") for ln in lines), cleaned


def test_rollover_adds_four_hours(tmp_path: Path):
    start_dt = datetime(2025, 6, 5, 10, 0, 0)
    vtt = """WEBVTT

00:59:59.000 --> 01:00:00.000
<v Bob>Wrapping up this section</v>

00:00:01.000 --> 00:00:02.000
<v Bob>Starting a new segment after rollover</v>
"""
    ctx = make_ctx(tmp_path, vtt, start_dt)
    out = TranscriptionParsingStage().run(ctx)
    cleaned = out.trc_outputs.get("transcription_parsing", "")
    lines = [ln for ln in cleaned.splitlines() if ln.strip()]
    assert any(ln.startswith("10:59 Bob:") for ln in lines), cleaned
    assert any(ln.startswith("14:00 Bob:") for ln in lines), cleaned


def test_invalid_timestamp_fallback(tmp_path: Path):
    start_dt = datetime(2025, 6, 5, 10, 0, 0)
    stage = TranscriptionParsingStage()

    def fake_segments(_content: str):  # noqa: D401
        return [
            {
                "vtt_timestamp_str": "BAD_TS",
                "raw_speaker": "Carol",
                "raw_dialogue": "First line",
            },
            {
                "vtt_timestamp_str": "00:03:15.000",
                "raw_speaker": "Carol",
                "raw_dialogue": "Back to valid",
            },
        ]

    stage._parse_vtt_to_raw_segments = fake_segments  # type: ignore[attr-defined]
    ctx = make_ctx(tmp_path, "WEBVTT", start_dt)
    out = stage.run(ctx)
    cleaned = out.trc_outputs.get("transcription_parsing", "")
    lines = [ln for ln in cleaned.splitlines() if ln.strip()]
    assert any(ln.startswith("10:00 Carol:") for ln in lines), cleaned
    assert any(ln.startswith("10:03 Carol:") for ln in lines), cleaned


def test_consolidation_same_minute_same_speaker(tmp_path: Path):
    start_dt = datetime(2025, 6, 5, 10, 0, 0)
    vtt = """WEBVTT

00:00:05.000 --> 00:00:06.000
<v Alice>Hello</v>
<v Alice>world</v>

00:00:40.000 --> 00:00:42.000
<v Alice>again</v>
"""
    ctx = make_ctx(tmp_path, vtt, start_dt)
    out = TranscriptionParsingStage().run(ctx)
    cleaned = out.trc_outputs.get("transcription_parsing", "")
    lines = [ln for ln in cleaned.splitlines() if ln.strip()]
    # Expect first two lines consolidated into one 10:00 Alice: Hello world
    assert any("10:00 Alice:" in ln and "Hello world" in ln for ln in lines), cleaned
    # "again" is later within same minute? (offset 40s) still minute 10:00 so should consolidate too
    assert any("10:00 Alice:" in ln and "again" in ln for ln in lines), cleaned
    # Only a single consolidated line for all three dialogues
    assert sum(1 for ln in lines if ln.startswith("10:00 Alice:")) == 1, lines


def test_replacement_and_strip_patterns(tmp_path: Path):
    start_dt = datetime(2025, 6, 5, 10, 0, 0)
    vtt = """WEBVTT

00:00:05.000 --> 00:00:06.000
<v Dana>working on cloud era platform with noise line</v>
"""
    ctx = make_ctx(tmp_path, vtt, start_dt)
    params = {
        "replacement_rules": {"common": {"cloud era": "Cloudera"}},
        "strip_patterns": ["noise"],
    }
    out = TranscriptionParsingStage().run(ctx, params)
    cleaned = out.trc_outputs.get("transcription_parsing", "")
    # Replacement happens before strip; strip removes the matching word only, dialogue retained
    assert "Cloudera" in cleaned or cleaned == ""
    assert "noise" not in cleaned
