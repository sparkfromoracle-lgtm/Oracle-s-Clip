from typing import Dict, List, Optional
from shared.contracts.visual_embedding import VisualEmbedding


class EmbeddingCache:
    """In-memory or persistent content-hash indexed embedding cache."""

    def __init__(self):
        self._cache: Dict[str, VisualEmbedding] = {}

    def get(self, content_hash: str) -> Optional[VisualEmbedding]:
        return self._cache.get(content_hash)

    def set(self, content_hash: str, embedding: VisualEmbedding) -> None:
        self._cache[content_hash] = embedding

    def contains(self, content_hash: str) -> bool:
        return content_hash in self._cache

    def clear(self) -> None:
        self._cache.clear()

    def size(self) -> int:
        return len(self._cache)
