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
    # Build incident with multiple TRCs each having summarisation output
    incident = {
        "trcs": [
            {"pipeline_outputs": {"summarisation": "Summary A"}},
            {"pipeline_outputs": {"summarisation": "Summary B"}},
            {"pipeline_outputs": {"summarisation": ""}},  # empty ignored
        ]
    }
    ctx = RunContext(
        incident_id="INC999",
        trc_id="TRC000",
        incident=incident,
        trc={"pipeline_outputs": {}},
        data_dir=tmp_path,
        incidents_dir=tmp_path,
        people_path=tmp_path / "people.json",
        artifacts_dir=tmp_path / "artifacts",
    )
    out = MasterSummarySynthesisStage().run(ctx)
    master = out.incident_updates.get("master_summary", "")
    assert "Summary A" in master and "Summary B" in master
    # artifact stored
    assert "master_summary_raw" in out.incident_artifacts_text
