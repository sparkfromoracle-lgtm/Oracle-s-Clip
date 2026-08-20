from typing import List, Optional
from shared.contracts.jobs import ContentOpportunity
from shared.contracts.media import MediaMetadata, SceneBoundary


class TemplateOpportunityGenerator:
    """Phase 13.1: Zero-LLM Deterministic Template Opportunity Generator.
    
    Generates structured ContentOpportunities using deterministic rule templates:
    - opening_window (first 15-30s hook)
    - per_scene (scene-bounded segments)
    - full_duration_fallback (when no scenes detected or short video)
    
    Invariants:
    - Zero LLM dependencies
    - Zero media I/O
    - Side-effect free (no mutation of inputs)
    - Deterministic ordering
    - Duplicate window elimination
    - Respects max_opportunities
    - Handles zero/negative durations cleanly
    """

    def __init__(self, default_opening_duration_ms: int = 15000, max_opportunities: int = 10):
        self.default_opening_duration_ms = default_opening_duration_ms
        self.max_opportunities = max_opportunities

    def generate(
        self,
        source_media_id: str,
        metadata: Optional[MediaMetadata] = None,
        scenes: Optional[List[SceneBoundary]] = None,
        max_opportunities: Optional[int] = None,
    ) -> List[ContentOpportunity]:
        if not source_media_id:
            return []

        limit = max_opportunities if max_opportunities is not None else self.max_opportunities
        if limit <= 0:
            return []

        duration_ms = metadata.duration_ms if metadata else 0
        if duration_ms <= 0:
            return []

        opportunities: List[ContentOpportunity] = []
        seen_windows = set()

        def add_opportunity(start_ms: int, end_ms: int, score: float, reason: str, template_name: str):
            # Clamp to media duration
            start_ms = max(0, min(start_ms, duration_ms))
            end_ms = max(start_ms, min(end_ms, duration_ms))
            if end_ms <= start_ms:
                return

            window_key = (start_ms, end_ms)
            if window_key in seen_windows:
                return

            seen_windows.add(window_key)
            opp_id = f"opp_{source_media_id}_{len(opportunities)}_{start_ms}_{end_ms}"
            opportunities.append(
                ContentOpportunity(
                    opportunity_id=opp_id,
                    source_media_id=source_media_id,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    score=round(score, 4),
                    reason=reason,
                    template_name=template_name,
                    metadata={"duration_ms": end_ms - start_ms},
                )
            )

        # 1. Opening Window Template (High engagement hook)
        opening_end = min(duration_ms, self.default_opening_duration_ms)
        if opening_end > 0:
            add_opportunity(
                start_ms=0,
                end_ms=opening_end,
                score=0.95,
                reason="High-engagement opening hook window",
                template_name="opening_window",
            )

        # 2. Per-Scene Template
        if scenes:
            for scene in sorted(scenes, key=lambda s: s.scene_index):
                if len(opportunities) >= limit:
                    break
                s_start = max(0, scene.start_ms)
                s_end = min(duration_ms, scene.end_ms)
                if s_end > s_start:
                    add_opportunity(
                        start_ms=s_start,
                        end_ms=s_end,
                        score=0.85,
                        reason=f"Scene {scene.scene_index} bounded opportunity",
                        template_name="per_scene",
                    )

        # 3. Full Duration Fallback (if no scenes or only opening was added and space remains)
        if not opportunities or (len(opportunities) == 1 and duration_ms > self.default_opening_duration_ms):
            if len(opportunities) < limit:
                add_opportunity(
                    start_ms=0,
                    end_ms=duration_ms,
                    score=0.70,
                    reason="Full duration continuous content fallback",
                    template_name="full_duration_fallback",
                )

        # Deterministic sorting by score descending, then start_ms ascending
        sorted_opps = sorted(opportunities, key=lambda o: (-o.score, o.start_ms))
        return sorted_opps[:limit]
