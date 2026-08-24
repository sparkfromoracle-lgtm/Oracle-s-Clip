"""Non-spam publishing scheduler.

Decides whether a candidate clip is worth publishing RIGHT NOW, should be
scheduled for later, needs human review, should wait, or should be rejected.

Core principles:
- Optimize for quality, relevance, originality, audience value — NOT volume.
- Autopilot is OFF by default.
- Never create filler content to satisfy a posting quota.
- Never flood platforms or bypass platform limits.
- Can decide "Nothing worth publishing right now."
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from shared.contracts.enums import RightsStatus, ScheduleDecision, QualityVerdict

logger = logging.getLogger("oracle_clip.scheduler")

# Minimum time between publications to the same platform (anti-flood).
MIN_PLATFORM_INTERVAL_HOURS = 4

# Minimum quality score to be considered for publishing.
MIN_QUALITY_SCORE = 0.75

# Minimum opportunity score to be considered.
MIN_OPPORTUNITY_SCORE = 0.70


class PublishingScheduler:
    """Evaluates whether a candidate clip should be published now, later, or not at all."""

    def __init__(self, autopilot_enabled: bool = False):
        self.autopilot_enabled = autopilot_enabled

    def evaluate(
        self,
        quality_verdict: str,
        quality_score: float,
        opportunity_score: float,
        rights_status: str,
        guardian_approved: bool,
        last_publish_time: Optional[datetime] = None,
        platform: Optional[str] = None,
        posts_today: int = 0,
        max_posts_per_day: int = 3,
    ) -> Dict[str, Any]:
        """Returns a scheduling decision with reasons.

        Possible decisions: PUBLISH, SCHEDULE, REVIEW, WAIT, REJECT.
        """
        reasons: List[str] = []

        # 1. Rights check — unknown or restricted rights block publishing.
        if rights_status in (
            RightsStatus.RIGHTS_UNKNOWN.value,
            RightsStatus.RESTRICTED.value,
            RightsStatus.EXPIRED.value,
            RightsStatus.NOT_MONETIZABLE.value,
        ):
            reasons.append(f"Rights status is '{rights_status}' — cannot publish without verified rights.")
            return self._decision(ScheduleDecision.REJECT, reasons)

        # 2. Guardian check
        if not guardian_approved:
            reasons.append("Guardian did not approve the clip.")
            return self._decision(ScheduleDecision.REJECT, reasons)

        # 3. Quality check
        if quality_verdict == QualityVerdict.FAIL.value:
            reasons.append("Quality verdict is FAIL.")
            return self._decision(ScheduleDecision.REJECT, reasons)

        if quality_score < MIN_QUALITY_SCORE:
            reasons.append(f"Quality score {quality_score:.2f} below minimum {MIN_QUALITY_SCORE}.")
            return self._decision(ScheduleDecision.REVIEW, reasons)

        # 4. Opportunity score check
        if opportunity_score < MIN_OPPORTUNITY_SCORE:
            reasons.append(f"Opportunity score {opportunity_score:.2f} below minimum {MIN_OPPORTUNITY_SCORE}.")
            return self._decision(ScheduleDecision.WAIT, reasons)

        # 5. Daily quota check — prevent flooding
        if posts_today >= max_posts_per_day:
            reasons.append(f"Daily posting limit reached ({posts_today}/{max_posts_per_day} for {platform or 'platform'}).")
            return self._decision(ScheduleDecision.WAIT, reasons)

        # 6. Anti-flood interval check
        if last_publish_time:
            elapsed = datetime.utcnow() - last_publish_time
            min_interval = timedelta(hours=MIN_PLATFORM_INTERVAL_HOURS)
            if elapsed < min_interval:
                remaining = min_interval - elapsed
                reasons.append(
                    f"Too soon since last publish to {platform or 'platform'}. "
                    f"Wait {remaining.total_seconds() / 3600:.1f}h more."
                )
                return self._decision(ScheduleDecision.SCHEDULE, reasons)

        # 7. Autopilot check — if autopilot is OFF, require human review.
        if not self.autopilot_enabled:
            reasons.append("Autopilot is OFF — manual review required before publishing.")
            return self._decision(ScheduleDecision.REVIEW, reasons)

        # All checks passed
        reasons.append("All checks passed — ready to publish.")
        return self._decision(ScheduleDecision.PUBLISH, reasons)

    @staticmethod
    def _decision(verdict: ScheduleDecision, reasons: List[str]) -> Dict[str, Any]:
        return {
            "decision": verdict.value,
            "reasons": reasons,
            "autopilot_enabled": verdict != ScheduleDecision.REVIEW or False,
        }
