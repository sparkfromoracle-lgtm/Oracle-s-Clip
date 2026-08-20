import abc
import hashlib
from typing import List, Optional
import numpy as np
from shared.contracts.enums import VisualEmbeddingModel
from shared.contracts.visual_embedding import VisualEmbedding, TextEmbedding
from shared.errors.errors import EmbeddingError, DependencyUnavailableError


class VisualEmbeddingProvider(abc.ABC):
    """Abstract interface for Visual & Text Embeddings (CLIP)."""

    @abc.abstractmethod
    def embed_image(self, image_path: str, media_id: str, frame_id: Optional[str] = None, timestamp_ms: int = 0) -> VisualEmbedding:
        pass

    @abc.abstractmethod
    def embed_text(self, text: str) -> TextEmbedding:
        pass


class MockVisualEmbeddingProvider(VisualEmbeddingProvider):
    """Deterministic mock embedding provider producing normalized pseudo-vectors."""

    def __init__(self, dimension: int = 512, model_name: VisualEmbeddingModel = VisualEmbeddingModel.CLIP_VIT_B32):
        self.dimension = dimension
        self.model_name = model_name

    def _generate_deterministic_vector(self, seed_str: str) -> List[float]:
        # Generate reproducible pseudo-random vector based on seed
        h = hashlib.sha256(seed_str.encode("utf-8")).digest()
        # Seed standard rng
        seed_int = int.from_bytes(h[:4], "big")
        rng = np.random.RandomState(seed_int)
        vec = rng.randn(self.dimension).astype(np.float32)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.tolist()

    def embed_image(self, image_path: str, media_id: str, frame_id: Optional[str] = None, timestamp_ms: int = 0) -> VisualEmbedding:
        vec = self._generate_deterministic_vector(f"img:{image_path}:{timestamp_ms}")
        return VisualEmbedding(
            embedding_id=f"emb_{media_id}_{timestamp_ms}",
            media_id=media_id,
            frame_id=frame_id,
            timestamp_ms=timestamp_ms,
            model_name=self.model_name,
            vector=vec,
            dimension=self.dimension,
        )

    def embed_text(self, text: str) -> TextEmbedding:
        vec = self._generate_deterministic_vector(f"text:{text.strip().lower()}")
        return TextEmbedding(
            query_text=text,
            model_name=self.model_name,
            vector=vec,
            dimension=self.dimension,
        )


class OpenCLIPProvider(VisualEmbeddingProvider):
    """Production OpenCLIP provider. Fails closed if torch/open_clip are not installed."""

    def __init__(self, model_name: str = "ViT-B-32", pretrained: str = "laion2b_s34b_b79k", device: str = "cpu"):
        self.model_name_str = model_name
        self.pretrained = pretrained
        self.device = device
        self._model = None
        self._preprocess = None
        self._tokenizer = None

    def _load(self):
        if self._model is None:
            try:
                import open_clip
                import torch
                model, _, preprocess = open_clip.create_model_and_transforms(
                    self.model_name_str, pretrained=self.pretrained, device=self.device
                )
                tokenizer = open_clip.get_tokenizer(self.model_name_str)
                self._model = model
                self._preprocess = preprocess
                self._tokenizer = tokenizer
            except ImportError:
                raise DependencyUnavailableError("OpenCLIP/torch dependencies are not installed.")

    def embed_image(self, image_path: str, media_id: str, frame_id: Optional[str] = None, timestamp_ms: int = 0) -> VisualEmbedding:
        self._load()
        try:
            from PIL import Image
            import torch
            image = self._preprocess(Image.open(image_path)).unsqueeze(0).to(self.device)
            with torch.no_grad():
                features = self._model.encode_image(image)
                features /= features.norm(dim=-1, keepdim=True)
            vec = features.squeeze(0).cpu().numpy().tolist()
            return VisualEmbedding(
                embedding_id=f"emb_{media_id}_{timestamp_ms}",
                media_id=media_id,
                frame_id=frame_id,
                timestamp_ms=timestamp_ms,
                model_name=VisualEmbeddingModel.CLIP_VIT_B32,
                vector=vec,
                dimension=len(vec),
            )
        except Exception as e:
            if isinstance(e, DependencyUnavailableError):
                raise e
            raise EmbeddingError(f"OpenCLIP image embedding failed: {e}")

    def embed_text(self, text: str) -> TextEmbedding:
        self._load()
        try:
            import torch
            tokens = self._tokenizer([text]).to(self.device)
            with torch.no_grad():
                features = self._model.encode_text(tokens)
                features /= features.norm(dim=-1, keepdim=True)
            vec = features.squeeze(0).cpu().numpy().tolist()
            return TextEmbedding(
                query_text=text,
                model_name=VisualEmbeddingModel.CLIP_VIT_B32,
                vector=vec,
                dimension=len(vec),
            )
        except Exception as e:
            if isinstance(e, DependencyUnavailableError):
                raise e
            raise EmbeddingError(f"OpenCLIP text embedding failed: {e}")
