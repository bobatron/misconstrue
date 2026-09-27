import numpy as np

from app.core.stretch import stretch, stretch_piece

SR = 16000


def _tone(freq, seconds):
    t = np.arange(int(SR * seconds)) / SR
    return (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _dominant_hz(x):
    spectrum = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return np.fft.rfftfreq(len(x), 1 / SR)[int(np.argmax(spectrum))]


def test_length_changes_pitch_does_not():
    x = _tone(220, 1.0)
    for factor in (1.25, 1.5, 2.0):
        y = stretch(x, SR, factor)
        assert abs(len(y) - len(x) * factor) <= 1
        assert abs(_dominant_hz(y[2000:-2000]) - 220) < 5


def test_factor_one_is_unchanged():
    x = _tone(300, 0.3)
    assert np.array_equal(stretch(x, SR, 1.0), x)


def test_no_clicks_from_misaligned_windows():
    y = stretch(_tone(180, 1.0), SR, 1.4)[1000:-1000]
    assert np.max(np.abs(np.diff(y))) < 0.1  # a pure tone's slope stays smooth


def test_piece_uses_context_and_has_the_right_length():
    audio = _tone(200, 1.0)
    piece = stretch_piece(audio, SR, 0.40, 0.46, 1.5)
    assert abs(len(piece) - int(0.06 * SR * 1.5)) <= 2
