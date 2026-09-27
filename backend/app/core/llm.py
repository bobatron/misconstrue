"""Ask a local LLM (Ollama) to hide carrier words inside natural phrases."""
from __future__ import annotations

import json
import logging
import random

import httpx

from app import config

log = logging.getLogger(__name__)

PROMPT = """You write short, natural, casual English phrases for a word game.

Write {n} different phrases. Rules for EVERY phrase:
- Include at least one word from EACH numbered group below, spelled exactly as given (no plurals, no tense changes).
- You may add a few other everyday words to make it flow.
- At most {max_words} words, friendly and harmless.
- Do NOT use any of these words: {banned}.

Groups:
{groups}

Reply with JSON only: {{"phrases": ["...", "..."]}}"""


def phrases(groups: list[list[str]], banned: list[str], rng: random.Random) -> list[str]:
    """Candidate phrases that each (hopefully) use one word from every group. [] if no LLM."""
    if config.LLM_PROVIDER != "ollama":
        return []
    lines = []
    for i, words in enumerate(groups, 1):
        words = words[:]
        rng.shuffle(words)  # vary which word the model gravitates to
        lines.append(f"{i}. {', '.join(words)}")
    prompt = PROMPT.format(
        n=config.LLM_CANDIDATES,
        max_words=len(groups) * 3 + 2,
        banned=", ".join(banned) or "(none)",
        groups="\n".join(lines),
    )
    try:
        resp = httpx.post(
            f"{config.OLLAMA_URL}/api/chat",
            json={
                "model": config.OLLAMA_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "format": "json",
                "stream": False,
                "think": False,
                "options": {"temperature": 0.9, "seed": rng.randrange(1 << 30)},
            },
            timeout=120,
        )
        resp.raise_for_status()
        out = json.loads(resp.json()["message"]["content"]).get("phrases", [])
        return [s.strip() for s in out if isinstance(s, str) and s.strip()]
    except (httpx.HTTPError, json.JSONDecodeError, KeyError, AttributeError) as exc:
        log.warning("LLM unavailable, falling back to template: %s", exc)
        return []
