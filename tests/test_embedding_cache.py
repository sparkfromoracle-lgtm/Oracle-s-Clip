from shared.contracts.enums import VisualEmbeddingModel
from shared.contracts.visual_embedding import VisualEmbedding
from media_service.embeddings.cache import EmbeddingCache


def test_embedding_cache_operations():
    cache = EmbeddingCache()
    assert cache.size() == 0

    emb = VisualEmbedding(
        embedding_id="emb_1",
        media_id="med_1",
        frame_id="f_1",
        timestamp_ms=1000,
        model_name=VisualEmbeddingModel.CLIP_VIT_B32,
        vector=[0.1] * 512,
        dimension=512,
    )

    cache.set("hash_123", emb)
    assert cache.size() == 1
    assert cache.contains("hash_123") is True
    assert cache.get("hash_123") == emb

    assert cache.contains("non_existent") is False
    assert cache.get("non_existent") is None

    cache.clear()
    assert cache.size() == 0
