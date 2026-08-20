from shared.hashing.content_hash import compute_content_hash, compute_media_segment_hash


def test_compute_content_hash():
    h1 = compute_content_hash("test_payload_1")
    h2 = compute_content_hash("test_payload_1")
    h3 = compute_content_hash("test_payload_2")

    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 64  # SHA-256 hex length


def test_compute_media_segment_hash():
    s1 = compute_media_segment_hash("m1", 0, 5000)
    s2 = compute_media_segment_hash("m1", 0, 5000)
    s3 = compute_media_segment_hash("m1", 0, 6000)

    assert s1 == s2
    assert s1 != s3
