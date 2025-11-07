from pathlib import Path

from trc.stages.base import RunContext
from trc.stages.noise_reduction import NoiseReductionStage
from trc.stages.text_enhancement import TextEnhancementStage


def make_ctx_enhanced(tmp_path: Path, parsed: str) -> RunContext:
    return RunContext(
        incident_id="INC_TEST",
        trc_id="TRC_TEST",
        incident={},
        trc={"pipeline_outputs": {"transcription_parsing": parsed}},
        data_dir=tmp_path,
        incidents_dir=tmp_path,
        people_path=tmp_path / "people.json",
        artifacts_dir=tmp_path / "artifacts",
    )


def make_ctx_noise(tmp_path: Path, enhanced: str) -> RunContext:
    return RunContext(
        incident_id="INC_TEST",
        trc_id="TRC_TEST",
        incident={},
        trc={"pipeline_outputs": {"text_enhancement": enhanced}},
        data_dir=tmp_path,
        incidents_dir=tmp_path,
        people_path=tmp_path / "people.json",
        artifacts_dir=tmp_path / "artifacts",
    )


def test_text_enhancement_applies_dialogue_replacements(tmp_path: Path):
    parsed = (
        "10:00 alice: working on cloud era platform\n"
        "Continuation with github and git hub\n"
        "10:00 bob: checking eikon icon ican status"
    )
    params = {
        "replacement_rules": {
            "common_misspellings": {
                "cloud era": "Cloudera",
                "github": "GitHub",
                "git hub": "GitHub",
            },
            "product_names": {"eikon": "Eikon", "icon": "Eikon", "ican": "Eikon"},
        }
    }
    ctx = make_ctx_enhanced(tmp_path, parsed)
    out = TextEnhancementStage().run(ctx, params)
    refined = out.trc_outputs.get("text_enhancement", "")
    assert "Cloudera" in refined
    assert refined.count("GitHub") == 2
    assert refined.count("Eikon") >= 3
    # speaker casing preserved
    assert "alice:" in refined
    # artifact contains diffs
    diffs = out.trc_artifacts_json.get("text_enhancement_diffs", {})
    assert isinstance(diffs, dict) and diffs.get("total_replacements", 0) >= 1
    assert isinstance(diffs.get("changes", []), list)


def test_noise_reduction_removes_fillers(tmp_path: Path):
    enhanced = "10:00 Alice: uh we will, umm, okay proceed\nSome yaah extra mmh hmm text"
    ctx = make_ctx_noise(tmp_path, enhanced)
    out = NoiseReductionStage().run(ctx)
    cleaned = out.trc_outputs.get("noise_reduction", "")
    assert "uh" not in cleaned.lower()
    assert "umm" not in cleaned.lower()
    assert "okay" not in cleaned.lower()
    assert "yaah" not in cleaned.lower()
    assert "mmh" not in cleaned.lower()
    assert "hmm" not in cleaned.lower()
    # ensure spacing collapsed
    for ln in cleaned.splitlines():
        assert "  " not in ln
