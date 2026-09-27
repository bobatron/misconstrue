"""Build a masked sentence: different words that contain all the sounds of the target."""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from app import config
from app.core import phonetics
from app.core.phonetics import Carrier, Phone
from app.core.splice import Span, cut_penalty, plan_splice



@dataclass
class Chunk:
    """A run of target phones and the words that could supply it."""

    t_start: int
    t_end: int
    phones: tuple[str, ...]
    carriers: list[str]  # best first


@dataclass
class MaskResult:
    target_text: str
    masked_text: str
    target_phones: list[Phone]
    spans: list[Span]
    cost: float
    chunks: list[Chunk] = field(default_factory=list)
    source: str = "template"  # "llm" or "template"


class Forbidden:
    """Decides which carrier words would give the trick away."""

    def __init__(self, target_words: list[str]):
        self.words = set(target_words)
        self.prons = {phonetics.word_phones(w) for w in target_words}
        self.long_words = [w for w in self.words if len(w) >= config.CONTAINED_WORD_MIN_LETTERS]

    def __call__(self, word: str) -> bool:
        if word in self.words or phonetics.word_phones(word) in self.prons:
            return True  # same word or a homophone
        for w in self.long_words:
            if w in word or (len(word) >= config.CONTAINED_WORD_MIN_LETTERS and word in w):
                return True
            m = SequenceMatcher(None, word, w).find_longest_match(0, len(word), 0, len(w))
            if m.size >= config.SHARED_LETTERS_LIMIT:
                return True
        return False


def _chunk_cost(target: list[Phone], i: int, j: int, c: Carrier) -> float:
    cost = 1.0 + cut_penalty(target, i) + (0.5 if j - i == 1 else 0.0)
    cost += max(0.0, 6.0 - c.zipf) * 0.1  # prefer everyday words
    carrier_len = len(phonetics.word_phones(c.word))
    if target[i].word_start and c.offset == 0:
        cost -= 0.2
    if target[j - 1].word_end and c.offset + (j - i) == carrier_len:
        cost -= 0.2
    return max(cost, 0.3)


def choose_chunks(target: list[Phone], forbidden: Forbidden, alternatives: int = 6) -> list[Chunk]:
    """Segment the target into as few carrier-word chunks as possible."""
    index = phonetics.carrier_index()
    sym = [p.symbol for p in target]
    n = len(sym)
    inf = float("inf")
    best = [inf] * (n + 1)
    back: list[tuple[int, list[Carrier]] | None] = [None] * (n + 1)
    best[0] = 0.0
    for i in range(n):
        if best[i] == inf:
            continue
        for j in range(i + 1, min(n, i + phonetics.MAX_NGRAM) + 1):
            options = [c for c in index.get(tuple(sym[i:j]), []) if not forbidden(c.word)]
            if not options:
                continue
            options.sort(key=lambda c: _chunk_cost(target, i, j, c))
            c = best[i] + _chunk_cost(target, i, j, options[0])
            if c < best[j]:
                best[j] = c
                back[j] = (i, options)
    if best[n] == inf:
        raise ValueError("Could not find carrier words for every sound in the sentence")
    chunks: list[Chunk] = []
    j = n
    while j > 0:
        entry = back[j]
        assert entry is not None
        i, options = entry
        words = list(dict.fromkeys(c.word for c in options))[:alternatives]
        chunks.append(Chunk(i, j, tuple(sym[i:j]), words))
        j = i
    return chunks[::-1]


def score_candidate(target: list[Phone], text: str, forbidden: Forbidden) -> tuple[list[Span], float] | None:
    """Splice cost of reading `text`, or None if it can't cover the target / leaks target words."""
    words = phonetics.tokenize(text)
    if not words or any(forbidden(w) for w in words):
        return None
    if not all(phonetics.in_dictionary(w) for w in words):
        return None  # the aligner needs dictionary words
    return plan_splice(target, phonetics.sentence_phones(words))


def template_sentence(chunks: list[Chunk], rng: random.Random) -> str:
    words = list(dict.fromkeys(ch.carriers[0] for ch in chunks))
    rng.shuffle(words)
    return (", ".join(words) + ".").capitalize()


def _phrase_ok(phrase: str, groups: list[Chunk], forbidden: Forbidden) -> bool:
    words = phonetics.tokenize(phrase)
    if not words or any(forbidden(w) or not phonetics.in_dictionary(w) for w in words):
        return False
    return all(set(g.carriers) & set(words) for g in groups)


def llm_sentence(chunks: list[Chunk], forbidden: Forbidden, banned: list[str], rng: random.Random) -> str | None:
    """Hide the chunks' carrier words in a few LLM-written phrases, in shuffled order.

    Small local models can't juggle many word groups at once, so each phrase only covers a
    few chunks. Batches the LLM can't manage fall back to their plain carrier words.
    """
    from app.core import llm

    order = chunks[:]
    rng.shuffle(order)  # don't let phrase order follow the target sentence
    parts = []
    used_llm = False
    step = config.LLM_GROUPS_PER_PHRASE
    for b in range(0, len(order), step):
        batch = order[b : b + step]
        valid = [p for p in llm.phrases([g.carriers for g in batch], banned, rng) if _phrase_ok(p, batch, forbidden)]
        if valid:
            used_llm = True
            parts.append(min(valid, key=lambda p: len(phonetics.tokenize(p))).rstrip(".!?,;"))
        else:
            parts.append(", ".join(g.carriers[0] for g in batch))
    if not used_llm:
        return None
    return ". ".join(p[0].upper() + p[1:] for p in parts) + "."


def mask(target_text: str, use_llm: bool = True, seed: int | None = None) -> MaskResult:
    target_words = phonetics.tokenize(target_text)
    if not target_words:
        raise ValueError("Please enter a sentence with some words in it")
    target = phonetics.sentence_phones(target_words)
    forbidden = Forbidden(target_words)
    chunks = choose_chunks(target, forbidden)
    rng = random.Random(seed)

    if use_llm:
        text = llm_sentence(chunks, forbidden, target_words, rng)
        scored = score_candidate(target, text, forbidden) if text else None
        if text and scored:
            return MaskResult(target_text, text, target, scored[0], scored[1], chunks, "llm")

    text = template_sentence(chunks, rng)
    scored = score_candidate(target, text, forbidden)
    assert scored is not None, "template sentence must always cover the target"
    return MaskResult(target_text, text, target, scored[0], scored[1], chunks, "template")
