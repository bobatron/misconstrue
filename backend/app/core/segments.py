"""One word at a time: take the long pauses out before transcribing and aligning.

With one word per prompt, a take is mostly silence: people pause as long as they like between
words (30-40 s takes for 12 words). Processing that as one recording proved fragile: the aligner
squashed words or smeared them over silence, and Whisper's word timings broke down after long
silences (some came back zero-length), so the retake check rejected good takes.

The prompter already knows roughly where each word is (when it was on screen, and when it
heard speech). So we keep just the stretch around each word, join those stretches with short
gaps into one compact clip, transcribe and align that once (as for a normal reading), then map
every time back to the original recording, which is what the video is cut from.
(Transcribing each word separately was also tried: Whisper costs ~4 s per call however short
the clip, so 12 words took ~50 s.)
"""
from __future__ import annotations

import bisect
import logging
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from app.core import aligner, verify_read
from app.core.aligner import Alignment, AlignmentError
from app.core.verify_read import Heard

log = logging.getLogger(__name__)

EDGE_S = 0.1  # extra audio either side of a word's on-screen window
SPEECH_PAD_S = 0.35  # audio kept either side of the speech the prompter heard
GAP_S = 0.25  # silence between words in the compact clip


def windows(timings: list[dict], n_words: int, duration: float) -> list[tuple[float, float]] | None:
    """(start, end) in seconds for each word: from when it appeared until the next one did.

    None unless there's exactly one timed prompt per word (one word per prompt).
    """
    by_prompt = {t["prompt"]: t for t in timings if "prompt" in t and "shown_ms" in t}
    if n_words == 0 or sorted(by_prompt) != list(range(n_words)):
        return None
    starts = [by_prompt[i]["shown_ms"] / 1000 for i in range(n_words)]
    out = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < n_words else duration
        out.append((max(0.0, start - EDGE_S), min(duration, end + EDGE_S)))
    return out


def speech_spans(timings: list[dict], wins: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """The part of each word's window worth keeping: around the speech the prompter heard, or the
    whole window if it didn't hear any (e.g. the reader pressed Next)."""
    by_prompt = {t["prompt"]: t for t in timings}
    spans = []
    for i, (a, b) in enumerate(wins):
        t = by_prompt[i]
        s, e = t.get("speech_start_ms"), t.get("speech_end_ms")
        if s is None or e is None:
            spans.append((a, b))
        else:
            spans.append((max(a, s / 1000 - SPEECH_PAD_S), min(b, e / 1000 + SPEECH_PAD_S)))
    return spans


@dataclass
class _Piece:
    compact_start: float
    rec_start: float
    length: float


class _TimeMap:
    """Maps times in the compact clip back to the original recording."""

    def __init__(self, pieces: list[_Piece]):
        self.pieces = pieces
        self.starts = [p.compact_start for p in pieces]

    def __call__(self, t: float) -> float:
        i = max(0, bisect.bisect_right(self.starts, t) - 1)
        p = self.pieces[i]
        offset = min(max(t - p.compact_start, 0.0), p.length)  # times in a gap snap to the nearest edge
        return p.rec_start + offset


def compact_clip(wav_16k: Path, spans: list[tuple[float, float]], out: Path) -> _TimeMap:
    audio, sr = sf.read(wav_16k, dtype="float32")
    gap = np.zeros(int(GAP_S * sr), dtype=np.float32)
    parts, pieces, pos = [gap], [], GAP_S
    for a, b in spans:
        chunk = audio[int(a * sr) : int(b * sr)]
        pieces.append(_Piece(pos, a, len(chunk) / sr))
        parts += [chunk, gap]
        pos += len(chunk) / sr + GAP_S
    sf.write(out, np.concatenate(parts), sr)
    return _TimeMap(pieces)


def analyse(
    wav_16k: Path, masked_text: str, timings: list[dict], wins: list[tuple[float, float]]
) -> tuple[list[Heard], Alignment | None, dict]:
    """Transcribe and align the compact clip; return both in recording time, plus seconds spent.
    Alignment is None if the aligner couldn't fit it (the pipeline treats that as unreadable)."""
    spent = {}
    with tempfile.TemporaryDirectory(prefix="words_") as tmp:
        clip = Path(tmp) / "compact.wav"
        to_rec = compact_clip(wav_16k, speech_spans(timings, wins), clip)

        t = time.perf_counter()
        heard = [Heard(h.word, to_rec(h.start), to_rec(h.end)) for h in verify_read.transcribe(clip)]
        spent["transcribe"] = time.perf_counter() - t

        t = time.perf_counter()
        try:
            al = aligner.align(clip, masked_text)
            alignment = Alignment(
                [(w, to_rec(s), to_rec(e)) for w, s, e in al.words],
                al.phones,
                [(to_rec(s), to_rec(e)) for s, e in al.times],
            )
        except AlignmentError as exc:
            log.info("couldn't align the compact clip: %s", str(exc)[:300])
            alignment = None
        spent["align"] = time.perf_counter() - t
    return heard, alignment, spent
