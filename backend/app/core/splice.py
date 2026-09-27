"""Find the cheapest way to build a target phone sequence out of spans of a source sequence.

Used twice:
  * at masking time, to score candidate masked sentences (dictionary phones);
  * at edit time, against the phones actually aligned in the recording.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.phonetics import STOPS, Phone, is_vowel


@dataclass(frozen=True)
class Span:
    t_start: int  # target phone index (inclusive)
    t_end: int  # target phone index (exclusive)
    s_start: int  # source phone index where the matching run starts

    @property
    def length(self) -> int:
        return self.t_end - self.t_start

    @property
    def s_end(self) -> int:
        return self.s_start + self.length


def cut_penalty(target: list[Phone], i: int) -> float:
    """How audible a cut just before target[i] is likely to be."""
    if i == 0 or target[i].word_start:
        return 0.0
    cur, prev = target[i].symbol, target[i - 1].symbol
    if cur in STOPS:
        return 0.05  # stop closure is near-silent: a clean place to cut
    if is_vowel(cur) and is_vowel(prev):
        return 0.6
    if is_vowel(cur) or is_vowel(prev):
        return 0.3
    return 0.15


MIN_PHONE_S = 0.045  # aligned phones shorter than this on average are probably misaligned


def span_cost(
    target: list[Phone], source: list[Phone], i: int, j: int, k: int,
    times: list[tuple[float, float]] | None = None,
) -> float:
    cost = 1.0 + cut_penalty(target, i)
    if times is not None:
        dur = (times[k + j - i - 1][1] - times[k][0]) / (j - i)
        if dur < MIN_PHONE_S:
            cost += 0.8 * (MIN_PHONE_S - dur) / MIN_PHONE_S + 0.3
    if j - i == 1:
        cost += 0.5  # single phones sound choppy
    # Sounds are shaped by their neighbours, so prefer runs whose surroundings match the target:
    # both at a word edge, or the same phone on the other side of the cut.
    last = k + j - i - 1
    if target[i].word_start and source[k].word_start:
        cost -= 0.2
    elif i > 0 and k > 0 and target[i - 1].symbol == source[k - 1].symbol:
        cost -= 0.15
    if target[j - 1].word_end and source[last].word_end:
        cost -= 0.2
    elif j < len(target) and last + 1 < len(source) and target[j].symbol == source[last + 1].symbol:
        cost -= 0.15
    return max(cost, 0.3)


def plan_splice(
    target: list[Phone], source: list[Phone], times: list[tuple[float, float]] | None = None
) -> tuple[list[Span], float] | None:
    """Minimum-cost segmentation of target into runs found in source. None if impossible.

    Pass the aligned `times` of the source phones to steer away from squashed alignments.
    """
    n, m = len(target), len(source)
    if n == 0:
        return [], 0.0
    t_sym = [p.symbol for p in target]
    s_sym = [p.symbol for p in source]

    # positions[length][tuple] -> source start indices
    positions: dict[tuple[str, ...], list[int]] = {}
    for k in range(m):
        for length in range(1, min(n, m - k) + 1):
            positions.setdefault(tuple(s_sym[k : k + length]), []).append(k)

    inf = float("inf")
    best = [inf] * (n + 1)
    back: list[Span | None] = [None] * (n + 1)
    best[0] = 0.0
    for i in range(n):
        if best[i] == inf:
            continue
        for j in range(i + 1, n + 1):
            ks = positions.get(tuple(t_sym[i:j]))
            if not ks:
                break  # longer spans starting at i can't match either
            k = min(ks, key=lambda k: span_cost(target, source, i, j, k, times))
            c = best[i] + span_cost(target, source, i, j, k, times)
            if c < best[j]:
                best[j] = c
                back[j] = Span(i, j, k)
    if best[n] == inf:
        return None
    spans: list[Span] = []
    j = n
    while j > 0:
        span = back[j]
        assert span is not None
        spans.append(span)
        j = span.t_start
    return spans[::-1], best[n]
