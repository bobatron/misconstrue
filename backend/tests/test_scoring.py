import sys
from pathlib import Path

from app.core.scoring import _edit_distance

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import bench  # noqa: E402


def test_edit_distance_counts_substitutions_insertions_deletions():
    assert _edit_distance([], []) == 0
    assert _edit_distance(list("abc"), list("abc")) == 0
    assert _edit_distance(list("abc"), list("axc")) == 1
    assert _edit_distance(list("abc"), list("ab")) == 1
    assert _edit_distance(list("abc"), list("abcd")) == 1
    assert _edit_distance(list("abc"), list("")) == 3


def test_bench_parses_recording_id_ranges():
    assert bench._parse_ids(["11", "12", "14-16", "20,22"]) == [11, 12, 14, 15, 16, 20, 22]
