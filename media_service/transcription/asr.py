import abc
from typing import List, Optional
from shared.contracts.media import TranscriptionResult, TranscriptSegment, TranscriptWord
from shared.contracts.enums import ASRProviderType
from shared.errors.errors import TranscriptionError, DependencyUnavailableError


class ASRProvider(abc.ABC):
    """Abstract interface for Automated Speech Recognition."""

    @abc.abstractmethod
    def transcribe(self, audio_or_video_path: str, language: Optional[str] = None) -> TranscriptionResult:
        pass


class MockASRProvider(ASRProvider):
    """Deterministic Mock ASR provider for testing and development."""

    def __init__(self, default_text: str = "Welcome to Oracle Clip automated speech transcription."):
        self.default_text = default_text

    def transcribe(self, audio_or_video_path: str, language: Optional[str] = None) -> TranscriptionResult:
        words_list = self.default_text.split()
        words = []
        cur_ms = 0
        step_ms = 500
        for w in words_list:
            words.append(TranscriptWord(word=w, start_ms=cur_ms, end_ms=cur_ms + step_ms, confidence=0.98))
            cur_ms += step_ms

        segment = TranscriptSegment(
            segment_id="seg_0",
            start_ms=0,
            end_ms=cur_ms,
            text=self.default_text,
            words=words,
            confidence=0.98,
        )

        return TranscriptionResult(
            media_id="mock_media",
            language=language or "en",
            segments=[segment],
            raw_text=self.default_text,
            duration_ms=cur_ms,
        )


class LocalASRProvider(ASRProvider):
    """Local ASR provider using faster-whisper or whisper. Fails closed if not installed in prod."""

    def __init__(self, model_size: str = "base", device: str = "cpu"):
        self.model_size = model_size
        self.device = device
        self._model = None

    def _get_model(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
                self._model = WhisperModel(self.model_size, device=self.device, compute_type="int8")
            except ImportError:
                try:
                    import whisper
                    self._model = whisper.load_model(self.model_size, device=self.device)
                except ImportError:
                    raise DependencyUnavailableError(
                        "Neither 'faster-whisper' nor 'openai-whisper' is installed for LocalASRProvider."
                    )
        return self._model

    def transcribe(self, audio_or_video_path: str, language: Optional[str] = None) -> TranscriptionResult:
        model = self._get_model()
        try:
            if hasattr(model, "transcribe"):
                # Check if faster-whisper (returns segments generator) or whisper (returns dict)
                import inspect
                sig = inspect.signature(model.transcribe)
                if "language" in sig.parameters:
                    res = model.transcribe(audio_or_video_path, language=language)
                else:
                    res = model.transcribe(audio_or_video_path)

                if isinstance(res, tuple):  # faster-whisper: (segments, info)
                    segments_gen, info = res
                    segments = []
                    all_text = []
                    seg_idx = 0
                    for s in segments_gen:
                        words = []
                        if hasattr(s, "words") and s.words:
                            for w in s.words:
                                words.append(TranscriptWord(
                                    word=w.word,
                                    start_ms=int(w.start * 1000),
                                    end_ms=int(w.end * 1000),
                                    confidence=getattr(w, "probability", 1.0)
                                ))
                        seg = TranscriptSegment(
                            segment_id=f"seg_{seg_idx}",
                            start_ms=int(s.start * 1000),
                            end_ms=int(s.end * 1000),
                            text=s.text.strip(),
                            words=words,
                            confidence=getattr(s, "avg_logprob", 1.0),
                        )
                        segments.append(seg)
                        all_text.append(s.text.strip())
                        seg_idx += 1
                    raw_text = " ".join(all_text)
                    total_dur = segments[-1].end_ms if segments else 0
                    return TranscriptionResult(
                        media_id=audio_or_video_path,
                        language=getattr(info, "language", language or "en"),
                        segments=segments,
                        raw_text=raw_text,
                        duration_ms=total_dur,
                    )
                elif isinstance(res, dict):  # whisper dict
                    segments = []
                    seg_idx = 0
                    for s in res.get("segments", []):
                        seg = TranscriptSegment(
                            segment_id=f"seg_{seg_idx}",
                            start_ms=int(s.get("start", 0) * 1000),
                            end_ms=int(s.get("end", 0) * 1000),
                            text=s.get("text", "").strip(),
                            confidence=0.95,
                        )
                        segments.append(seg)
                        seg_idx += 1
                    return TranscriptionResult(
                        media_id=audio_or_video_path,
                        language=res.get("language", language or "en"),
                        segments=segments,
                        raw_text=res.get("text", "").strip(),
                        duration_ms=segments[-1].end_ms if segments else 0,
                    )
        except Exception as e:
            if isinstance(e, DependencyUnavailableError):
                raise e
            raise TranscriptionError(f"Local ASR transcription failed: {e}")
