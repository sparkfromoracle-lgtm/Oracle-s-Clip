from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import os
from typing import Dict, List, Optional, Tuple, Union


@dataclass(frozen=True)
class ChecksumVerificationReport:
    artifact_identity: str
    checksum_algorithm: str
    expected_checksum: Optional[str]
    calculated_checksum: str
    verification_result: str  # "VERIFIED", "MISMATCH", "COMPUTED"
    timestamp: str
    file_size_bytes: int

    def to_dict(self) -> Dict[str, Union[str, int, Optional[str]]]:
        return asdict(self)


def calculate_sha256(data_or_path: Union[str, bytes]) -> Tuple[str, int]:
    """Computes SHA-256 and byte size from file path or bytes."""
    hasher = hashlib.sha256()
    if isinstance(data_or_path, str) and os.path.exists(data_or_path):
        size = os.path.getsize(data_or_path)
        with open(data_or_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest(), size
    elif isinstance(data_or_path, str):
        data_bytes = data_or_path.encode("utf-8")
        hasher.update(data_bytes)
        return hasher.hexdigest(), len(data_bytes)
    else:
        hasher.update(data_or_path)
        return hasher.hexdigest(), len(data_or_path)


def verify_artifact_checksum(
    artifact_identity: str,
    data_or_path: Union[str, bytes],
    expected_checksum: Optional[str] = None,
    algorithm: str = "SHA-256",
) -> ChecksumVerificationReport:
    """Verifies or calculates cryptographic checksum for an artifact."""
    calc_hash, size = calculate_sha256(data_or_path)
    now_iso = datetime.now(timezone.utc).isoformat()

    if expected_checksum is None:
        result = "COMPUTED"
    elif calc_hash.lower() == expected_checksum.strip().lower():
        result = "VERIFIED"
    else:
        result = "MISMATCH"

    return ChecksumVerificationReport(
        artifact_identity=artifact_identity,
        checksum_algorithm=algorithm,
        expected_checksum=expected_checksum,
        calculated_checksum=calc_hash,
        verification_result=result,
        timestamp=now_iso,
        file_size_bytes=size,
    )


def verify_artifacts_manifest(
    artifacts: Dict[str, Union[str, bytes]],
    expected_checksums: Optional[Dict[str, str]] = None,
) -> List[ChecksumVerificationReport]:
    """Verifies a manifest of multiple artifacts."""
    reports: List[ChecksumVerificationReport] = []
    expected_map = expected_checksums or {}
    for identity, data_or_path in artifacts.items():
        exp = expected_map.get(identity)
        rep = verify_artifact_checksum(
            artifact_identity=identity,
            data_or_path=data_or_path,
            expected_checksum=exp,
        )
        reports.append(rep)
    return reports
