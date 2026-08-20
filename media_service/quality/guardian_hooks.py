import abc
from datetime import datetime
from typing import Any, Dict, List, Optional
from shared.contracts.enums import QualityVerdict
from shared.contracts.jobs import QualityMetric, QualityReport, RenderedAsset


class QualityChecker:
    """Phase 13.4: Deterministic Quality Checker for Rendered Assets.
    
    Evaluates rendered media properties against defined quality thresholds.
    """

    def __init__(
        self,
        min_duration_ms: int = 1000,
        min_width: int = 480,
        min_height: int = 480,
        min_bitrate: Optional[int] = 500_000,
    ):
        self.min_duration_ms = min_duration_ms
        self.min_width = min_width
        self.min_height = min_height
        self.min_bitrate = min_bitrate

    def check(self, asset: RenderedAsset) -> QualityReport:
        metrics: List[QualityMetric] = []
        now_str = datetime.utcnow().isoformat() + "Z"

        # 1. Duration Check
        dur_pass = asset.duration_ms >= self.min_duration_ms
        metrics.append(
            QualityMetric(
                name="duration_ms",
                score=1.0 if dur_pass else 0.0,
                threshold=float(self.min_duration_ms),
                passed=dur_pass,
                details=f"Duration: {asset.duration_ms}ms (min: {self.min_duration_ms}ms)",
            )
        )

        # 2. Resolution Width Check
        w_pass = asset.width >= self.min_width
        metrics.append(
            QualityMetric(
                name="width",
                score=1.0 if w_pass else 0.0,
                threshold=float(self.min_width),
                passed=w_pass,
                details=f"Width: {asset.width}px (min: {self.min_width}px)",
            )
        )

        # 3. Resolution Height Check
        h_pass = asset.height >= self.min_height
        metrics.append(
            QualityMetric(
                name="height",
                score=1.0 if h_pass else 0.0,
                threshold=float(self.min_height),
                passed=h_pass,
                details=f"Height: {asset.height}px (min: {self.min_height}px)",
            )
        )

        # 4. Bitrate Check (if available)
        if asset.bitrate is not None and self.min_bitrate is not None:
            b_pass = asset.bitrate >= self.min_bitrate
            metrics.append(
                QualityMetric(
                    name="bitrate",
                    score=1.0 if b_pass else (float(asset.bitrate) / self.min_bitrate),
                    threshold=float(self.min_bitrate),
                    passed=b_pass,
                    details=f"Bitrate: {asset.bitrate} bps (min: {self.min_bitrate} bps)",
                )
            )

        passed_count = sum(1 for m in metrics if m.passed)
        overall_score = passed_count / len(metrics) if metrics else 0.0

        if overall_score >= 1.0:
            verdict = QualityVerdict.PASS
            summary = "All quality checks passed successfully."
        elif overall_score >= 0.75:
            verdict = QualityVerdict.WARN
            summary = f"Quality checks passed with warnings ({passed_count}/{len(metrics)} passed)."
        else:
            verdict = QualityVerdict.FAIL
            summary = f"Quality checks failed ({passed_count}/{len(metrics)} passed)."

        return QualityReport(
            report_id=f"qr_{asset.asset_id}_{int(datetime.utcnow().timestamp())}",
            asset_id=asset.asset_id,
            verdict=verdict,
            overall_score=round(overall_score, 4),
            metrics=metrics,
            created_at=now_str,
            summary=summary,
        )


class GuardianHook(abc.ABC):
    """Abstract interface for Guardian policy evaluation hook."""

    @abc.abstractmethod
    def evaluate(self, report: QualityReport) -> Dict[str, Any]:
        pass


class PassThroughGuardianHook(GuardianHook):
    """Deterministic default Guardian Hook that respects the QualityReport verdict."""

    def evaluate(self, report: QualityReport) -> Dict[str, Any]:
        approved = report.verdict in {QualityVerdict.PASS, QualityVerdict.WARN}
        return {
            "approved": approved,
            "verdict": report.verdict.value,
            "score": report.overall_score,
            "policy": "passthrough",
            "report_id": report.report_id,
            "asset_id": report.asset_id,
            "action": "publish" if approved else "reject",
        }
