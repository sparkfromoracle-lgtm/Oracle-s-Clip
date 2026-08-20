from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class VectorSearchFilter:
    media_ids: Optional[List[str]] = None
    min_timestamp_ms: Optional[int] = None
    max_timestamp_ms: Optional[int] = None
    metadata_filters: Dict[str, Any] = field(default_factory=dict)

    def matches(self, media_id: str, timestamp_ms: int, metadata: Dict[str, Any]) -> bool:
        if self.media_ids is not None and media_id not in self.media_ids:
            return False
        if self.min_timestamp_ms is not None and timestamp_ms < self.min_timestamp_ms:
            return False
        if self.max_timestamp_ms is not None and timestamp_ms > self.max_timestamp_ms:
            return False
        for k, v in self.metadata_filters.items():
            if metadata.get(k) != v:
                return False
        return True
