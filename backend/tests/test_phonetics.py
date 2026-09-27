from app.core import phonetics


def test_tokenize_lowercases_and_keeps_apostrophes():
    assert phonetics.tokenize("Hello, Sir! Don’t go.") == ["hello", "sir", "don't", "go"]


def test_unstressed_vowels_are_distinct():
    assert phonetics.strip_stress("AH0") == "AH0"
    assert phonetics.strip_stress("AH1") == "AH"
    assert phonetics.strip_stress("AH2") == "AH"
    assert phonetics.strip_stress("T") == "T"


def test_sentence_phones_track_words():
    phones = phonetics.sentence_phones(["hi", "there"])
    assert phones[0].word_start and phones[0].word_index == 0
    assert phones[-1].word_end and phones[-1].word_index == 1


def test_carrier_index_has_common_words_only():
    index = phonetics.carrier_index()
    carriers = [c.word for c in index[("P", "IY")]]
    assert carriers, "some common word should contain P IY"
    assert not set(carriers) & phonetics.BLOCKED_CARRIERS


def test_names_and_places_are_not_carriers_unless_everyday_words():
    if not phonetics.proper_names():
        import pytest

        pytest.skip("NLTK name lists not installed")
    carriers = {c.word for cs in phonetics.carrier_index().values() for c in cs}
    assert not {"peter", "boston", "amy", "york"} & carriers
    assert "will" in carriers  # a name, but mostly an everyday word
