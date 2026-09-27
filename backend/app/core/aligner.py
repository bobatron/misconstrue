"""Phone-level timestamps for a recording of a known sentence (Montreal Forced Aligner)."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app import config
from app.core.phonetics import Phone, strip_stress, tokenize

SILENCE = {"", "sil", "sp", "spn", "<eps>"}


@dataclass
class Alignment:
    words: list[tuple[str, float, float]]  # (word, start, end), speech only, in reading order
    phones: list[Phone]  # word_index refers to `words`
    times: list[tuple[float, float]]  # parallel to phones


class AlignmentError(RuntimeError):
    pass


def _mfa() -> str:
    return shutil.which("mfa") or str(Path(sys.prefix) / "bin" / "mfa")


def _entries(tiers: dict, name: str) -> list[tuple[float, float, str]]:
    tier = tiers[name]
    entries = tier["entries"] if isinstance(tier, dict) else tier
    return [(float(s), float(e), str(label)) for s, e, label in entries]


def align(wav_16k: Path, text: str) -> Alignment:
    words = tokenize(text)
    with tempfile.TemporaryDirectory(prefix="mfa_") as tmp:
        corpus, out = Path(tmp) / "corpus", Path(tmp) / "out"
        corpus.mkdir()
        shutil.copy(wav_16k, corpus / "rec.wav")
        (corpus / "rec.lab").write_text(" ".join(words))
        cmd = [
            _mfa(), "align", str(corpus), config.MFA_DICTIONARY, config.MFA_ACOUSTIC_MODEL, str(out),
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
