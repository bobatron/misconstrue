"""Party mode: a generated dance beat, with each word of the sentence landing on a beat.

The music is synthesised here (no recordings, so no licensing): a four-on-the-floor kick, claps
on beats 2 and 4, off-beat hi-hats, an off-beat bass line and chords that "pump" with the kick,
over an Am-F-C-G progression.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from app.core.phonetics import Phone
from app.core.splice import Span

INTRO_BEATS = 4  # one bar of music before the first word
OUTRO_BEATS = 4  # and one after the last
# Am, F, C, G: (bass root Hz, chord tones Hz), one chord per bar.
PROGRESSION = [
    (110.00, (220.00, 261.63, 329.63)),  # A minor
    (87.31, (174.61, 220.00, 261.63)),  # F major
    (130.81, (261.63, 329.63, 392.00)),  # C major
    (98.00, (196.00, 246.94, 293.66)),  # G major
]


def beat_seconds(bpm: float) -> float:
    return 60.0 / bpm


# ── Instruments ────────────────────────────────────────────────────────────────


def _kick(sr: int) -> np.ndarray:
    t = np.arange(int(0.35 * sr)) / sr
    freq = 45 + 85 * np.exp(-t * 32)  # fast pitch drop: the "thump"
    phase = 2 * np.pi * np.cumsum(freq) / sr
    body = np.sin(phase) * np.exp(-t * 7)
    click = np.exp(-t * 400) * 0.3
    return (body + click).astype(np.float32)


def _noise_hit(sr: int, length_s: float, decay: float, rng: np.random.Generator, bright: bool) -> np.ndarray:
    n = rng.standard_normal(int(length_s * sr)).astype(np.float32)
    if bright:  # crude high-pass: differences keep the hiss, drop the rumble
        n = np.diff(n, prepend=0).astype(np.float32)
    t = np.arange(len(n)) / sr
    return n * np.exp(-t * decay).astype(np.float32)


def _clap(sr: int, rng: np.random.Generator) -> np.ndarray:
    out = np.zeros(int(0.25 * sr), dtype=np.float32)
    for delay in (0.0, 0.011, 0.023):  # a few quick bursts make it sound like hands
        hit = _noise_hit(sr, 0.2, 28, rng, bright=True) * 0.5
        start = int(delay * sr)
        out[start : start + len(hit)] += hit[: len(out) - start]
    return out


def _saw(freq: float, t: np.ndarray, harmonics: int = 10, detune: float = 0.0) -> np.ndarray:
    """Band-limited sawtooth by adding harmonics (no aliasing, no filter needed)."""
    f = freq * (1 + detune)
    return sum(np.sin(2 * np.pi * k * f * t) / k for k in range(1, harmonics + 1)).astype(np.float32)


def track(bpm: float, beats: int, sr: int, seed: int = 7) -> np.ndarray:
    """`beats` beats of dance music (mono, float32, peak ~0.9)."""
    rng = np.random.default_rng(seed)
    beat = beat_seconds(bpm)
    n = int(math.ceil(beats * beat * sr)) + sr  # a second of tail for the last hits to ring out
    out = np.zeros(n, dtype=np.float32)
    kick, clap = _kick(sr), _clap(sr, rng)
    hat = _noise_hit(sr, 0.06, 70, rng, bright=True) * 0.25

    def place(sound: np.ndarray, at_s: float, gain: float = 1.0) -> None:
        i = int(at_s * sr)
        if i < n:
            out[i : i + len(sound)] += gain * sound[: n - i]

    for b in range(beats):
        t0 = b * beat
        bar, beat_in_bar = divmod(b, 4)
        root, chord = PROGRESSION[bar % len(PROGRESSION)]
        place(kick, t0, 0.9)
        if beat_in_bar in (1, 3):
            place(clap, t0, 0.55)
        place(hat, t0 + beat / 2)  # off-beat hats
        # Off-beat bass note.
        tb = np.arange(int(beat * 0.45 * sr)) / sr
        bass = _saw(root, tb, harmonics=6) * np.exp(-tb * 6).astype(np.float32) * 0.22
        place(bass, t0 + beat / 2)
        # Chord for this beat, pumping: quiet on the kick, swelling back up before the next one.
        tc = np.arange(int(beat * sr)) / sr
        pump = (0.15 + 0.85 * np.clip(tc / (beat * 0.6), 0, 1)).astype(np.float32)
        pad = sum(_saw(f, tc, harmonics=5, detune=d) for f in chord for d in (-0.004, 0.004)) / 6
        place(pad * pump * 0.12, t0)
    peak = float(np.max(np.abs(out))) or 1.0
    return out / peak * 0.9


# ── Words on the beat ──────────────────────────────────────────────────────────


def split_at_words(spans: list[Span], target: list[Phone]) -> list[tuple[int, Span]]:
    """Each cut piece tagged with its target word; pieces that run across a word boundary are split
    there, so every word can start on its own beat."""
    out: list[tuple[int, Span]] = []
    for sp in spans:
        start = sp.t_start
        for k in range(sp.t_start + 1, sp.t_end + 1):
            if k == sp.t_end or target[k].word_index != target[k - 1].word_index:
                out.append((target[start].word_index, Span(start, k, sp.s_start + (start - sp.t_start))))
                start = k
    return out


@dataclass
class WordSlot:
    word_index: int
    start_s: float  # on a beat
    end_s: float  # when the word's audio ends
    beats: int  # beats it occupies


def lay_out(word_lengths: list[tuple[int, float]], bpm: float) -> tuple[list[WordSlot], int]:
    """Start each word on a beat after a 1-bar intro; a word longer than a beat takes as many beats
    as it needs (with a little slack so a word just over a beat doesn't double its gap).
    Returns the slots and the total number of beats, rounded up to whole bars."""
    beat = beat_seconds(bpm)
    slots, b = [], INTRO_BEATS
    for word_index, length in word_lengths:
        beats = max(1, math.ceil(length / beat - 0.15))
        slots.append(WordSlot(word_index, b * beat, b * beat + length, beats))
        b += beats
    total = b + OUTRO_BEATS
    return slots, int(math.ceil(total / 4) * 4)


def duck(music: np.ndarray, voice: np.ndarray, sr: int, depth: float) -> np.ndarray:
    """Turn the music down while someone is speaking (smoothed), so the words stay clear."""
    win = int(0.05 * sr)
    level = np.sqrt(np.convolve(voice**2, np.ones(win) / win, mode="same"))
    level = level / (float(level.max()) or 1.0)
    smooth = np.convolve(level, np.ones(win * 3) / (win * 3), mode="same")
    return (music * (1 - depth * np.clip(smooth * 3, 0, 1))).astype(np.float32)
