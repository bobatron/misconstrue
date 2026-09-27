"""Slow audio down without changing its pitch (WSOLA: waveform-similarity overlap-add).

The audio is cut into short overlapping windows that are laid down further apart than they
were taken. Each window is nudged by a few milliseconds to where it best lines up with the
previous one, which keeps the waveform continuous (no warble) and the pitch unchanged.
"""
from __future__ import annotations

import numpy as np

WINDOW_S = 0.025  # ~ a couple of voice pitch periods
TOLERANCE_S = 0.008  # how far each window may shift to line up


def stretch(x: np.ndarray, sr: int, factor: float) -> np.ndarray:
    """Return `x` made `factor` times longer (factor > 1 = slower), same pitch."""
    if abs(factor - 1.0) < 1e-3 or len(x) == 0:
        return x.copy()
    n = int(WINDOW_S * sr)
    hop_out = n // 2
    hop_in = hop_out / factor
    tol = int(TOLERANCE_S * sr)
    out_len = int(round(len(x) * factor))
    pad = n + tol
    xp = np.concatenate([np.zeros(pad, x.dtype), x, np.zeros(pad + n, x.dtype)])
    window = np.hanning(n).astype(x.dtype)
    y = np.zeros(out_len + n, dtype=np.float64)
    weight = np.zeros(out_len + n, dtype=np.float64)

    prev = pad  # start of the previously used window, in padded coordinates
    for k in range(out_len // hop_out + 1):
        nominal = pad + int(k * hop_in)
        if k == 0:
            best = nominal
        else:
            # Where would the previous window naturally have continued? Find the spot near
            # `nominal` whose waveform matches that continuation best.
            template = xp[prev + hop_out : prev + hop_out + n]
            lo = max(0, nominal - tol)
            region = xp[lo : nominal + tol + n]
            if len(region) < n:
                break
            best = lo + int(np.argmax(np.correlate(region, template, mode="valid")))
        start = k * hop_out
        seg = xp[best : best + n]
        if start + n > len(y) or len(seg) < n:
            break
        y[start : start + n] += seg * window
        weight[start : start + n] += window
        prev = best
    y = y[:out_len] / np.maximum(weight[:out_len], 1e-3)
    return y.astype(x.dtype)


def stretch_piece(audio: np.ndarray, sr: int, start: float, end: float, factor: float, context_s: float = 0.04) -> np.ndarray:
    """Stretch audio[start:end] (seconds) using a little surrounding audio as context.

    Stretching a 60 ms clip on its own smears its edges; stretching it with its neighbours
    and then cutting it back out keeps the edges clean.
    """
    a = max(0, int((start - context_s) * sr))
    s0, s1 = int(start * sr), int(end * sr)
    b = min(len(audio), int((end + context_s) * sr))
    if abs(factor - 1.0) < 1e-3:
        return audio[s0:s1].copy()
    stretched = stretch(audio[a:b], sr, factor)
    cut0 = int(round((s0 - a) * factor))
    return stretched[cut0 : cut0 + int(round((s1 - s0) * factor))]
