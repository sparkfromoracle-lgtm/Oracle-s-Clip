import os
from typing import Dict, Optional, Tuple
from shared.errors.errors import ValidationError


# Known magic byte signatures for media containers
KNOWN_MEDIA_SIGNATURES: Dict[str, bytes] = {
    "mp4_ftyp": b"ftyp",            # MP4 / M4V (offset 4)
    "mkv_webm": b"\x1a\x45\xdf\xa3", # Matroska / WebM
    "riff_avi_wav": b"RIFF",        # AVI / WAV
    "ogg": b"OggS",                 # OGG
    "flv": b"FLV",                  # Flash Video
    "id3_mp3": b"ID3",              # MP3 with ID3 tag
}


class MediaGuard:
    """Enforces media security boundaries, file size limits, and container sanity checks."""

    def __init__(
        self,
        max_file_size_bytes: int = 500 * 1024 * 1024,  # 500 MB default limit
        min_file_size_bytes: int = 64,                  # Non-trivial header size
        allowed_extensions: Optional[Tuple[str, ...]] = None,
    ):
        self.max_file_size_bytes = max_file_size_bytes
        self.min_file_size_bytes = min_file_size_bytes
        self.allowed_extensions = allowed_extensions or (
            ".mp4", ".mov", ".mkv", ".webm", ".avi", ".wav", ".mp3", ".m4a", ".aac"
        )

    def validate_file_path(self, file_path: str) -> None:
        """Validates that a local media file exists, is non-empty, within size bounds, and has valid header."""
        if not file_path or not isinstance(file_path, str):
            raise ValidationError("Media file path must be a non-empty string.")

        if not os.path.exists(file_path):
            raise ValidationError(f"Media file does not exist: '{file_path}'")

        if not os.path.isfile(file_path):
            raise ValidationError(f"Media path is not a regular file: '{file_path}'")

        size = os.path.getsize(file_path)
        if size < self.min_file_size_bytes:
            raise ValidationError(
                f"Media file '{file_path}' is too small ({size} bytes). Minimum required: {self.min_file_size_bytes} bytes."
            )

        if size > self.max_file_size_bytes:
            raise ValidationError(
                f"Media file size ({size} bytes) exceeds maximum allowable limit of {self.max_file_size_bytes} bytes."
            )

        # Check extension
        _, ext = os.path.splitext(file_path.lower())
        if ext and ext not in self.allowed_extensions:
            raise ValidationError(
                f"File extension '{ext}' is not in allowed media extensions: {self.allowed_extensions}"
            )

        # Inspect header bytes for valid media container structure
        with open(file_path, "rb") as f:
            header = f.read(32)

        if not self._is_valid_media_header(header):
            raise ValidationError(
                f"Media file '{file_path}' does not contain recognized video/audio container headers (malformed or corrupt)."
            )

    def validate_bytes(self, data: bytes, filename: Optional[str] = None) -> None:
        """Validates in-memory media bytes."""
        if not data or len(data) < self.min_file_size_bytes:
            raise ValidationError(f"Media payload is too small ({len(data)} bytes).")

        if len(data) > self.max_file_size_bytes:
            raise ValidationError(
                f"Media payload size ({len(data)} bytes) exceeds limit of {self.max_file_size_bytes} bytes."
            )

        if filename:
            _, ext = os.path.splitext(filename.lower())
            if ext and ext not in self.allowed_extensions:
                raise ValidationError(f"Extension '{ext}' is not allowed.")

        header = data[:32]
        if not self._is_valid_media_header(header):
            raise ValidationError("Media payload header is corrupt or unrecognized container format.")

    def _is_valid_media_header(self, header: bytes) -> bool:
        """Checks if header matches any known audio/video container signatures."""
        if len(header) < 8:
            return False

        # ISO BMFF (MP4, MOV, M4V, etc.): offset 4 contains 'ftyp' or offset 0 is 0x00 0x00
        if len(header) >= 8 and (header[4:8] == b"ftyp" or header[4:8] == b"moov" or header[4:8] == b"free" or header[4:8] == b"mdat"):
            return True

        # MKV / WebM: starts with \x1a\x45\xdf\xa3
        if header.startswith(b"\x1a\x45\xdf\xa3"):
            return True

        # RIFF (WAV, AVI)
        if header.startswith(b"RIFF"):
            return True

        # OGG
        if header.startswith(b"OggS"):
            return True

        # FLV
        if header.startswith(b"FLV"):
            return True

        # MP3 ID3
        if header.startswith(b"ID3") or (header[0] == 0xFF and (header[1] & 0xE0) == 0xE0):
            return True

        # MPEG-TS sync byte
        if header[0] == 0x47:
            return True

        return False
