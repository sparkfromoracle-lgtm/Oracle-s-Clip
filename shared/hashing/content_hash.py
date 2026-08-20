import hashlib
from typing import Union


def compute_content_hash(data: Union[str, bytes]) -> str:
    """Computes a deterministic SHA-256 content hash."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def compute_media_segment_hash(source_media_id: str, start_ms: int, end_ms: int) -> str:
    """Computes a deterministic hash for a specific media segment."""
    payload = f"{source_media_id}:{start_ms}:{end_ms}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
