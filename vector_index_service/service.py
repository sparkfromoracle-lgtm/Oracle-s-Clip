from typing import Dict, List, Optional
import numpy as np
from shared.contracts.visual_embedding import VisualEmbedding, TextEmbedding, EmbeddingSearchResult
from vector_index_service.filters.vector_search_filter import VectorSearchFilter


class VectorIndexService:
    """In-memory cosine similarity vector index service."""

    def __init__(self, dimension: int = 512):
        self.dimension = dimension
        self._embeddings: Dict[str, VisualEmbedding] = {}

    def insert(self, embedding: VisualEmbedding) -> None:
        self._embeddings[embedding.embedding_id] = embedding

    def insert_batch(self, embeddings: List[VisualEmbedding]) -> None:
        for emb in embeddings:
            self.insert(emb)

    def search(
        self,
        query: TextEmbedding,
        top_k: int = 5,
        search_filter: Optional[VectorSearchFilter] = None,
    ) -> List[EmbeddingSearchResult]:
        if not self._embeddings:
            return []

        q_vec = np.array(query.vector, dtype=np.float32)
        q_norm = np.linalg.norm(q_vec)
        if q_norm == 0:
            return []
        q_vec = q_vec / q_norm

        results = []
        for emb in self._embeddings.values():
            if search_filter and not search_filter.matches(emb.media_id, emb.timestamp_ms, emb.metadata):
                continue

            e_vec = np.array(emb.vector, dtype=np.float32)
            e_norm = np.linalg.norm(e_vec)
            if e_norm == 0:
                continue
            e_vec = e_vec / e_norm

            sim = float(np.dot(q_vec, e_vec))
            results.append(
                EmbeddingSearchResult(
                    embedding_id=emb.embedding_id,
                    media_id=emb.media_id,
                    frame_id=emb.frame_id,
                    timestamp_ms=emb.timestamp_ms,
                    score=round(sim, 4),
                    metadata=emb.metadata,
                )
            )

        # Sort by similarity descending
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    def size(self) -> int:
        return len(self._embeddings)

    def clear(self) -> None:
        self._embeddings.clear()
