"""How good are the disguises? Masks a fixed set of sentences and reports how many words User 2
has to say, timing, and (with the optional LLM on) how many phrase groups fell back to plain
word lists and why the LLM's phrases were rejected.

  make mask-eval                      # all sentences
  make mask-eval ARGS="--set LLM_GROUPS_PER_PHRASE=2"
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from _env import require_project_python  # noqa: E402

require_project_python()

from app import config  # noqa: E402
from app.core import masker  # noqa: E402

SENTENCES = [
    "I love pizza",
    "you are my best friend",
    "my cat is the boss of me",
    "please give me all of your money",
    "hello charlotte and amber",
    "I want my mummy I am scared of the dark",
    "hello sir this is not what I originally said",
    "I have a secret crush on my neighbour",
    "I think cheese is better than chocolate",
    "the dog ate my homework again",
    "I am the king of the world",
    "please call me captain from now on",
    "I promise to wash the dishes every day",
    "my favourite band is terrible",
    "I sing in the shower every morning",
    "can I borrow twenty pounds until friday",
    "I am secretly a robot from the future",
    "I forgot your birthday again and I am sorry",
    "nobody knows that I still sleep with a teddy bear",
    "I would like to formally apologise for my terrible jokes",
]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    p.add_argument("--seed", type=int, default=1)
    args = p.parse_args()
    for pair in args.set:
        k, _, v = pair.partition("=")
        setattr(config.settings, k, v)

    totals = {"groups": 0, "fallbacks": 0, "rejected": {}}
    fully_natural = 0
    times = []
    word_counts = []
    for text in SENTENCES:
        t = time.perf_counter()
        r = masker.mask(text, seed=args.seed)
        times.append(time.perf_counter() - t)
        s = r.stats
        totals["groups"] += s.get("groups", 0)
        totals["fallbacks"] += s.get("fallbacks", 0)
        for k, v in s.get("rejected", {}).items():
            totals["rejected"][k] = totals["rejected"].get(k, 0) + v
        n_words = len(r.masked_text.split())
        word_counts.append(n_words)
        natural = r.source == "llm" and not s.get("fallbacks")
        fully_natural += natural
        mark = f"{n_words} words" if r.source == "template" else "✓" if natural else f"{s.get('fallbacks')}/{s.get('groups')} lists"
        print(f"{times[-1]:5.1f}s  {mark:10} {len(r.spans):2} cuts  {text!r}\n        → {r.masked_text}")
    g, f = totals["groups"], totals["fallbacks"]
    print(f"\nWords to say: {sum(word_counts) / len(word_counts):.1f} on average, {max(word_counts)} at most")
    if g:
        print(f"Fully natural sentences (LLM): {fully_natural}/{len(SENTENCES)}")
        print(f"Phrase groups that fell back to a word list: {f}/{g} ({100 * f / max(g, 1):.0f}%)")
        print("Why LLM phrases were rejected:", ", ".join(f"{k}: {v}" for k, v in sorted(totals["rejected"].items(), key=lambda x: -x[1])))
    print(f"Time per sentence: {sum(times) / len(times):.1f}s average, {max(times):.1f}s worst")


if __name__ == "__main__":
    main()
