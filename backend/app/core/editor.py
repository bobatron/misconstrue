"""Cut the recording at phone boundaries and stitch the target sentence back together."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from app import config
from app.core import effects, media, party
from app.core.aligner import Alignment
from app.core.phonetics import Phone
from app.core.splice import Span
from app.core.stretch import stretch_piece

MAX_EXTRA_STRETCH = 2.0  # MIN_PIECE_MS may stretch a piece at most this much beyond PLAYBACK_SPEED


@dataclass
class Segment:
    src_start: float
    src_end: float
    out_start: float = 0.0
    stretch: float = 1.0  # output duration / source duration
    protect: tuple[tuple[float, float], ...] = ()  # quiet-but-real sounds (h, f, th) never trimmed

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


# Soft consonants: nearly as quiet as silence ("h" is ~2% of speech loudness), but real sounds.
SOFT_SOUNDS = {"HH", "F", "TH", "V", "DH"}


def segments_for(spans: list[Span], alignment: Alignment, audio: np.ndarray, sr: int) -> list[Segment]:
    segs = []
    for sp in spans:
        start = alignment.times[sp.s_start][0]
        end = alignment.times[sp.s_end - 1][1]
        soft = tuple(alignment.times[k] for k in range(sp.s_start, sp.s_end)
                     if alignment.phones[k].symbol in SOFT_SOUNDS)
        segs.append(Segment(_snap(audio, sr, start), _snap(audio, sr, end), protect=soft))
    return segs


# ── Tightening: no audible gaps inside words ──────────────────────────────────
# A carrier word read on its own ends in a pause, and a final t/k/p has a long silent build-up:
# the aligner counts that silence as part of the last sound, so pieces carried 100-340 ms of
# silence into the middle of rebuilt words ("g-e-t" from "forget"). Long quiet stretches are
# shortened by splitting the piece around them, so the video still follows each part exactly.

QUIET_WIN_S = 0.005
QUIET_FRACTION = 0.06  # quieter than this share of the recording's speech level counts as silence
EDGE_KEEP_S = 0.015  # quiet kept at the start and end of a piece


def speech_level(audio: np.ndarray, sr: int) -> float:
    """A loud-speech reference for the recording (95th percentile of 10 ms loudness)."""
    win = int(0.01 * sr)
    n = len(audio) // win
    if not n:
        return 1.0
    rms = np.sqrt(np.mean(audio[: n * win].reshape(n, win) ** 2, axis=1))
    return float(np.percentile(rms, 95)) or 1.0


def _quiet_runs(clip: np.ndarray, sr: int, threshold: float) -> list[tuple[float, float]]:
    """(start, end) seconds of quiet stretches within a clip."""
    win = int(QUIET_WIN_S * sr)
    n = len(clip) // win
    if not n:
        return []
    quiet = np.sqrt(np.mean(clip[: n * win].reshape(n, win) ** 2, axis=1)) < threshold
    runs, start = [], None
    for i, q in enumerate(list(quiet) + [False]):
        if q and start is None:
            start = i
        elif not q and start is not None:
            runs.append((start * QUIET_WIN_S, i * QUIET_WIN_S))
            start = None
    return runs


def _unprotected(runs: list[tuple[float, float]], seg: Segment) -> list[tuple[float, float]]:
    """Quiet runs (relative to the piece) with any soft-consonant stretches cut out of them."""
    for a, b in seg.protect:
        a, b = a - seg.src_start, b - seg.src_start
        kept = []
        for x, y in runs:
            if y <= a or x >= b:
                kept.append((x, y))
            else:
                if x < a:
                    kept.append((x, a))
                if y > b:
                    kept.append((b, y))
        runs = kept
    return runs


def tighten(seg: Segment, audio: np.ndarray, sr: int, level: float) -> list[Segment]:
    """Trim quiet edges and shorten long silences inside a piece; returns one or more pieces."""
    if not config.TIGHTEN_PIECES:
        return [seg]
    max_gap, keep = config.MAX_GAP_IN_WORD_MS / 1000, config.KEEP_GAP_IN_WORD_MS / 1000
    clip = audio[int(seg.src_start * sr) : int(seg.src_end * sr)]
    runs = _unprotected(_quiet_runs(clip, sr, level * QUIET_FRACTION), seg)
    start, end = seg.src_start, seg.src_end
    if runs and runs[0][0] == 0:  # quiet start
        start = min(seg.src_start + max(0.0, runs[0][1] - EDGE_KEEP_S), end)
        runs = runs[1:]
    if runs and abs(runs[-1][1] - (seg.src_end - seg.src_start)) < QUIET_WIN_S * 1.5:  # quiet end
        end = max(seg.src_end - max(0.0, (runs[-1][1] - runs[-1][0]) - EDGE_KEEP_S), start)
        runs = runs[:-1]
    pieces, cursor = [], start
    for a, b in runs:
        a, b = seg.src_start + a, seg.src_start + b
        if b - a > max_gap and cursor < a < end:
            pieces.append(Segment(cursor, a + keep / 2, protect=seg.protect))
            cursor = b - keep / 2
    pieces.append(Segment(cursor, end, protect=seg.protect))
    return [p for p in pieces if p.duration > 0.005] or [Segment(seg.src_start, seg.src_end)]


def _stretch_factors(segs: list[Segment], speed: float) -> None:
    """Slow everything by `speed`, and very short pieces a bit more (MIN_PIECE_MS)."""
    base = 1.0 / speed
    min_s = config.MIN_PIECE_MS / 1000
    for seg in segs:
        factor = base
        if min_s and 0 < seg.duration * base < min_s:
            factor = base * min(MAX_EXTRA_STRETCH, min_s / (seg.duration * base))
        seg.stretch = factor


def _prepare_clips(segs: list[Segment], audio: np.ndarray, sr: int, speed: float) -> list[np.ndarray]:
    """Cut and stretch each piece, and even out loudness so pieces from loud and quiet words match."""
    _stretch_factors(segs, speed)
    clips = [stretch_piece(audio, sr, s.src_start, s.src_end, s.stretch) for s in segs]
    rms = np.array([np.sqrt(np.mean(c**2)) if len(c) else 0.0 for c in clips])
    target = float(np.median(rms[rms > 0])) if np.any(rms > 0) else 0.0
    for c, r in zip(clips, rms):
        if r > 0:
            c *= float(np.clip(target / r, 0.6, 1.8))
    return clips


def _join(segs: list[Segment], clips: list[np.ndarray], sr: int, start_s: float = 0.0) -> np.ndarray:
    """Crossfade pieces one after another; sets each segment's out_start (offset by start_s)."""
    xf = int(sr * config.CROSSFADE_MS / 1000)
    fade_in = np.linspace(0, 1, xf, dtype=np.float32)
    out = np.zeros(0, dtype=np.float32)
    for seg, c in zip(segs, clips):
        k = min(xf, len(c), len(out))
        seg.out_start = start_s + (len(out) - k) / sr
        if k:
            out[-k:] = out[-k:] * fade_in[::-1][-k:] + c[:k] * fade_in[:k]
        out = np.concatenate([out, c[k:]])
    return out


