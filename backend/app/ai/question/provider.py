from abc import ABC, abstractmethod
from dataclasses import dataclass
from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.question_suggestion import QuestionSuggestion
from app.domain.utterance import Utterance
from app.domain.runtime_improvement_context import RuntimeImprovementContext  

@dataclass
class QuestionGenerationContext:
    category: str
    status: ComplaintCoverageStatus
    utterances: tuple[Utterance, ...]
    learning_context: tuple[RuntimeImprovementContext, ...] = ()  

class QuestionSuggestionProvider(ABC):
    @abstractmethod
    def generate(self, context: QuestionGenerationContext) -> QuestionSuggestion | None:
        raise NotImplementedError