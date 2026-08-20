from media_service.embeddings.provider import MockVisualEmbeddingProvider
from shared.contracts.enums import VisualEmbeddingModel


def test_mock_embedding_provider_consistency():
    provider = MockVisualEmbeddingProvider(dimension=512, model_name=VisualEmbeddingModel.CLIP_VIT_B32)
    
    # Same inputs produce identical embeddings
    emb1 = provider.embed_image("image1.jpg", "media1", "frame1", 1000)
    emb2 = provider.embed_image("image1.jpg", "media1", "frame1", 1000)
    assert emb1.vector == emb2.vector
    assert emb1.dimension == 512

    # Different inputs produce different embeddings
    emb3 = provider.embed_image("image2.jpg", "media1", "frame2", 2000)
    assert emb1.vector != emb3.vector

    # Text embedding consistency
    txt1 = provider.embed_text("sunset over mountains")
    txt2 = provider.embed_text("sunset over mountains")
    txt3 = provider.embed_text("city skyline at night")
    assert txt1.vector == txt2.vector
    assert txt1.vector != txt3.vector
