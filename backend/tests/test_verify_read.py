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


def _alignment(words_times):
    from app.core.aligner import Alignment
    from app.core.phonetics import Phone

    words, phones, times = [], [], []
    for wi, (w, s, e) in enumerate(words_times):
        words.append((w, s, e))
        phones.append(Phone("AH", wi, 0, 1))
        times.append((s, e))
    return Alignment(words, phones, times)


def test_ranges_that_only_touch_are_fine():
    # Common in good paragraph reads (fixture r12): Whisper's range ends where the aligner's starts.
    heard = [Heard("the", 0.0, 0.3), Heard("happy", 0.3, 0.7), Heard("robin", 0.7, 1.0)]
    alignment = _alignment([("the", 0.0, 0.3), ("happy", 0.3, 0.7), ("robin", 1.0, 1.4)])
    assert check("The happy robin", heard, alignment, {2}).ok


def test_word_after_a_pause_is_not_rejected():
    # Whisper stretches "robin" back into the 1 s pause before it; the aligner is precise.
    heard = [Heard("the", 0.0, 0.3), Heard("happy", 0.3, 0.7), Heard("robin", 0.7, 2.2)]
    alignment = _alignment([("the", 0.0, 0.3), ("happy", 0.3, 0.7), ("robin", 1.7, 2.2)])
    assert check("The happy robin", heard, alignment, {2}).ok


def test_word_placed_where_it_was_not_said_is_rejected():
    # Like fixture r23: the aligner's "robin" ends 0.11 s before Whisper hears it begin.
    heard = [Heard("the", 0.0, 0.3), Heard("happy", 0.3, 0.7), Heard("robin", 1.51, 2.7)]
    alignment = _alignment([("the", 0.0, 0.3), ("happy", 0.3, 0.7), ("robin", 1.04, 1.40)])
    res = check("The happy robin", heard, alignment, {2})
    assert not res.ok and res.missing == [2]
