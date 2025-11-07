from pathlib import Path

from trc.stages.base import RunContext
from trc.stages.participant_analysis import ParticipantAnalysisStage


def make_ctx(tmp_path: Path, noise_reduced: str) -> RunContext:
    return RunContext(
        incident_id="INC123",
        trc_id="TRC456",
        incident={},
        trc={"pipeline_outputs": {"noise_reduction": noise_reduced}},
        data_dir=tmp_path,
        incidents_dir=tmp_path,
        people_path=tmp_path / "people.json",
        artifacts_dir=tmp_path / "artifacts",
    )


def test_participant_analysis_extracts_names_and_updates_people_dir(tmp_path: Path):
    text = (
        "10:00 Alice Johnson: We met with Bob Smith to discuss.\n"
        "10:01 Bob Smith: Thanks Alice Johnson for the update."
    )
    ctx = make_ctx(tmp_path, text)
    out = ParticipantAnalysisStage().run(ctx)

    payload = out.trc_outputs.get("participant_analysis", {})
    assert isinstance(payload, dict)
    roles = payload.get("roles", [])
    assert any(r.get("display_name") == "Alice Johnson" for r in roles)
    assert any(r.get("display_name") == "Bob Smith" for r in roles)

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
