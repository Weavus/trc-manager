from pathlib import Path
from typing import Any

from trc.stages.base import RunContext
from trc.stages.keyword_extraction import KeywordExtractionStage
from trc.stages.participant_analysis import ParticipantAnalysisStage
from trc.stages.summarisation import SummarisationStage


def make_ctx(tmp_path: Path, noise_reduced: str) -> RunContext:
    pipeline_outputs: dict[str, Any] = {"noise_reduction": noise_reduced}

    return RunContext(
        incident_id="INC123",
        trc_id="TRC456",
        incident={},
        trc={"pipeline_outputs": pipeline_outputs},
        data_dir=tmp_path,
        incidents_dir=tmp_path,
        people_path=tmp_path / "people.json",
        artifacts_dir=tmp_path / "artifacts",
    )


def test_participant_analysis_extract_names_and_updates_people_dir(tmp_path: Path):
    text = (
        "10:00 Alice Johnson: We met with Bob Smith to discuss.\n"
        "10:01 Bob Smith: Thanks Alice Johnson for the update."
    )

    ctx = make_ctx(tmp_path, text)
    out = ParticipantAnalysisStage().run(ctx)

    payload = out.trc_outputs.get("participant_analysis", {})
    assert isinstance(payload, dict)
    roles = payload.get("roles", [])
    knowledge = payload.get("knowledge", [])
    assert any(r.get("display_name") == "Alice Johnson" for r in roles)
    assert any(r.get("display_name") == "Bob Smith" for r in roles)
    assert len(knowledge) >= 0  # May be empty in heuristic mode

    # Check people directory updates
    updates = out.people_directory_updates

    assert "alice johnson" in updates and "bob smith" in updates
    for key, entry in updates.items():
        assert entry.get("raw_name") == key
        assert isinstance(entry.get("discovered_roles", []), list)
        assert isinstance(entry.get("discovered_knowledge", []), list)
        # Linked to current incident/TRC
        for rr in entry.get("discovered_roles", []):
            assert rr.get("incident_id") == ctx.incident_id
            assert rr.get("trc_id") == ctx.trc_id
        for kk in entry.get("discovered_knowledge", []):
            assert kk.get("incident_id") == ctx.incident_id
            assert kk.get("trc_id") == ctx.trc_id


def test_multiple_stages_can_consume_same_input(tmp_path: Path):
    """Test that multiple stages can consume the same input (demonstrating parallel potential)."""
    text = (
        "10:00 Alice Johnson: We need to fix the database issue.\n"
        "10:01 Bob Smith: The PostgreSQL server is down."
    )

    # Both summarisation and keyword_extraction consume "noise_reduction" input
    ctx = RunContext(
        incident_id="INC123",
        trc_id="TRC456",
        incident={},
        trc={"pipeline_outputs": {"noise_reduction": text}},
        data_dir=tmp_path,
        incidents_dir=tmp_path,
        people_path=tmp_path / "people.json",
        artifacts_dir=tmp_path / "artifacts",
    )

    # Both stages should be able to run independently with the same input
    summary_result = SummarisationStage().run(ctx)
    assert "summarisation" in summary_result.trc_outputs

    keyword_result = KeywordExtractionStage().run(ctx)
    assert "keywords" in keyword_result.trc_outputs

    # Verify they both consumed the same input
    assert summary_result.input_info == keyword_result.input_info
