from app.core.verify_read import Heard, check


def _heard(text):
    return [Heard(w, i * 0.5, i * 0.5 + 0.4) for i, w in enumerate(text.split())]


MASKED = "The happy robin sang a lovely song today"


def test_full_reading_passes():
    assert check(MASKED, _heard("the happy robin sang a lovely song today"), None, {2, 5}).ok


def test_homophones_and_numbers_count():
    assert check("I won one prize", _heard("i one won prize"), None, {1, 2}).ok


def test_dropped_ending_asks_for_retake():
    res = check(MASKED, _heard("the happy robin sang a"), None, {5, 6})
    assert not res.ok
    assert 5 in res.missing and "lovely" in res.message


def test_skipped_critical_word_asks_for_retake():
    res = check(MASKED, _heard("the happy sang a lovely song today"), None, {2})
    assert not res.ok and res.missing == [2]


def test_minor_slip_in_unused_word_is_ok():
    assert check(MASKED, _heard("the happy robin sang the lovely song today"), None, {2, 5}).ok


def test_silence_asks_for_retake():
    res = check(MASKED, [], None, set())
    assert not res.ok and "couldn't hear" in res.message
