from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from shared.contracts.enums import MediaType


@dataclass(frozen=True)
class MediaMetadata:
    duration_ms: int
    format_name: str
    width: Optional[int] = None
    height: Optional[int] = None
    frame_rate: Optional[float] = None
    bitrate: Optional[int] = None
    audio_channels: Optional[int] = None
    audio_sample_rate: Optional[int] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MediaItem:
    media_id: str
    tenant_id: str
    media_type: MediaType
    storage_path: str
    metadata: Optional[MediaMetadata] = None
    content_hash: Optional[str] = None


@dataclass(frozen=True)
class SceneBoundary:
    scene_index: int
    start_ms: int
    end_ms: int
    score: float = 1.0


@dataclass(frozen=True)
class ExtractedFrame:
    frame_id: str
    media_id: str
    timestamp_ms: int
    scene_index: int
    storage_path: str
    width: int
    height: int
    content_hash: Optional[str] = None


@dataclass(frozen=True)
class TranscriptWord:
    word: str
    start_ms: int
    end_ms: int
    confidence: float = 1.0


@dataclass(frozen=True)
class TranscriptSegment:
    segment_id: str
    start_ms: int
    end_ms: int
    text: str
    words: List[TranscriptWord] = field(default_factory=list)
    confidence: float = 1.0


@dataclass(frozen=True)
class TranscriptionResult:
    media_id: str
    language: str
    segments: List[TranscriptSegment]
    raw_text: str
    duration_ms: int
