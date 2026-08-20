from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from shared.contracts.enums import VisualEmbeddingModel


@dataclass(frozen=True)
class VisualEmbedding:
    embedding_id: str
    media_id: str
    frame_id: Optional[str]
    timestamp_ms: int
    model_name: VisualEmbeddingModel
    vector: List[float]
    dimension: int
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TextEmbedding:
    query_text: str
    model_name: VisualEmbeddingModel
    vector: List[float]
    dimension: int


@dataclass(frozen=True)
class EmbeddingSearchResult:
    embedding_id: str
    media_id: str
    frame_id: Optional[str]
    timestamp_ms: int
    score: float
    metadata: Dict[str, Any] = field(default_factory=dict)
