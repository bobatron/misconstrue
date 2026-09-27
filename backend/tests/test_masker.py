import random

import pytest

from app.core import masker, phonetics


def test_forbidden_blocks_target_words_homophones_and_stems():
    f = masker.Forbidden(["originally", "said", "read"])
    assert f("said")
    assert f("red")  # sounds like "read"
    assert f("original")  # shares a long stem
    assert f("aboriginal")
    assert not f("police")


def test_template_mask_covers_target_without_leaking_words():
    target = "hello sir this is not what I originally said"
    r = masker.mask(target, use_llm=False, seed=1)
    words = set(phonetics.tokenize(r.masked_text))
    assert not words & {"hello", "sir", "originally", "said"}
    assert r.spans and r.spans[-1].t_end == len(r.target_phones)


def test_llm_sentence_falls_back_when_llm_is_unavailable(monkeypatch):
    from app import config

    monkeypatch.setattr(config.settings, "LLM_PROVIDER", "none")
    r = masker.mask("I love pizza", use_llm=True, seed=1)
    assert r.source == "template"


def test_common_function_words_are_not_secret():
    f = masker.Forbidden(["i", "love", "the", "pizza", "not"])
    assert not f("the") and not f("i")  # everywhere anyway
    assert f("love") and f("not")  # content words and negations stay hidden


@pytest.mark.parametrize("target, leak", [
    ("cheese", "cheesy"), ("pounds", "pounding"), ("twenty", "twentieth"), ("dog", "dogs"),
    ("love", "loving"), ("secretly", "secrecy"),
])
def test_word_family_members_give_the_game_away(target, leak):
    assert masker.Forbidden([target])(leak)


@pytest.mark.parametrize("target, fine", [("homework", "homemade"), ("dog", "dough"), ("cat", "catalogue")])
def test_unrelated_words_are_allowed(target, fine):
    assert not masker.Forbidden([target])(fine)
