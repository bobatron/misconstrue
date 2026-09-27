from app import config
from app.core import aligner

DICT = """hello\t0.99\t0.1\t1.0\t1.0\tHH AH0 L OW1
hello\t0.36\t0.1\t1.0\t1.0\tHH EH0 L OW1
world\t0.99\t0.1\t1.0\t1.0\tW ER1 L D
other\t0.99\t0.1\t1.0\t1.0\tAH1 DH ER0
"""


def _use_dict(tmp_path, monkeypatch):
    path = tmp_path / "full.dict"
    path.write_text(DICT)
    monkeypatch.setattr(config.settings, "PRONUNCIATION_DICT", path)
    aligner._dictionary_lines.cache_clear()


def test_mini_dictionary_keeps_every_variant_and_only_needed_words(tmp_path, monkeypatch):
    _use_dict(tmp_path, monkeypatch)
    mini = aligner.dictionary_for(["hello", "world", "hello"], tmp_path)
    lines = open(mini).read().splitlines()
    assert lines == DICT.splitlines()[:3]


def test_falls_back_to_full_dictionary_for_unknown_words(tmp_path, monkeypatch):
    _use_dict(tmp_path, monkeypatch)
    assert aligner.dictionary_for(["hello", "zzyzx"], tmp_path) == str(tmp_path / "full.dict")
