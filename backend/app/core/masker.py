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
    stats: dict = field(default_factory=dict)  # phrase groups tried / fell back, why LLM phrases were rejected


# Words so common that seeing them in the disguise gives nothing away ("the", "I"). Banning them
# whenever the target contains them rejected many good LLM phrases. Negations aren't here: "not"
# changes a sentence's meaning, so it stays hidden.
FUNCTION_WORDS = {
    "a", "an", "the", "i", "me", "my", "you", "your", "we", "our", "us", "he", "him", "his", "she", "her",
    "it", "its", "they", "them", "their", "is", "are", "was", "were", "be", "been", "am", "do", "does", "did",
    "have", "has", "had", "to", "of", "in", "on", "at", "for", "with", "by", "from", "as", "and", "or", "but",
    "so", "if", "that", "this", "these", "those", "there", "here", "then", "than", "up", "out", "all",
}


SUFFIXES = ("ingly", "edly", "ness", "ing", "ies", "ers", "est", "ful", "ish", "ed", "es", "er", "ly", "s", "y", "e")
SHARED_STEM = 5  # word-family stems sharing this many leading letters count as the same word


def stem(word: str) -> str:
    """Crude word-family stem: cheese/cheesy -> chees, pounds/pounding -> pound, dog/dogs -> dog."""
    for suffix in SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def same_family(a: str, b: str) -> bool:
    sa, sb = stem(a), stem(b)
    if sa == sb:
        return True
    shorter, longer = sorted((sa, sb), key=len)
    if len(shorter) >= 4 and longer.startswith(shorter):  # twent/twentieth
        return True
    common = 0
    for x, y in zip(sa, sb):
        if x != y:
            break
        common += 1
    return common >= SHARED_STEM  # secret/secrec


class Forbidden:
    """Decides which carrier words would give the trick away."""

    def __init__(self, target_words: list[str]):
        self.words = {w for w in target_words if w not in FUNCTION_WORDS}
        self.prons = {phonetics.word_phones(w) for w in self.words}
        self.long_words = [w for w in self.words if len(w) >= config.CONTAINED_WORD_MIN_LETTERS]

    def __call__(self, word: str) -> bool:
        if word in self.words or phonetics.word_phones(word) in self.prons:
            return True  # same word or a homophone
        if any(same_family(word, w) for w in self.words if len(w) >= 3):
            return True  # cheesy for cheese, dogs for dog
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


def _phrase_problem(phrase: str, groups: list[Chunk], forbidden: Forbidden) -> str | None:
    """Why an LLM phrase can't be used, or None if it's fine."""
    words = phonetics.tokenize(phrase)
    if not words:
        return "empty"
    if any(forbidden(w) for w in words):
        return "gives the game away"
    if not all(phonetics.in_dictionary(w) for w in words):
        return "word the aligner doesn't know"
    if not all(set(g.carriers) & set(words) for g in groups):
        return "missing a required word"
    return None


def llm_sentence(
    chunks: list[Chunk], forbidden: Forbidden, banned: list[str], rng: random.Random, stats: dict | None = None
) -> str | None:
    """Hide the chunks' carrier words in a few LLM-written phrases, in shuffled order.

    Small local models can't juggle many word groups at once, so each phrase only covers a few
    chunks. A batch the LLM can't manage is retried one group at a time (single-word phrases are
    much easier), and only then falls back to plain carrier words. Requests run in parallel.
    """
    order = chunks[:]
    rng.shuffle(order)  # don't let phrase order follow the target sentence
    stats = stats if stats is not None else {}
    stats.setdefault("groups", 0)
    stats.setdefault("fallbacks", 0)
    stats.setdefault("retried", 0)
    stats.setdefault("rejected", {})
    step = config.LLM_GROUPS_PER_PHRASE
    batches = [order[b : b + step] for b in range(0, len(order), step)]
    seeds = [rng.randrange(1 << 30) for _ in batches]

    first = _ask_batches(batches, seeds, forbidden, banned, stats)
    parts: list[str | None] = list(first)
    # Retry failed multi-group batches one group at a time.
    retry = [(i, g) for i, (batch, phrase) in enumerate(zip(batches, first)) if phrase is None and len(batch) > 1 for g in batch]
    if retry:
        stats["retried"] += len({i for i, _ in retry})
        singles = _ask_batches([[g] for _, g in retry], [rng.randrange(1 << 30) for _ in retry], forbidden, banned, stats)
        by_batch: dict[int, list[str]] = {}
        for (i, g), phrase in zip(retry, singles):
            by_batch.setdefault(i, []).append(phrase or g.carriers[0])
            if phrase is None:
                stats["fallbacks"] += 1
        for i, pieces in by_batch.items():
            parts[i] = ", ".join(pieces) if any("," in x or " " not in x for x in pieces) and len(pieces) > 1 else ". ".join(pieces)
    for i, (batch, phrase) in enumerate(zip(batches, parts)):
        stats["groups"] += 1
        if phrase is None:  # a single-group batch the LLM couldn't manage
            stats["fallbacks"] += 1
            parts[i] = batch[0].carriers[0]
    used_llm = any(p is not None for p in first) or stats["fallbacks"] < sum(len(b) for b in batches)
    if not used_llm:
        return None
    return ". ".join(p[0].upper() + p[1:] for p in parts if p) + "."


def _ask_batches(
    batches: list[list[Chunk]], seeds: list[int], forbidden: Forbidden, banned: list[str], stats: dict
) -> list[str | None]:
    """The shortest valid LLM phrase for each batch (None if none worked), asked in parallel."""
    from concurrent.futures import ThreadPoolExecutor

    from app.core import llm

    def ask(batch: list[Chunk], seed: int) -> tuple[str | None, dict]:
        rejected: dict = {}
        valid = []
        for phrase in llm.phrases([g.carriers for g in batch], banned, random.Random(seed)):
            problem = _phrase_problem(phrase, batch, forbidden)
            if problem:
                rejected[problem] = rejected.get(problem, 0) + 1
            else:
                valid.append(phrase)
        best = min(valid, key=lambda p: len(phonetics.tokenize(p))).rstrip(".!?,;") if valid else None
        return best, rejected

    with ThreadPoolExecutor(max_workers=max(1, min(4, len(batches)))) as pool:
        results = list(pool.map(ask, batches, seeds))
    for _, rejected in results:
        for k, v in rejected.items():
            stats["rejected"][k] = stats["rejected"].get(k, 0) + v
    return [phrase for phrase, _ in results]


def mask(target_text: str, use_llm: bool = True, seed: int | None = None) -> MaskResult:
    target_words = phonetics.tokenize(target_text)
    if not target_words:
        raise ValueError("Please enter a sentence with some words in it")
    target = phonetics.sentence_phones(target_words)
    forbidden = Forbidden(target_words)
    chunks = choose_chunks(target, forbidden)
    rng = random.Random(seed)

    stats: dict = {}
    if use_llm:
        text = llm_sentence(chunks, forbidden, target_words, rng, stats)
        scored = score_candidate(target, text, forbidden) if text else None
        if text and scored:
            return MaskResult(target_text, text, target, scored[0], scored[1], chunks, "llm", stats)

    text = template_sentence(chunks, rng)
    scored = score_candidate(target, text, forbidden)
    assert scored is not None, "template sentence must always cover the target"
    return MaskResult(target_text, text, target, scored[0], scored[1], chunks, "template", stats)
