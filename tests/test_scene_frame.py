from media_service.scenes.scene_frame import SceneFrameExtractor


def test_scene_detection_uniform():
    extractor = SceneFrameExtractor()
    scenes = extractor.detect_scenes(video_path="mock.mp4", duration_ms=12000)
    assert len(scenes) == 3
    assert scenes[0].start_ms == 0
    assert scenes[0].end_ms == 5000
    assert scenes[1].start_ms == 5000
    assert scenes[1].end_ms == 10000
    assert scenes[2].start_ms == 10000
    assert scenes[2].end_ms == 12000


def test_scene_detection_zero_duration():
    extractor = SceneFrameExtractor()
    assert extractor.detect_scenes(video_path="mock.mp4", duration_ms=0) == []
