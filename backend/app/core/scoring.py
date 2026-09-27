"""Clarity score: how well a listener (Whisper) understands the finished video."""
from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.core import phonetics, verify_read


@dataclass
class Clarity:
    score: float  # 0-1: share of target words heard correctly (1 - word error rate, floored at 0)
    sounds: float  # 0-1: same, but comparing sounds: partial credit for near-misses ("dork" for "dark")
    heard: str


def _edit_distance(a: list, b: list) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def clarity(video: Path, target_text: str) -> Clarity:
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "out.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-ac", "1", "-ar", "16000", str(wav)], check=True)
        heard = verify_read.transcribe(wav)
    return score_text(target_text, " ".join(h.word for h in heard))


def score_text(target_text: str, heard_text: str) -> Clarity:
    # Compare by sound so homophones ("I"/"eye", "for"/"four") aren't counted as mistakes.
    target = [verify_read._key(w) for w in phonetics.tokenize(target_text)]
    got = [verify_read._key(w) for w in phonetics.tokenize(heard_text)]
    word_err = _edit_distance(target, got) / max(1, len(target))
    t_phones = [p.rstrip("0") for key in target for p in key]  # ignore stress for this score
    g_phones = [p.rstrip("0") for key in got for p in key]
    sound_err = _edit_distance(t_phones, g_phones) / max(1, len(t_phones))
    return Clarity(round(max(0.0, 1 - word_err), 3), round(max(0.0, 1 - sound_err), 3), heard_text)
