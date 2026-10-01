from app.core import cadence


def test_identical_rhythm_scores_perfectly():
    ref = [("its", 0.2, 0.4), ("party", 0.45, 0.8), ("time", 0.9, 1.2)]
    shifted = [(w, s + 3.0, e + 3.0) for w, s, e in ref]  # same rhythm, later in the video
    c = cadence.compare(ref, shifted)
    assert c["length_ratio"] == 1.0 and c["onset_error_ms"] == 0 and c["out_gap_ms"] == c["ref_gap_ms"]


def test_slower_output_with_long_gaps_is_reported():
    ref = [("its", 0.0, 0.2), ("party", 0.25, 0.6), ("time", 0.65, 1.0)]  # 50 ms gaps
    out = [("its", 0.0, 0.2), ("party", 0.7, 1.05), ("time", 1.55, 1.9)]  # 500 ms gaps
    c = cadence.compare(ref, out)
    assert c["length_ratio"] == 1.9
    assert c["ref_gap_ms"] == 50 and c["out_gap_ms"] == 500
    assert c["onset_error_ms"] == 450  # (0 + 450 + 900) / 3
