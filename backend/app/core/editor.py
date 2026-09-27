"""Cut the recording at phone boundaries and stitch the target sentence back together."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from app import config
from app.core import media
from app.core.aligner import Alignment
from app.core.splice import Span

LEAD_S = 0.3  # footage (with silence) shown before and after the spliced speech


@dataclass
class Segment:
    src_start: float
    src_end: float
    out_start: float = 0.0

    @property
    def duration(self) -> float:
        return self.src_end - self.src_start


def _snap(audio: np.ndarray, sr: int, t: float) -> float:
    """Move a cut point to the quietest 5 ms window within SNAP_WINDOW_MS."""
    win = int(sr * 0.005)
    reach = int(sr * config.SNAP_WINDOW_MS / 1000)
    centre = int(t * sr)
    lo, hi = max(0, centre - reach), min(len(audio) - win, centre + reach)
    if hi <= lo:
        return t
    starts = np.arange(lo, hi, max(1, win // 2))
    energy = [float(np.sum(audio[s : s + win] ** 2)) for s in starts]
    return (starts[int(np.argmin(energy))] + win / 2) / sr


def segments_for(spans: list[Span], alignment: Alignment, audio: np.ndarray, sr: int) -> list[Segment]:
    segs = []
    for sp in spans:
        start = alignment.times[sp.s_start][0]
        end = alignment.times[sp.s_end - 1][1]
        segs.append(Segment(_snap(audio, sr, start), _snap(audio, sr, end)))
    return segs


def _stitch(segs: list[Segment], audio: np.ndarray, sr: int) -> np.ndarray:
    xf = int(sr * config.CROSSFADE_MS / 1000)
    clips = [audio[int(s.src_start * sr) : int(s.src_end * sr)].copy() for s in segs]

    # Even out loudness so fragments from loud and quiet words match.
    rms = np.array([np.sqrt(np.mean(c**2)) if len(c) else 0.0 for c in clips])
    target = float(np.median(rms[rms > 0])) if np.any(rms > 0) else 0.0
    for c, r in zip(clips, rms):
        if r > 0:
            c *= float(np.clip(target / r, 0.6, 1.8))

    lead = np.zeros(int(sr * LEAD_S), dtype=audio.dtype)
    out = lead.copy()
    fade_in = np.linspace(0, 1, xf, dtype=audio.dtype)
    for seg, c in zip(segs, clips):
        k = min(xf, len(c), len(out) - len(lead)) if len(out) > len(lead) else 0
        seg.out_start = (len(out) - k) / sr
        if k:
            out[-k:] = out[-k:] * fade_in[::-1][-k:] + c[:k] * fade_in[:k]
        out = np.concatenate([out, c[k:]])
    out = np.concatenate([out, lead])
    peak = float(np.max(np.abs(out))) if len(out) else 0.0
    return out / peak * 0.95 if peak > 0.95 else out


def _frames(segs: list[Segment], frames: np.ndarray, total_s: float) -> np.ndarray:
    """For each output frame, pick the source frame that matches the audio playing at that moment."""
    fps = config.FPS
    n_out = int(np.ceil(total_s * fps))
    idx = np.empty(n_out, dtype=int)
    starts = [s.out_start for s in segs]
    for f in range(n_out):
        t = f / fps
        if t < starts[0]:
            src_t = segs[0].src_start - (starts[0] - t)  # lead-in: footage just before speech
        else:
            i = int(np.searchsorted(starts, t, side="right")) - 1
            src_t = segs[i].src_start + (t - starts[i])
            if i == len(segs) - 1:
                src_t = min(src_t, segs[i].src_end + LEAD_S)  # tail: footage just after
        idx[f] = int(round(src_t * fps))
    return frames[np.clip(idx, 0, len(frames) - 1)]


def render(spans: list[Span], alignment: Alignment, norm: media.Normalised, out: Path, workdir: Path) -> Path:
    audio, sr = sf.read(norm.wav48, dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    # Alignment was done on the 16 kHz file; times are in seconds so they carry over.
    segs = segments_for(spans, alignment, audio, sr)
    stitched = _stitch(segs, audio, sr)
    out_wav = workdir / "stitched.wav"
    sf.write(out_wav, stitched, sr)
    frames = _frames(segs, media.read_frames(norm.video), len(stitched) / sr)
    media.write_video(frames, out_wav, out, workdir)
    return out
