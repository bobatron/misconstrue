"""Split the masked sentence into the short prompts the reader sees one at a time."""
from __future__ import annotations

import math
import re

_PHRASE_END = re.compile(r"[.!?;,:]$")
_SENTENCE_END = re.compile(r"[.!?]$")


def split_prompts(masked_text: str, words_per_prompt: int) -> list[dict]:
    """[{"text": "Watson found peace", "tokens": [0, 1, 2]}, ...]

    `tokens` index into masked_text.split(), the tokens the retake message refers to.
    Phrases (split at punctuation) stay together where they fit; longer ones are split into
    even groups (5 words at 3 per prompt -> 3 + 2, not 3 + 1 + 1). A lone word is joined to a
    neighbour when there's room: short words read on their own change sound ("a" -> "ay").
    """
    tokens = masked_text.split()
    phrases: list[list[int]] = [[]]
    for i, tok in enumerate(tokens):
        phrases[-1].append(i)
        if _PHRASE_END.search(tok):
            phrases.append([])
    phrases = [p for p in phrases if p]

    # Join single-word phrases to a neighbour in the same sentence if the result still fits.
    merged: list[list[int]] = []
    for phrase in phrases:
        prev = merged[-1] if merged else None
        if (
            prev
            and not _SENTENCE_END.search(tokens[prev[-1]])
            and (len(phrase) == 1 or len(prev) == 1)
            and len(prev) + len(phrase) <= words_per_prompt
        ):
            merged[-1] = prev + phrase
        else:
            merged.append(phrase)

    prompts: list[list[int]] = []
    for phrase in merged:
        groups = math.ceil(len(phrase) / words_per_prompt)
        size, extra = divmod(len(phrase), groups)
        start = 0
        for g in range(groups):
            end = start + size + (1 if g < extra else 0)
            prompts.append(phrase[start:end])
            start = end

    def clean(tok: str) -> str:
        return tok.rstrip(".,;:!?")

    return [{"text": " ".join(clean(tokens[i]) for i in p), "tokens": p} for p in prompts]
