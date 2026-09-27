from pathlib import Path

import pytest

from app import config


def _load(tmp_path, monkeypatch, text, env=None):
    env_file = tmp_path / ".env"
    env_file.write_text(text)
    monkeypatch.setattr(config, "ENV_FILE", env_file)
    for k in config.Settings.model_fields:
        monkeypatch.delenv(k, raising=False)
    for k, v in (env or {}).items():
        monkeypatch.setenv(k, v)
    return config.load()


def test_defaults_without_env_file(tmp_path, monkeypatch):
    s = _load(tmp_path, monkeypatch, "")
    assert s.MAX_RETAKES == 5 and s.LLM_PROVIDER == "none"


def test_env_file_overrides_defaults(tmp_path, monkeypatch):
    s = _load(tmp_path, monkeypatch, "MAX_RETAKES=3\nCROSSFADE_MS=12.5\n# comment\n")
    assert s.MAX_RETAKES == 3 and s.CROSSFADE_MS == 12.5


def test_environment_beats_env_file(tmp_path, monkeypatch):
    s = _load(tmp_path, monkeypatch, "MAX_RETAKES=3\n", env={"MAX_RETAKES": "7"})
    assert s.MAX_RETAKES == 7


def test_typo_is_reported_with_suggestion(tmp_path, monkeypatch):
    with pytest.raises(config.SettingsError, match="did you mean MAX_RETAKES"):
        _load(tmp_path, monkeypatch, "MAX_RETAKE=3\n")


@pytest.mark.parametrize("line", ["MAX_WER=2", "LLM_PROVIDER=openai", "MAX_RETAKES=lots"])
def test_bad_values_are_rejected(tmp_path, monkeypatch, line):
    with pytest.raises(config.SettingsError, match=line.split("=")[0]):
        _load(tmp_path, monkeypatch, line + "\n")


def test_paths_expand_home_and_resolve_against_project_root(tmp_path, monkeypatch):
    s = _load(tmp_path, monkeypatch, "MFA_ROOT_DIR=~/mfa\nDATA_DIR=./somewhere\n")
    assert s.MFA_ROOT_DIR == Path.home() / "mfa"
    assert s.DATA_DIR == config.ROOT / "somewhere"
    assert s.PRONUNCIATION_DICT == Path.home() / "mfa" / "pretrained_models" / "dictionary" / "english_us_arpa.dict"


def test_runtime_changes_are_validated_and_live(monkeypatch):
    monkeypatch.setattr(config.settings, "CROSSFADE_MS", 20)
    assert config.CROSSFADE_MS == 20
    with pytest.raises(ValueError):
        config.settings.CROSSFADE_MS = 500


def test_env_example_is_up_to_date():
    committed = (config.ROOT / ".env.example").read_text()
    assert committed == config.example_env(), "run `make env-example` to regenerate .env.example"
    for name in config.Settings.model_fields:
        assert f"# {name}=" in committed
