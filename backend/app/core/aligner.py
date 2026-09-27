"""Phone-level timestamps for a recording of a known sentence (Montreal Forced Aligner)."""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app import config
from app.core.phonetics import Phone, strip_stress, tokenize

log = logging.getLogger(__name__)

SILENCE = {"", "sil", "sp", "spn", "<eps>"}


@dataclass
class Alignment:
    words: list[tuple[str, float, float]]  # (word, start, end), speech only, in reading order
    phones: list[Phone]  # word_index refers to `words`
    times: list[tuple[float, float]]  # parallel to phones

    def to_json(self) -> dict:
        return {
            "words": self.words,
            "phones": [[p.symbol, p.word_index, p.pos, p.word_len] for p in self.phones],
            "times": self.times,
        }

    @classmethod
    def from_json(cls, data: dict) -> Alignment:
        return cls(
            [tuple(w) for w in data["words"]],
            [Phone(*p) for p in data["phones"]],
            [tuple(t) for t in data["times"]],
        )


class AlignmentError(RuntimeError):
    pass


def _mfa() -> str:
    return shutil.which("mfa") or str(Path(sys.prefix) / "bin" / "mfa")


def _entries(tiers: dict, name: str) -> list[tuple[float, float, str]]:
    tier = tiers[name]
    entries = tier["entries"] if isinstance(tier, dict) else tier
    return [(float(s), float(e), str(label)) for s, e, label in entries]


@lru_cache(maxsize=2)
def _dictionary_lines(path: Path) -> dict[str, list[str]]:
    """word -> its lines in the pronunciation dictionary, verbatim (all variants and probabilities)."""
    lines: dict[str, list[str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        word = line.split("\t", 1)[0].lower()
        if word:
            lines.setdefault(word, []).append(line)
    return lines


def dictionary_for(words: list[str], folder: Path) -> str:
    """A pronunciation dictionary containing only `words`.

    MFA spends most of its time loading its full 200,000-word dictionary; a sentence needs
    about 25 words. Falls back to the full dictionary if any word isn't in it.
    """
    path = config.PRONUNCIATION_DICT
    if path is None or not path.exists():
        return config.MFA_DICTIONARY
    lines = _dictionary_lines(path)
    missing = sorted({w for w in words if w not in lines})
    if missing:
        log.info("Not in the dictionary, aligning with the full one: %s", ", ".join(missing))
        return config.MFA_DICTIONARY
    mini = folder / "sentence.dict"
    mini.write_text("\n".join(line for w in dict.fromkeys(words) for line in lines[w]) + "\n", encoding="utf-8")
    return str(mini)


def align(wav_16k: Path, text: str) -> Alignment:
    words = tokenize(text)
    with tempfile.TemporaryDirectory(prefix="mfa_") as tmp:
        corpus, out = Path(tmp) / "corpus", Path(tmp) / "out"
        corpus.mkdir()
        shutil.copy(wav_16k, corpus / "rec.wav")
        (corpus / "rec.lab").write_text(" ".join(words))
        dictionary = dictionary_for(words, Path(tmp))
        cmd = [
            _mfa(), "align", str(corpus), dictionary, config.MFA_ACOUSTIC_MODEL, str(out),
            "--output_format", "json", "--clean", "--single_speaker", "--quiet",
            "--temporary_directory", str(Path(tmp) / "mfa_tmp"),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        result = out / "rec.json"
        if proc.returncode != 0 or not result.exists():
            raise AlignmentError(f"MFA failed: {proc.stderr[-2000:] or proc.stdout[-2000:]}")
        data = json.loads(result.read_text())

    tiers = data["tiers"]
    word_entries = [(s, e, w) for s, e, w in _entries(tiers, "words") if w.lower() not in SILENCE]
    phone_entries = [(s, e, p) for s, e, p in _entries(tiers, "phones") if p.lower() not in SILENCE]

    grouped: list[list[tuple[float, float, str]]] = [[] for _ in word_entries]
    for s, e, p in phone_entries:
        mid = (s + e) / 2
        for wi, (ws, we, _) in enumerate(word_entries):
            if ws <= mid <= we:
                grouped[wi].append((s, e, p))
                break

    phones: list[Phone] = []
    times: list[tuple[float, float]] = []
    for wi, group in enumerate(grouped):
        for pos, (s, e, p) in enumerate(group):
            phones.append(Phone(strip_stress(p), wi, pos, len(group)))
            times.append((s, e))
    return Alignment([(w.lower(), s, e) for s, e, w in word_entries], phones, times)
