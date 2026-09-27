"""Text -> ARPAbet phonemes, plus a reverse index from phoneme n-grams to common words.

Pronunciations come from the aligner's own dictionary (MFA english_us_arpa), so the sounds we
plan to cut are the sounds the aligner will find. CMUdict is only a fallback.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pronouncing
from wordfreq import zipf_frequency

from app import config

VOWELS = {
    "AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER", "EY", "IH", "IY", "OW", "OY", "UH", "UW",
}
STOPS = {"P", "B", "T", "D", "K", "G"}
MAX_NGRAM = 8

_WORD_RE = re.compile(r"[a-z']+")

# Words we never ask anyone to read out: slurs, sensitive topics, letters, abbreviations.
BLOCKED_CARRIERS = {
    "nazi", "nazis", "hitler", "rape", "raped", "rapist", "sex", "sexy", "sexual", "porn", "kill",
    "killed", "killing", "murder", "suicide", "terrorist", "terrorism", "bomb", "cancer", "abortion",
    "slave", "slavery", "drug", "drugs", "cocaine", "heroin", "penis", "vagina", "nude", "naked",
    "schizophrenia", "hell", "damn", "god", "jesus", "allah", "gay", "lesbian", "negro", "jew",
    "mrs", "mr", "dr", "st", "vs", "etc", "ok", "url", "www", "com", "html", "pdf", "usa", "uk",
}


@dataclass(frozen=True)
class Phone:
    symbol: str  # ARPAbet, stress stripped
    word_index: int  # which word of the sentence it belongs to
    pos: int  # position within that word
    word_len: int  # number of phones in that word

    @property
    def word_start(self) -> bool:
        return self.pos == 0

    @property
    def word_end(self) -> bool:
        return self.pos == self.word_len - 1


def strip_stress(p: str) -> str:
    """ARPAbet -> our phone symbol. Unstressed vowels keep a "0" (AH0 is a schwa, AH1 is not);
    primary and secondary stress are merged."""
    base = p.rstrip("012")
    return base + "0" if base in VOWELS and p.endswith("0") else base


def is_vowel(symbol: str) -> bool:
    return symbol.rstrip("0") in VOWELS


def tokenize(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower().replace("’", "'"))


@lru_cache(maxsize=1)
def _g2p():
    from g2p_en import G2p  # heavy import, only loaded for out-of-dictionary words

    return G2p()


@lru_cache(maxsize=1)
def pronunciations() -> dict[str, list[tuple[float, tuple[str, ...]]]]:
    """word -> [(probability, phones), ...], likeliest first."""
    prons: dict[str, list[tuple[float, tuple[str, ...]]]] = {}
    path = config.PRONUNCIATION_DICT
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if len(parts) < 6:
                continue
            prons.setdefault(parts[0].lower(), []).append(
                (float(parts[1]), tuple(strip_stress(p) for p in parts[5].split()))
            )
    else:  # aligner not installed: plan with CMUdict
        pronouncing.init_cmu()
        for word, pron in pronouncing.pronunciations:
            prons.setdefault(word, []).append((1.0, tuple(strip_stress(p) for p in pron.split())))
    for variants in prons.values():
        variants.sort(key=lambda v: -v[0])
    return prons


def likely_variants(word: str) -> list[tuple[str, ...]]:
    variants = pronunciations().get(word, [])
    return [ph for prob, ph in variants if prob >= config.MIN_VARIANT_PROB] or [ph for _, ph in variants[:1]]


@lru_cache(maxsize=50_000)
def word_phones(word: str) -> tuple[str, ...]:
    """Stress-stripped phones for a single word (likeliest dictionary pronunciation, else g2p)."""
    variants = pronunciations().get(word)
    if variants:
        return variants[0][1]
    return tuple(strip_stress(p) for p in _g2p()(word) if p.strip() and p[0].isalpha())


def sentence_phones(words: list[str]) -> list[Phone]:
    out: list[Phone] = []
    for wi, w in enumerate(words):
        ph = word_phones(w)
        out.extend(Phone(p, wi, i, len(ph)) for i, p in enumerate(ph))
    return out


def in_dictionary(word: str) -> bool:
    return word in pronunciations()


@dataclass(frozen=True)
class Carrier:
    word: str
    offset: int  # where the n-gram starts inside the word's phones
    zipf: float


WORD_LIST = Path("/usr/share/dict/words")  # on Debian/Ubuntu: apt install wamerican


@lru_cache(maxsize=1)
def lowercase_words() -> set[str] | None:
    """Lower-case entries of the system word list: real words, not names (Nottingham, Watson)."""
    if not WORD_LIST.exists():
        return None
    return {w for w in WORD_LIST.read_text(encoding="utf-8", errors="ignore").split() if w.islower()}


@lru_cache(maxsize=1)
def carrier_index() -> dict[tuple[str, ...], list[Carrier]]:
    """Phone n-gram -> common words containing it, most frequent first.

    A word only carries an n-gram if every likely pronunciation contains it, so it doesn't
    matter which variant the speaker happens to use.
    """
    index: dict[tuple[str, ...], list[Carrier]] = {}
    known = lowercase_words()
    for word in pronunciations():
        if known is not None and word not in known:
            continue
        if not word.isalpha() or word in BLOCKED_CARRIERS or (len(word) == 1 and word not in ("a", "i")):
            continue
        z = zipf_frequency(word, "en")
        if z < config.MIN_CARRIER_ZIPF:
            continue
        ph, *others = likely_variants(word)
        for n in range(1, min(MAX_NGRAM, len(ph)) + 1):
            for i in range(len(ph) - n + 1):
                gram = ph[i : i + n]
                if all(_contains(o, gram) for o in others):
                    index.setdefault(gram, []).append(Carrier(word, i, z))
    for key in index:
        index[key] = list({c.word: c for c in index[key]}.values())
        index[key].sort(key=lambda c: -c.zipf)
        del index[key][40:]
    return index


def _contains(seq: tuple[str, ...], gram: tuple[str, ...]) -> bool:
    n = len(gram)
    return any(seq[i : i + n] == gram for i in range(len(seq) - n + 1))
