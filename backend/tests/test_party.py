import numpy as np

from app.core import party
from app.core.phonetics import sentence_phones, tokenize
from app.core.splice import Span

SR = 16000


def test_music_is_the_right_length_and_not_silent():
    music = party.track(bpm=120, beats=8, sr=SR)  # 8 beats at 120 BPM = 4 s, plus a 1 s tail
    assert abs(len(music) / SR - 5.0) < 0.01
    assert 0.5 < float(np.max(np.abs(music))) <= 0.91
    assert float(np.sqrt(np.mean(music**2))) > 0.05


def test_every_word_starts_on_a_beat_after_a_one_bar_intro():
    beat = party.beat_seconds(120)  # 0.5 s
    slots, beats = party.lay_out([(0, 0.3), (1, 0.9), (2, 0.52), (3, 0.2)], bpm=120)
    starts = [s.start_s for s in slots]
    assert starts[0] == party.INTRO_BEATS * beat
    assert all(abs(s / beat - round(s / beat)) < 1e-9 for s in starts)
    assert [s.beats for s in slots] == [1, 2, 1, 1]  # 0.9 s needs two beats; 0.52 s is close enough to one
    assert beats % 4 == 0 and beats * beat >= slots[-1].end_s + party.OUTRO_BEATS * beat - 1e-9


def test_pieces_are_split_where_a_word_ends():
    target = sentence_phones(tokenize("this is"))  # DH IH S | IH Z
    span = Span(t_start=1, t_end=4, s_start=10)  # IH S | IH: runs across the word boundary
    tagged = party.split_at_words([span], target)
    assert [(w, (sp.t_start, sp.t_end, sp.s_start)) for w, sp in tagged] == [(0, (1, 3, 10)), (1, (3, 4, 12))]


def test_music_dips_while_someone_speaks():
    music = np.ones(SR * 2, dtype=np.float32)
    voice = np.zeros(SR * 2, dtype=np.float32)
    voice[SR // 2 : SR] = 0.5  # speech from 0.5 to 1.0 s
    ducked = party.duck(music, voice, SR, depth=0.6)
    assert ducked[int(0.75 * SR)] < 0.6 and ducked[int(1.8 * SR)] > 0.95
