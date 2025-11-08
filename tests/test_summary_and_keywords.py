from pathlib import Path

from trc.stages.base import RunContext
from trc.stages.keyword_extraction import KeywordExtractionStage
from trc.stages.master_summary_synthesis import MasterSummarySynthesisStage
from trc.stages.summarisation import SummarisationStage


def make_ctx_noise(tmp_path: Path, text: str, incident: dict | None = None) -> RunContext:
    return RunContext(
        incident_id="INC789",
        trc_id="TRC111",
        incident=incident or {},
        trc={"pipeline_outputs": {"noise_reduction": text}},
        data_dir=tmp_path,
        incidents_dir=tmp_path,
        people_path=tmp_path / "people.json",
        artifacts_dir=tmp_path / "artifacts",
    )


def test_summarisation_infers_title_when_missing(tmp_path: Path):
    text = (
        "Important Incident Discussion about Networking latency and database scaling concerns." * 2
    )
    ctx = make_ctx_noise(tmp_path, text, incident={})
    out = SummarisationStage().run(ctx)
    summary = out.trc_outputs.get("summarisation", "")
    assert summary.startswith("Important Incident")
    # incident title should be updated
    assert "title" in out.incident_updates


def test_keyword_extraction_top_five(tmp_path: Path):
    text = (
        "Networking latency latency latency database scaling scaling "
        "performance metrics analysis troubleshooting"
    )
    ctx = make_ctx_noise(tmp_path, text)
    out = KeywordExtractionStage().run(ctx)
    keywords = out.trc_outputs.get("keywords")
    assert isinstance(keywords, list)
    # latency appears 3 times, scaling 2, others once
    assert keywords[0] == "latency"
    assert "scaling" in keywords
    assert len(keywords) <= 5
    assert out.incident_updates.get("keywords") == keywords


def test_master_summary_synthesis_aggregates(tmp_path: Path):
    # Simulate incremental synthesis for multiple TRCs
    incident = {
        "trcs": [
            {"pipeline_outputs": {"summarisation": "Summary A"}},
            {"pipeline_outputs": {"summarisation": "Summary B"}},
        ]
    }

    # First TRC: set master to Summary A
    ctx1 = RunContext(
        incident_id="INC999",
        trc_id="TRC000",
        incident=incident,
        trc={"pipeline_outputs": {"summarisation": "Summary A"}},
        data_dir=tmp_path,
        incidents_dir=tmp_path,
        people_path=tmp_path / "people.json",
        artifacts_dir=tmp_path / "artifacts",
    )
    out1 = MasterSummarySynthesisStage().run(ctx1)
    master1 = out1.incident_updates.get("master_summary", "")
    assert master1 == "Summary A"

    # Second TRC: synthesize with existing
    incident["master_summary"] = master1
    ctx2 = RunContext(
        incident_id="INC999",
        trc_id="TRC001",
        incident=incident,
        trc={"pipeline_outputs": {"summarisation": "Summary B"}},
        data_dir=tmp_path,
        incidents_dir=tmp_path,
        people_path=tmp_path / "people.json",
        artifacts_dir=tmp_path / "artifacts",
    )
    out2 = MasterSummarySynthesisStage().run(ctx2)
    master2 = out2.incident_updates.get("master_summary", "")
    assert "Summary A" in master2 and "Summary B" in master2
    # artifact stored
    assert "master_summary_raw_llm_output" in out2.incident_artifacts_text
