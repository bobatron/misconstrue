"""Text -> ARPAbet phonemes, plus a reverse index from phoneme n-grams to common words."""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

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
    return p.rstrip("012")


def tokenize(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower().replace("’", "'"))


@lru_cache(maxsize=1)
def _g2p():
    from g2p_en import G2p  # heavy import, only loaded for out-of-dictionary words

    return G2p()


@lru_cache(maxsize=50_000)
def word_phones(word: str) -> tuple[str, ...]:
    """Stress-stripped phones for a single word (first CMUdict pronunciation, else g2p)."""
    prons = pronouncing.phones_for_word(word)
    if prons:
        return tuple(strip_stress(p) for p in prons[0].split())
    return tuple(strip_stress(p) for p in _g2p()(word) if p.strip() and p[0].isalpha())


def sentence_phones(words: list[str]) -> list[Phone]:
    out: list[Phone] = []
    for wi, w in enumerate(words):
        ph = word_phones(w)
        out.extend(Phone(p, wi, i, len(ph)) for i, p in enumerate(ph))
    return out


def in_dictionary(word: str) -> bool:
    return bool(pronouncing.phones_for_word(word))


@dataclass(frozen=True)
class Carrier:
    word: str
    offset: int  # where the n-gram starts inside the word's phones
    zipf: float


@lru_cache(maxsize=1)
def carrier_index() -> dict[tuple[str, ...], list[Carrier]]:
    """Phone n-gram -> common words containing it, most frequent first."""
    pronouncing.init_cmu()
    index: dict[tuple[str, ...], list[Carrier]] = {}
    seen: set[str] = set()
    for word, pron in pronouncing.pronunciations:
        if word in seen or not word.isalpha() or word in BLOCKED_CARRIERS:
            continue
        if len(word) == 1 and word not in ("a", "i"):
            continue
        seen.add(word)
        z = zipf_frequency(word, "en")
        if z < config.MIN_CARRIER_ZIPF:
            continue
        ph = tuple(strip_stress(p) for p in pron.split())
        for n in range(1, min(MAX_NGRAM, len(ph)) + 1):
            for i in range(len(ph) - n + 1):
                index.setdefault(ph[i : i + n], []).append(Carrier(word, i, z))
    for key in index:
        index[key].sort(key=lambda c: -c.zipf)
        del index[key][40:]
    return index
