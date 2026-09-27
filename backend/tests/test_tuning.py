import json

import pytest
from fastapi.testclient import TestClient

from app import config


@pytest.fixture
def tuning(tmp_path, monkeypatch):
    """Tuning layer writing to a temp folder, restored afterwards."""
    monkeypatch.setattr(config, "_base", config._base.model_copy(update={"DATA_DIR": tmp_path}))
    monkeypatch.setattr(config, "_tuned", {})
    yield tmp_path / "settings.json"
    config.reset_tuning()


def test_apply_saves_and_is_live(tuning):
    config.apply_tuning({"CROSSFADE_MS": 20, "MAX_RETAKES": 3})
    assert config.CROSSFADE_MS == 20 and config.MAX_RETAKES == 3
    assert json.loads(tuning.read_text()) == {"CROSSFADE_MS": 20.0, "MAX_RETAKES": 3}
    assert config.source("CROSSFADE_MS") == "tuning page"


def test_setting_back_to_base_value_forgets_it(tuning):
    config.apply_tuning({"CROSSFADE_MS": 20})
    config.apply_tuning({"CROSSFADE_MS": config._base.CROSSFADE_MS})
    assert not tuning.exists()


def test_invalid_changes_apply_nothing(tuning):
    before = config.CROSSFADE_MS
    with pytest.raises(config.TuningError) as exc:
        config.apply_tuning({"CROSSFADE_MS": 12, "MAX_WER": 5, "DATA_DIR": "/tmp", "NOPE": 1})
    assert set(exc.value.errors) == {"MAX_WER", "DATA_DIR", "NOPE"}
    assert config.CROSSFADE_MS == before


def test_reset_restores_base_and_notifies(tuning):
    seen = []
    config.on_change(seen.append)
    config.apply_tuning({"MIN_CARRIER_ZIPF": 4.0})
    config.reset_tuning()
    assert config.MIN_CARRIER_ZIPF == config._base.MIN_CARRIER_ZIPF
    assert seen == [{"MIN_CARRIER_ZIPF"}, {"MIN_CARRIER_ZIPF"}]
    config._listeners.remove(seen.append)


def test_saved_tuning_is_loaded_at_startup_and_bad_entries_skipped(tuning):
    tuning.write_text(json.dumps({"CROSSFADE_MS": 14, "MAX_WER": 9, "DATA_DIR": "/x", "NOPE": 1}))
    live, tuned = config._start(config._base)
    assert live.CROSSFADE_MS == 14 and tuned == {"CROSSFADE_MS": 14}


def test_tuning_api_is_local_only():
    from app.main import app

    local = TestClient(app, client=("127.0.0.1", 5000))
    remote = TestClient(app, client=("203.0.113.9", 5000))
    assert local.get("/api/tune/settings").status_code == 200
    assert remote.get("/api/tune/settings").status_code == 403
