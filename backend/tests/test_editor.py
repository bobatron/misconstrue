import numpy as np

from app import config
from app.core import editor
from app.core.editor import Segment


def test_slowed_piece_shows_matching_frames(monkeypatch):
    monkeypatch.setattr(config.settings, "FPS", 10)
    frames = np.arange(100).reshape(100, 1, 1, 1)  # frame i shows the number i
    # One piece from 2.0-2.4 s, played twice as slowly, starting at 0.3 s in the output.
    seg = Segment(2.0, 2.4, out_start=0.3, stretch=2.0)
    out = editor._frames([seg], frames, total_s=1.1)[:, 0, 0, 0]
    # Output 0.3-1.1 s (0.8 s) must walk through source 2.0-2.4 s at half speed.
    for f in range(3, 11):
        expected_src_s = 2.0 + (f / 10 - 0.3) / 2.0
        assert abs(out[f] - round(expected_src_s * 10)) <= 1


def test_stretch_factors(monkeypatch):
    monkeypatch.setattr(config.settings, "PLAYBACK_SPEED", 0.8)
    monkeypatch.setattr(config.settings, "MIN_PIECE_MS", 150)
    long, short, tiny = Segment(0, 0.3), Segment(0, 0.1), Segment(0, 0.02)
    editor._stretch_factors([long, short, tiny])
    assert long.stretch == 1.25  # just the overall slow-down
    assert abs(short.stretch - 1.5) < 1e-9  # 0.1 s -> 0.125 s after slowing -> stretched to 0.15 s
    assert tiny.stretch == 1.25 * editor.MAX_EXTRA_STRETCH  # capped
