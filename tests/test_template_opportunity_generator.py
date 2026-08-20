from shared.contracts.media import MediaMetadata, SceneBoundary
from media_service.opportunities.template_generator import TemplateOpportunityGenerator


def test_template_opportunity_generator_opening_and_scenes():
    gen = TemplateOpportunityGenerator(default_opening_duration_ms=15000, max_opportunities=5)
    meta = MediaMetadata(duration_ms=30000, format_name="mp4")
    scenes = [
        SceneBoundary(scene_index=0, start_ms=0, end_ms=5000),
        SceneBoundary(scene_index=1, start_ms=5000, end_ms=15000),
        SceneBoundary(scene_index=2, start_ms=15000, end_ms=30000),
    ]

    opps = gen.generate(source_media_id="media_101", metadata=meta, scenes=scenes)
    assert len(opps) > 0
    # Highest score opportunity should be opening_window (0.95)
    assert opps[0].template_name == "opening_window"
    assert opps[0].start_ms == 0
    assert opps[0].end_ms == 15000

    # Check deduplication & deterministic ordering
    seen_ids = set()
    for o in opps:
        assert o.opportunity_id not in seen_ids
        seen_ids.add(o.opportunity_id)
        assert o.source_media_id == "media_101"


def test_template_opportunity_generator_zero_duration():
    gen = TemplateOpportunityGenerator()
    meta = MediaMetadata(duration_ms=0, format_name="mp4")
    assert gen.generate(source_media_id="media_102", metadata=meta) == []


def test_template_opportunity_generator_fallback():
    gen = TemplateOpportunityGenerator(default_opening_duration_ms=5000)
    meta = MediaMetadata(duration_ms=20000, format_name="mp4")
    opps = gen.generate(source_media_id="media_103", metadata=meta, scenes=None)
    assert len(opps) >= 1
    assert any(o.template_name == "full_duration_fallback" for o in opps)
