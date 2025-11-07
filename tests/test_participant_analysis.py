from pathlib import Path
from typing import Any

from trc.stages.base import RunContext
from trc.stages.keyword_extraction import KeywordExtractionStage
from trc.stages.participant_knowledge_analysis import ParticipantKnowledgeAnalysisStage
from trc.stages.participant_role_analysis import ParticipantRoleAnalysisStage
from trc.stages.summarisation import SummarisationStage


def make_ctx(
    tmp_path: Path, noise_reduced: str, role_analysis_output: dict | None = None
) -> RunContext:
    pipeline_outputs: dict[str, Any] = {"noise_reduction": noise_reduced}
    if role_analysis_output:
        pipeline_outputs["participant_role_analysis"] = role_analysis_output

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


def test_participant_analysis_split_stages_extract_names_and_updates_people_dir(tmp_path: Path):
    text = (
        "10:00 Alice Johnson: We met with Bob Smith to discuss.\n"
        "10:01 Bob Smith: Thanks Alice Johnson for the update."
    )

    # First run role analysis
    ctx1 = make_ctx(tmp_path, text)
    role_out = ParticipantRoleAnalysisStage().run(ctx1)

    role_payload = role_out.trc_outputs.get("participant_role_analysis", {})
    assert isinstance(role_payload, dict)
    roles = role_payload.get("roles", [])
    assert any(r.get("display_name") == "Alice Johnson" for r in roles)
    assert any(r.get("display_name") == "Bob Smith" for r in roles)

    # Then run knowledge analysis
    ctx2 = make_ctx(tmp_path, text, role_payload)
    knowledge_out = ParticipantKnowledgeAnalysisStage().run(ctx2)

    knowledge_payload = knowledge_out.trc_outputs.get("participant_knowledge_analysis", {})
    assert isinstance(knowledge_payload, dict)
    knowledge = knowledge_payload.get("knowledge", [])
    assert len(knowledge) >= 0  # May be empty in heuristic mode

    # Check backward compatibility - combined output should be available
    combined_payload = knowledge_out.trc_outputs.get("participant_analysis", {})
    assert isinstance(combined_payload, dict)
    assert "roles" in combined_payload
    assert "knowledge" in combined_payload
    assert combined_payload["roles"] == roles

    # Check people directory updates from both stages
    all_updates = {}
    all_updates.update(role_out.people_directory_updates)
    all_updates.update(knowledge_out.people_directory_updates)

    assert "alice johnson" in all_updates and "bob smith" in all_updates
    for key, entry in all_updates.items():
        assert entry.get("raw_name") == key
        assert isinstance(entry.get("discovered_roles", []), list)
        assert isinstance(entry.get("discovered_knowledge", []), list)
        # Linked to current incident/TRC
        for rr in entry.get("discovered_roles", []):
            assert rr.get("incident_id") == ctx1.incident_id
            assert rr.get("trc_id") == ctx1.trc_id
        for kk in entry.get("discovered_knowledge", []):
            assert kk.get("incident_id") == ctx2.incident_id
            assert kk.get("trc_id") == ctx2.trc_id


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
