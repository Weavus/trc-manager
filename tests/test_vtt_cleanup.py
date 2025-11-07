from datetime import datetime
from pathlib import Path

from trc.stages.base import RunContext
from trc.stages.vtt_cleanup import CleanupStage


def make_ctx(tmp_path: Path, raw_vtt: str, start_dt: datetime | None) -> RunContext:
    """Helper to create a minimal RunContext for the cleanup stage."""
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


def test_absolute_time_prefix_from_start(tmp_path: Path):
    # Meeting starts at 10:00
    start_dt = datetime(2025, 6, 5, 10, 0, 0)
    vtt = """WEBVTT

00:00:05.000 --> 00:00:06.000
<v Alice>Hello everyone</v>

00:01:10.000 --> 00:01:12.000
<v Alice>Moving on to the next item</v>
"""
    ctx = make_ctx(tmp_path, vtt, start_dt)
    out = CleanupStage().run(ctx)
    cleaned = out.trc_outputs.get("vtt_cleanup", "")
    lines = [ln for ln in cleaned.splitlines() if ln.strip()]
    # Expect 10:00 and 10:01 prefixes
    assert any(ln.startswith("10:00 Alice:") for ln in lines), cleaned
    assert any(ln.startswith("10:01 Alice:") for ln in lines), cleaned


def test_rollover_increases_by_fixed_window(tmp_path: Path):
    # Meeting starts at 10:00, offsets roll over after an hour to a smaller value
    # We simulate a decrease from 00:59:59 to 00:00:01, which should add FOUR_HOURS
    start_dt = datetime(2025, 6, 5, 10, 0, 0)
    vtt = """WEBVTT

00:59:59.000 --> 01:00:00.000
<v Bob>Wrapping up this section</v>

00:00:01.000 --> 00:00:02.000
<v Bob>Starting a new segment after rollover</v>
"""
    ctx = make_ctx(tmp_path, vtt, start_dt)
    out = CleanupStage().run(ctx)
    cleaned = out.trc_outputs.get("vtt_cleanup", "")
    lines = [ln for ln in cleaned.splitlines() if ln.strip()]
    # First line around 10:59, second line should be 14:00 due to 4-hour rollover adjustment
    assert any(ln.startswith("10:59 Bob:") for ln in lines), cleaned
    assert any(ln.startswith("14:00 Bob:") for ln in lines), cleaned


def test_invalid_timestamp_fallback_monkeypatched(tmp_path: Path):
    # Monkeypatch parser to yield an invalid timestamp segment to exercise fallback path.
    start_dt = datetime(2025, 6, 5, 10, 0, 0)
    stage = CleanupStage()

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
    cleaned = out.trc_outputs.get("vtt_cleanup", "")
    lines = [ln for ln in cleaned.splitlines() if ln.strip()]
    assert any(ln.startswith("10:00 Carol:") for ln in lines), cleaned  # fallback to meeting start
    assert any(ln.startswith("10:03 Carol:") for ln in lines), cleaned
