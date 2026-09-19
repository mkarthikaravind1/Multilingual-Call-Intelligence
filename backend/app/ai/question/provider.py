from abc import ABC, abstractmethod
from dataclasses import dataclass
from app.domain.complaint_coverage import ComplaintCoverageStatus
from app.domain.question_suggestion import QuestionSuggestion
from app.domain.utterance import Utterance

@dataclass
class QuestionGenerationContext:
    category: str
    status: ComplaintCoverageStatus
    utterances: tuple[Utterance, ...]

class QuestionSuggestionProvider(ABC):
    @abstractmethod
    def generate(self, context: QuestionGenerationContext) -> QuestionSuggestion | None:
        raise NotImplementedError