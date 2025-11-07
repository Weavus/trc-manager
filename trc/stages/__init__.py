from __future__ import annotations

from .base import Stage
from .keyword_extraction import KeywordExtractionStage
from .master_summary import MasterSummaryStage
from .people_extraction import PeopleExtractionStage
from .refinement import RefinementStage
from .summarisation import SummarisationStage
from .vtt_cleanup import CleanupStage


def get_builtin_registry() -> dict[str, Stage]:
    return {
        "vtt_cleanup": CleanupStage(),
        "refinement": RefinementStage(),
        "people_extraction": PeopleExtractionStage(),
        "summarisation": SummarisationStage(),
        "keyword_extraction": KeywordExtractionStage(),
        "master_summary": MasterSummaryStage(),
    }
