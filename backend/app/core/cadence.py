"""Cadence: how closely the finished video's rhythm matches a reference recording.

The reference is someone saying the target sentence the way the video should sound (recorded on
the tuning page). Both are timed word by word with the aligner, then compared: overall length,
the gaps between words, and how far each word's start is from where it falls in the reference.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from app.core import aligner, phonetics

WordTimes = list[tuple[str, float, float]]  # (word, start, end) in seconds


def word_times(media_path: Path, text: str) -> WordTimes:
    """When each word of `text` is spoken in an audio or video file."""
    with tempfile.TemporaryDirectory(prefix="cadence_") as tmp:
        wav = Path(tmp) / "audio.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(media_path), "-vn", "-ac", "1", "-ar", "16000", str(wav)],
                       check=True)
        return aligner.align(wav, text).words


def _onsets(times: WordTimes) -> list[float]:
    return [s - times[0][1] for _, s, _ in times]


def _gaps(times: WordTimes) -> list[float]:
    return [max(0.0, times[i + 1][1] - times[i][2]) for i in range(len(times) - 1)]


def compare(reference: WordTimes, output: WordTimes) -> dict:
    """Numbers for how the output's rhythm differs from the reference's (both for the same words)."""
    n = min(len(reference), len(output))
    if n == 0:
        return {}
    ref, out = reference[:n], output[:n]
    ref_len = ref[-1][2] - ref[0][1]
    out_len = out[-1][2] - out[0][1]
    ref_gaps, out_gaps = _gaps(ref), _gaps(out)
    onset_err = [abs(a - b) for a, b in zip(_onsets(ref), _onsets(out))]
    return {
        "length_ratio": round(out_len / ref_len, 2) if ref_len else None,  # 1.0 = same overall length
        "ref_gap_ms": round(1000 * sum(ref_gaps) / len(ref_gaps)) if ref_gaps else 0,
        "out_gap_ms": round(1000 * sum(out_gaps) / len(out_gaps)) if out_gaps else 0,
        "onset_error_ms": round(1000 * sum(onset_err) / n),  # average distance of word starts from the reference
    }


def summary(c: dict) -> str:
    if not c:
        return "no cadence"
    return (f"length ×{c['length_ratio']}, gaps {c['out_gap_ms']} ms (ref {c['ref_gap_ms']} ms), "
            f"word starts off by {c['onset_error_ms']} ms")


def target_words(text: str) -> list[str]:
    return phonetics.tokenize(text)
