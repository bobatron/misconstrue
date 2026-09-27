from app.core.phonetics import sentence_phones, tokenize
from app.core.splice import plan_splice


def _phones(text):
    return sentence_phones(tokenize(text))


def _rebuilt(target, source, spans):
    return [p.symbol for sp in spans for p in source[sp.s_start : sp.s_end]]


def test_plan_covers_every_target_phone_in_order():
    target, source = _phones("I love pizza"), _phones("highly shove the pete's support")
    spans, _ = plan_splice(target, source)
    assert _rebuilt(target, source, spans) == [p.symbol for p in target]
    assert spans[0].t_start == 0 and spans[-1].t_end == len(target)
    assert all(a.t_end == b.t_start for a, b in zip(spans, spans[1:]))


def test_prefers_long_runs():
    target = _phones("cat")
    spans, _ = plan_splice(target, _phones("the catalogue"))
    assert len(spans) == 1


def test_impossible_when_a_sound_is_missing():
    assert plan_splice(_phones("zoo"), _phones("cat")) is None


def test_squashed_alignment_is_avoided():
    target = _phones("cat")
    source = _phones("cat cat")
    squashed = [(0.00, 0.01), (0.01, 0.02), (0.02, 0.03)]
    normal = [(1.0, 1.08), (1.08, 1.2), (1.2, 1.28)]
    spans, _ = plan_splice(target, source, squashed + normal)
    assert spans[0].s_start == 3
