import abc
from typing import Any, Dict, Optional
from shared.errors.errors import DependencyUnavailableError


class AIGatewayClient(abc.ABC):
    """Abstract client interface for external AI Gateway (commercial LLMs, multimodal APIs)."""

    @abc.abstractmethod
    def generate(self, prompt: str, model: Optional[str] = None, **kwargs: Any) -> Dict[str, Any]:
        pass

    @abc.abstractmethod
    def is_available(self) -> bool:
        pass


class UnavailableAIGatewayClient(AIGatewayClient):
    """Phase 13.5: Fail-Closed AI Gateway Client skeleton.
    
    Invariants:
    - Always unavailable / fail-closed.
    - Zero-LLM execution path never depends on this client.
    """

    def generate(self, prompt: str, model: Optional[str] = None, **kwargs: Any) -> Dict[str, Any]:
        raise DependencyUnavailableError(
            "AI Gateway is currently unavailable / fail-closed. Use the deterministic Zero-LLM execution path."
        )

    def is_available(self) -> bool:
        return False
