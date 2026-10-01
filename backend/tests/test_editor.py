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
    monkeypatch.setattr(config.settings, "MIN_PIECE_MS", 150)
    long, short, tiny = Segment(0, 0.3), Segment(0, 0.1), Segment(0, 0.02)
    editor._stretch_factors([long, short, tiny], 0.8)
    assert long.stretch == 1.25  # just the overall slow-down
    assert abs(short.stretch - 1.5) < 1e-9  # 0.1 s -> 0.125 s after slowing -> stretched to 0.15 s
    assert tiny.stretch == 1.25 * editor.MAX_EXTRA_STRETCH  # capped


def test_long_silence_inside_a_piece_is_shortened_and_quiet_edges_trimmed(monkeypatch):
    monkeypatch.setattr(config.settings, "MAX_GAP_IN_WORD_MS", 70)
    monkeypatch.setattr(config.settings, "KEEP_GAP_IN_WORD_MS", 50)
    sr = 16000
    tone = (0.5 * np.sin(2 * np.pi * 200 * np.arange(int(0.1 * sr)) / sr)).astype(np.float32)
    silence = np.zeros(int(0.3 * sr), dtype=np.float32)
    lead = np.zeros(int(0.1 * sr), dtype=np.float32)
    # 0.1 s quiet, 0.1 s sound, 0.3 s silence (like a t closure), 0.1 s sound, 0.1 s quiet
    audio = np.concatenate([lead, tone, silence, tone, lead])
    pieces = editor.tighten(Segment(0.0, len(audio) / sr), audio, sr, level=0.35)
    assert len(pieces) == 2  # split around the long silence
    kept = sum(p.duration for p in pieces)
    # 0.2 s of sound + ~0.05 s of the silence + ~0.015 s at each quiet edge
    assert 0.25 <= kept <= 0.30
    assert pieces[0].src_start > 0.08 and pieces[-1].src_end < 0.62


def test_piece_without_silence_is_left_alone():
    sr = 16000
    tone = (0.5 * np.sin(2 * np.pi * 200 * np.arange(int(0.2 * sr)) / sr)).astype(np.float32)
    pieces = editor.tighten(Segment(0.0, 0.2), tone, sr, level=0.35)
    assert len(pieces) == 1 and abs(pieces[0].duration - 0.2) < 0.01


def test_soft_consonants_are_never_trimmed():
    sr = 16000
    breath = (0.01 * np.random.default_rng(0).standard_normal(int(0.08 * sr))).astype(np.float32)  # a quiet "h"
    tone = (0.5 * np.sin(2 * np.pi * 200 * np.arange(int(0.1 * sr)) / sr)).astype(np.float32)
    audio = np.concatenate([breath, tone])
    unprotected = editor.tighten(Segment(0.0, 0.18), audio, sr, level=0.35)
    protected = editor.tighten(Segment(0.0, 0.18, protect=((0.0, 0.08),)), audio, sr, level=0.35)
    assert unprotected[0].src_start > 0.05  # without protection the "h" looks like silence
    assert protected[0].src_start == 0.0  # with it, the "h" stays
