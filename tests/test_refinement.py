from datetime import datetime
from pathlib import Path

from trc.stages.base import RunContext
from trc.stages.refinement import RefinementStage


def make_ctx(tmp_path: Path, cleaned: str) -> RunContext:
    return RunContext(
        incident_id="INC_TEST",
        trc_id="TRC_TEST",
        incident={},
        trc={"pipeline_outputs": {"vtt_cleanup": cleaned}},
        data_dir=tmp_path,
        incidents_dir=tmp_path,
        people_path=tmp_path / "people.json",
        artifacts_dir=tmp_path / "artifacts",
        start_dt=datetime(2025, 6, 5, 10, 0, 0),
    )


def test_refinement_applies_replacements(tmp_path: Path):
    # Two lines with prefixes; only dialogue text after speaker is replaced
    cleaned = (
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
    ctx = make_ctx(tmp_path, cleaned)
    out = RefinementStage().run(ctx, params)
    refined = out.trc_outputs.get("refinement", "")
    assert "Cloudera" in refined
    assert refined.count("GitHub") == 2  # github + git hub merged
    # Eikon replacement appears 3 times (eikon, icon, ican -> Eikon)
    assert refined.count("Eikon") >= 3
    # Speaker names should remain lowercase here (no change logic for speakers)
    assert "alice:" in refined


def test_refinement_handles_empty(tmp_path: Path):
    ctx = make_ctx(tmp_path, "")
    out = RefinementStage().run(ctx, {"replacement_rules": {"x": "y"}})
    assert out.trc_outputs.get("refinement", "") == ""
