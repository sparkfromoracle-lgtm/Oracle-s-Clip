from shared.contracts.enums import VisualEmbeddingModel
from media_service.embeddings.provider import MockVisualEmbeddingProvider
from vector_index_service.service import VectorIndexService
from vector_index_service.filters.vector_search_filter import VectorSearchFilter


def test_text_to_image_retrieval_flow():
    provider = MockVisualEmbeddingProvider(dimension=512, model_name=VisualEmbeddingModel.CLIP_VIT_B32)
    index = VectorIndexService(dimension=512)

    emb1 = provider.embed_image("sunset.jpg", "media_1", "frame_1", 1000)
    emb2 = provider.embed_image("ocean.jpg", "media_1", "frame_2", 2000)
    emb3 = provider.embed_image("car.jpg", "media_2", "frame_1", 1000)

    index.insert_batch([emb1, emb2, emb3])
    assert index.size() == 3

    query = provider.embed_text("beautiful sunset")
    results = index.search(query, top_k=2)

    assert len(results) == 2
    assert results[0].score >= results[1].score


def test_vector_search_with_filter():
    provider = MockVisualEmbeddingProvider(dimension=512)
    index = VectorIndexService(dimension=512)

    emb1 = provider.embed_image("sunset.jpg", "media_1", "frame_1", 1000)
    emb2 = provider.embed_image("ocean.jpg", "media_2", "frame_1", 1000)
    index.insert_batch([emb1, emb2])

    query = provider.embed_text("ocean")
    flt = VectorSearchFilter(media_ids=["media_2"])
    results = index.search(query, top_k=5, search_filter=flt)

    assert len(results) == 1
    assert results[0].media_id == "media_2"
