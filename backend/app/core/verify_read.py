"""Completeness gate: did the speaker actually read the whole masked sentence?"""
from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

from app import config
from app.core import phonetics
from app.core.aligner import Alignment

_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def _number_words(n: int) -> list[str]:
    if n < 20:
        return [_ONES[n]]
    if n < 100:
        return [_TENS[n // 10]] + ([_ONES[n % 10]] if n % 10 else [])
    if n < 1000:
        rest = _number_words(n % 100) if n % 100 else []
        return [_ONES[n // 100], "hundred"] + rest
    if n < 10000:
        rest = _number_words(n % 1000) if n % 1000 else []
        return _number_words(n // 1000) + ["thousand"] + rest
    return [str(n)]


@dataclass
class Heard:
    word: str
    start: float
    end: float


@dataclass
class GateResult:
    ok: bool
    message: str = ""
    missing: list[int] = field(default_factory=list)  # indices into the masked words
    heard_text: str = ""


@lru_cache(maxsize=2)
def _whisper(model: str | None = None):
    from faster_whisper import WhisperModel

    return WhisperModel(model or config.WHISPER_MODEL, device="cpu", compute_type="int8")


def transcribe(wav_16k: Path, model: str | None = None) -> list[Heard]:
    """What was said, with word timings. `model` overrides WHISPER_MODEL (the clarity score uses a
    fixed one so scores stay comparable when the retake check's model changes)."""
    # No initial prompt on purpose: priming with the masked text would let Whisper "hear" words
    # that were never said.
    segments, _ = _whisper(model).transcribe(
        str(wav_16k), language="en", word_timestamps=True, vad_filter=True, condition_on_previous_text=False
    )
    heard: list[Heard] = []
    for seg in segments:
        for w in seg.words or []:
            token = w.word.strip().lower().replace(",", "")
            if token.isdigit():
                words = _number_words(int(token))
            else:
                words = phonetics.tokenize(token)
            heard.extend(Heard(x, w.start, w.end) for x in words)
    return heard


def _key(word: str) -> tuple[str, ...]:
    """Compare by sound so homophones (read/red, one/won) count as a match."""
    try:
        return phonetics.word_phones(word)  # g2p guesses sounds for mis-heard non-words too
    except LookupError:
        return (word,)  # g2p data missing: fall back to spelling


def _match_words(masked: list[str], heard: list[Heard]) -> dict[int, tuple[float, float]]:
    """Masked word index -> (start, end) of where it was heard.

    Exact sound matches first; then, in stretches where Whisper heard something different
    ("nottingham knots" -> "nodding amnots"), accept words whose phones mostly show up anyway.
    """
    mk = [_key(w) for w in masked]
    hk = [_key(h.word) for h in heard]
    sm = SequenceMatcher(None, mk, hk, autojunk=False)
    match: dict[int, tuple[float, float]] = {}
    for tag, a0, a1, b0, b1 in sm.get_opcodes():
        if tag == "equal":
            for k in range(a1 - a0):
                match[a0 + k] = (heard[b0 + k].start, heard[b0 + k].end)
        elif tag in ("replace", "delete"):
            lo, hi = max(0, b0 - 1), min(len(heard), b1 + 1)  # let neighbours absorb mis-split words
            if lo >= hi:
                continue
            heard_phones = [p for key in hk[lo:hi] for p in key]
            heard_consonants = [_consonants(key) for key in hk[lo:hi]]
            for i in range(a0, a1):
                found = _subsequence_hits(mk[i], heard_phones)
                same_consonants = len(_consonants(mk[i])) >= 2 and _consonants(mk[i]) in heard_consonants
                if (found / max(1, len(mk[i])) >= config.FUZZY_MATCH_RATIO or (len(mk[i]) >= 3 and len(mk[i]) - found <= 1)
                        or same_consonants):
                    match[i] = (heard[lo].start, heard[hi - 1].end)
    return match


def _consonants(phones: tuple[str, ...]) -> tuple[str, ...]:
    """A word's consonant sounds. Whisper most often mishears vowels on a word said on its own
    ("belly" -> "ballet", both B-L); a wrong or skipped word almost always differs in consonants."""
    return tuple(p for p in phones if not phonetics.is_vowel(p))


def _subsequence_hits(word: tuple[str, ...], heard: list[str]) -> int:
    """Length of the longest common subsequence of the two phone lists."""
    prev = [0] * (len(heard) + 1)
    for a in word:
        cur = [0]
        for j, b in enumerate(heard):
            cur.append(prev[j] + 1 if a == b else max(prev[j + 1], cur[j]))
        prev = cur
    return prev[-1]


def _message(words: list[str]) -> str:
    quoted = ", ".join(f"“{w}”" for w in words[:4])
    return f"We didn't quite catch {quoted}. Please go through the words again, saying each one clearly."


def check(
    masked_text: str,
    heard: list[Heard],
    alignment: Alignment | None,
    critical: set[int],
) -> GateResult:
    """`critical` = masked word indices the splice plan actually cuts from."""
    masked = phonetics.tokenize(masked_text)
    heard_text = " ".join(h.word for h in heard)
    if not heard:
        return GateResult(False, "We couldn't hear any speech. Check your microphone and say the words out loud.",
                          list(range(len(masked))), heard_text)

    match = _match_words(masked, heard)
    missing = [i for i in range(len(masked)) if i not in match]
    wer = 1 - len(match) / len(masked)

    critical_missing = [i for i in missing if i in critical]
    if critical_missing or wer > config.MAX_WER:
        flagged = critical_missing or missing
        return GateResult(False, _message([masked[i] for i in flagged]), missing, heard_text)

    if alignment is not None:
        unclear = []
        for wi in sorted(critical):
            if wi >= len(alignment.words):
                unclear.append(wi)
                continue
            durs = [e - s for p, (s, e) in zip(alignment.phones, alignment.times) if p.word_index == wi]
            if not durs or 1000 * sum(durs) / len(durs) < config.MIN_CRITICAL_PHONE_MS:
                unclear.append(wi)  # squashed phones: the aligner was forcing a word that isn't there
                continue
            hs, he = match[wi]
            _, ws, we = alignment.words[wi]
            # The aligner is precise; Whisper's word timings are loose and often shifted. What
            # matters is whether they touch: across all benchmark takes, every needed word in a good
            # take touches or overlaps where Whisper heard it (gap 0.00 s), while bad takes had the
            # aligner slip out of step (gaps of 0.11-0.60 s). Two rules that didn't work: comparing
            # midpoints rejected good takes with prompter pauses (Whisper stretches a word back into
            # the pause), and requiring overlap rejected good takes where the ranges only touch.
            gap = max(0.0, max(ws, hs) - min(we, he))
            if gap > config.MAX_WORD_TIME_GAP_S:
                unclear.append(wi)
        if unclear:
            return GateResult(False, _message([masked[i] for i in unclear]), unclear, heard_text)

    return GateResult(True, heard_text=heard_text, missing=missing)
