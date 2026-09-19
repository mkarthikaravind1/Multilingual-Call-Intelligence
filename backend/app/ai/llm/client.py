from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class LLMRequest:
    prompt: str

@dataclass
class LLMResponse:
    text: str

class LLMClient(ABC):
    @abstractmethod
    def complete(self, request: LLMRequest) -> LLMResponse:
        raise NotImplementedError