"""Phone-level timestamps for a recording of a known sentence (Montreal Forced Aligner)."""
from __future__ import annotations

import ctypes
import json
import logging
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

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
        return str(path)
    mini = folder / "sentence.dict"
    mini.write_text("\n".join(line for w in dict.fromkeys(words) for line in lines[w]) + "\n", encoding="utf-8")
    return str(mini)


WIDE_BEAM = {"beam": 100, "retry_beam": 400}
DITHER_SEED = 1  # MFA adds random "dither" noise to audio features; a fixed seed makes results repeatable


class _InProcessAligner:
    """MFA's single-file aligner called directly, so its libraries (~2.5 s to import) and the
    acoustic model stay loaded between recordings: ~0.4 s per alignment instead of ~4 s."""

    def __init__(self) -> None:
        from montreal_forced_aligner import config as mfa_config
        from montreal_forced_aligner.models import AcousticModel

        mfa_config.TEMPORARY_DIRECTORY = config.DATA_DIR / "mfa"  # where the model is unpacked
        path = config.MFA_ROOT_DIR / "pretrained_models" / "acoustic" / f"{config.MFA_ACOUSTIC_MODEL}.zip"
        self.acoustic_model = AcousticModel(path)
        self._libc = ctypes.CDLL(None)

    def align(self, wav: Path, transcript: Path, dictionary: str, result: Path, tmp: Path, config_path: Path | None) -> None:
        from montreal_forced_aligner import config as mfa_config
        from montreal_forced_aligner.command_line.align_one import align_one_function
        from montreal_forced_aligner.models import DictionaryModel

        mfa_config.TEMPORARY_DIRECTORY = tmp
        mfa_config.CLEAN = True  # never reuse a lexicon compiled for another sentence
        self._libc.srand(DITHER_SEED)
        kwargs = {
            "sound_file_path": wav, "text_file_path": transcript, "output_path": result,
            "output_format": "json", "no_tokenization": False, "config_path": config_path,
        }
        # The command-line wrapper only reads these two attributes from its click context.
        context = SimpleNamespace(params={}, args=[])
        align_one_function(context, kwargs, self.acoustic_model, DictionaryModel(Path(dictionary)), None)


@lru_cache(maxsize=1)
def _in_process() -> _InProcessAligner:
    return _InProcessAligner()


def warm_up() -> None:
    """Load the aligner's libraries and model now rather than on the first recording."""
    if config.ALIGNER_MODE == "in_process":
        _in_process()
    if config.PRONUNCIATION_DICT.exists():
        _dictionary_lines(config.PRONUNCIATION_DICT)


def _run_mfa(wav: Path, transcript: Path, dictionary: str, result: Path, tmp: Path) -> None:
    """Align with MFA's single-file aligner (`align_one`), always with a wide search.

    It skips MFA's corpus machinery (database, nine multi-process stages) built for thousands of
    files. In-process first; the `mfa` command is the fallback if that breaks.
    """
    # Always the wide search. MFA's default (beam 10) doesn't fail on recordings that are mostly
    # pauses (one word at a time): it quietly returns a wrong alignment, squashing every word into
    # the first few seconds. The wide search gets them right, and is no worse elsewhere.
    searches = [_wide_beam_config(tmp)]
    errors: list[str] = []
    if config.ALIGNER_MODE == "in_process":
        try:
            in_process = _in_process()
        except Exception as exc:  # e.g. an MFA version with different internals
            log.warning("Can't align in-process (%s); using the mfa command", exc)
            in_process = None
        if in_process:
            for attempt, search in enumerate(searches):
                try:
                    in_process.align(wav, transcript, dictionary, result, tmp / f"mfa_tmp{attempt}", search)
                    return
                except Exception as exc:
                    errors.append(repr(exc))
                    log.info("In-process alignment %s failed: %s", "retry" if attempt else "attempt", exc)
            log.warning("In-process alignment failed; trying the mfa command")

    for attempt, search in enumerate(searches):
        cmd = [
            _mfa(), "align_one", str(wav), str(transcript), dictionary, config.MFA_ACOUSTIC_MODEL, str(result),
            "--output_format", "json", "--quiet", "--temporary_directory", str(tmp / f"mfa_cmd{attempt}"),
        ]
        if search:
            cmd += ["--config_path", str(search)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0 and result.exists():
            return
        errors.append(proc.stderr[-1500:] or proc.stdout[-1500:])
    raise AlignmentError("MFA failed: " + "\n---\n".join(errors))


def _wide_beam_config(folder: Path) -> Path:
    path = folder / "wide_beam.yaml"
    path.write_text("".join(f"{k}: {v}\n" for k, v in WIDE_BEAM.items()))
    return path


def align(wav_16k: Path, text: str) -> Alignment:
    words = tokenize(text)
    with tempfile.TemporaryDirectory(prefix="mfa_") as tmp_name:
        tmp = Path(tmp_name)
        transcript = tmp / "rec.lab"
        transcript.write_text(" ".join(words))
        dictionary = dictionary_for(words, tmp)
        result = tmp / "rec.json"
        _run_mfa(wav_16k, transcript, dictionary, result, tmp)
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