def _normalise_peak(x: np.ndarray, peak: float = 0.95) -> np.ndarray:
    m = float(np.max(np.abs(x))) if len(x) else 0.0
    return x / m * peak if m > peak else x


def _stitch(segs: list[Segment], audio: np.ndarray, sr: int) -> np.ndarray:
    clips = _prepare_clips(segs, audio, sr, config.PLAYBACK_SPEED)
    lead = np.zeros(int(sr * config.LEAD_IN_S), dtype=np.float32)
    voice = _join(segs, clips, sr, start_s=len(lead) / sr)
    return _normalise_peak(np.concatenate([lead, voice, lead]))


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
            src_t = segs[i].src_start + (t - starts[i]) / segs[i].stretch  # slowed pieces repeat frames
            if i == len(segs) - 1:
                src_t = min(src_t, segs[i].src_end + config.LEAD_IN_S)  # tail: footage just after
        idx[f] = int(round(src_t * fps))
    return frames[np.clip(idx, 0, len(frames) - 1)]


def _load_audio(norm: media.Normalised) -> tuple[np.ndarray, int]:
    audio, sr = sf.read(norm.wav48, dtype="float32")
    return (audio.mean(axis=1) if audio.ndim > 1 else audio), sr


def render(
    spans: list[Span], alignment: Alignment, norm: media.Normalised, out: Path, workdir: Path,
    frames: np.ndarray | None = None,
) -> Path:
    """`frames`: the recording's frames if already read (shared with the party render)."""
    audio, sr = _load_audio(norm)
    # Alignment was done on the 16 kHz file; times are in seconds so they carry over.
    level = speech_level(audio, sr)
    segs = [p for seg in segments_for(spans, alignment, audio, sr) for p in tighten(seg, audio, sr, level)]
    stitched = _stitch(segs, audio, sr)
    out_wav = workdir / "stitched.wav"
    sf.write(out_wav, stitched, sr)
    source = frames if frames is not None else media.read_frames(norm.video)
    media.write_video(_frames(segs, source, len(stitched) / sr), out_wav, out, workdir)
    return out


