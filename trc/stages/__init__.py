from __future__ import annotations

from .base import Stage
from .keyword_extraction import KeywordExtractionStage
from .master_summary_synthesis import MasterSummarySynthesisStage
from .noise_reduction import NoiseReductionStage
from .participant_knowledge_analysis import ParticipantKnowledgeAnalysisStage
from .participant_role_analysis import ParticipantRoleAnalysisStage
from .summarisation import SummarisationStage
from .text_enhancement import TextEnhancementStage
from .transcription_parsing import TranscriptionParsingStage


def get_builtin_registry() -> dict[str, Stage]:
    return {
        "transcription_parsing": TranscriptionParsingStage(),
        "text_enhancement": TextEnhancementStage(),
        "noise_reduction": NoiseReductionStage(),
        "participant_role_analysis": ParticipantRoleAnalysisStage(),
        "participant_knowledge_analysis": ParticipantKnowledgeAnalysisStage(),
        "summarisation": SummarisationStage(),
        "keyword_extraction": KeywordExtractionStage(),
        "master_summary_synthesis": MasterSummarySynthesisStage(),
    }