@dataclass
class PartyInfo:
    """Where things land in the party video (for effects and captions)."""

    bpm: float
    beats: int
    slots: list[party.WordSlot]


def render_party(
    spans: list[Span], target: list[Phone], target_words: list[str], alignment: Alignment,
    norm: media.Normalised, out: Path, workdir: Path, source_frames: np.ndarray | None = None,
) -> PartyInfo:
    """The party version: each word of the sentence starts on a beat of a generated dance track."""
    audio, sr = _load_audio(norm)
    tagged_spans = party.split_at_words(spans, target)
    level = speech_level(audio, sr)
    tagged: list[tuple[int, Segment]] = [
        (w, piece)
        for (w, _), seg in zip(tagged_spans, segments_for([sp for _, sp in tagged_spans], alignment, audio, sr))
        for piece in tighten(seg, audio, sr, level)
    ]
    segs = [seg for _, seg in tagged]
    clips = _prepare_clips(segs, audio, sr, config.PARTY_PLAYBACK_SPEED)

    # Join the pieces of each word, then put each word on its beat.
    words: list[tuple[int, list[int]]] = []  # (target word index, piece indices)
    for i, (w, _) in enumerate(tagged):
        if not words or words[-1][0] != w:
            words.append((w, []))
        words[-1][1].append(i)
    joined = [_join([segs[i] for i in idx], [clips[i] for i in idx], sr) for _, idx in words]
    slots, beats = party.lay_out([(w, len(a) / sr) for (w, _), a in zip(words, joined)], config.PARTY_BPM)

    music = party.track(config.PARTY_BPM, beats, sr)
    voice = np.zeros_like(music)
    for slot, (_, idx), a in zip(slots, words, joined):
        i = int(slot.start_s * sr)
        voice[i : i + len(a)] += a[: len(voice) - i]
        for k in idx:  # pieces were timed from the word's start: move them to its beat
            segs[k].out_start += slot.start_s
    mix = _normalise_peak(voice + party.duck(music, voice, sr, config.MUSIC_DUCKING) * config.MUSIC_VOLUME)

    out_wav = workdir / "party.wav"
    sf.write(out_wav, mix, sr)
    source = source_frames if source_frames is not None else media.read_frames(norm.video)
    frames = _frames(segs, source, len(mix) / sr)
    if config.PARTY_EFFECTS or config.PARTY_CAPTIONS:
        captions = [(target_words[sl.word_index], sl.start_s, sl.end_s) for sl in slots]
        frames = effects.apply(frames, config.FPS, config.PARTY_BPM, beats, captions,
                               captions=config.PARTY_CAPTIONS, motion=config.PARTY_EFFECTS)
    media.write_video(frames, out_wav, out, workdir)
    return PartyInfo(config.PARTY_BPM, beats, slots)
