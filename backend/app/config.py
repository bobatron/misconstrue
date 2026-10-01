"""App-wide settings.

Every setting has a built-in default. Override it in a `.env` file at the project root
(see `.env.example`), or with an environment variable of the same name, which wins over `.env`.
Changes made on the tuning page (/tune) are saved to DATA_DIR/settings.json and win over both.

Code reads settings as `config.NAME`. They're served from the live `settings` object, so a
change made at runtime applies to the next video.
"""
from __future__ import annotations

import difflib
import json
import logging
import os
import textwrap
from pathlib import Path
from typing import Any, Callable, Literal

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = Path(os.getenv("MISCONSTRUE_ENV_FILE", ROOT / ".env"))

# Groups whose settings only take effect after a restart (models are loaded once, paths are
# fixed): shown on the tuning page but not editable there.
RESTART_GROUPS = {"system"}

GROUPS = {
    "masking": "Masking: how the disguise sentence is made",
    "check": "Retake check: how strict we are about reading the whole sentence",
    "recording": "Recording: what User 2 sees while recording",
    "video": "Output video",
    "party": "Party mode: music and effects",
    "limits": "Limits",
    "system": "Models, paths & services (advanced)",
}


def setting(default: Any, group: str, help: str, **constraints: Any) -> Any:
    return Field(default, description=help, json_schema_extra={"group": group}, **constraints)


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    # ── Masking ────────────────────────────────────────────────────────────────
    LLM_PROVIDER: Literal["ollama", "none"] = setting(
        "none", "masking",
        "'none' (default) = the disguise is just the carrier words, shown one at a time: instant. 'ollama' = a "
        "local AI wraps them in natural phrases (slower, needs Ollama running).")
    OLLAMA_MODEL: str = setting(
        "qwen3:8b", "masking", "Ollama model to use (must be pulled: `ollama pull <name>`).")
    LLM_CANDIDATES: int = setting(
        6, "masking", "Phrases the AI suggests per group; the shortest valid one is used. More = better odds, slower.",
        ge=1, le=20)
    LLM_GROUPS_PER_PHRASE: int = setting(
        3, "masking", "Carrier-word groups the AI must fit into one phrase. Small models manage 2-3.",
        ge=1, le=6)
    MIN_CARRIER_ZIPF: float = setting(
        3.5, "masking",
        "How common a carrier word must be (Zipf scale: 3 = uncommon, 4 = everyday, 5 = very common). "
        "Higher = easier words to read, but fewer choices and more cuts.",
        ge=1.0, le=7.0)
    CONTAINED_WORD_MIN_LETTERS: int = setting(
        4, "masking", "Carrier words may not contain a target word of this many letters or more "
        "(stops 'originally' hiding inside a carrier).", ge=2, le=12)
    SHARED_LETTERS_LIMIT: int = setting(
        6, "masking", "Carrier words sharing this many letters in a row with a target word are rejected "
        "('aboriginal' vs 'originally'). Higher = less secret, more choices.", ge=3, le=20)
    MIN_VARIANT_PROB: float = setting(
        0.3, "masking", "Pronunciations likelier than this must ALL contain a carrier's sounds, so it doesn't "
        "matter which way the reader says the word. Lower = safer, fewer choices.", ge=0.0, le=1.0)

    # ── Retake check ───────────────────────────────────────────────────────────
    MAX_WER: float = setting(
        0.5, "check", "Largest share of masked-sentence words that may be missed or misheard "
        "(0.5 = half). Words the edit needs must always be there. Lower = stricter.", ge=0.0, le=1.0)
    FUZZY_MATCH_RATIO: float = setting(
        0.6, "check", "How much of a word's sounds must be heard to count a near-miss as said "
        "('forward' for 'forehead'). Higher = stricter.", ge=0.0, le=1.0)
    MIN_CRITICAL_PHONE_MS: float = setting(
        35, "check", "Needed words whose sounds average shorter than this (ms) are treated as not really "
        "said (mumbled or skipped). Higher = stricter.", ge=0, le=200)
    MAX_WORD_TIME_GAP_S: float = setting(
        0.05, "check", "Largest gap (seconds) allowed between where the aligner put a needed word and where the "
        "transcriber heard it. Catches the aligner slipping out of step with the speech. Lower = stricter.",
        ge=0.0, le=2.0)
    MAX_RETAKES: int = setting(
        5, "check", "After this many attempts, make the best video we can instead of asking again.",
        ge=1, le=50)

    # ── Recording ──────────────────────────────────────────────────────────────
    WORDS_PER_PROMPT: int = setting(
        1, "recording", "Words shown at a time while recording. 1 = one word at a time; 2-3 keeps short words "
        "sounding natural ('the', not 'thee').", ge=1, le=8)
    ADVANCE_SILENCE_MS: float = setting(
        600, "recording", "How long a pause (ms) after speaking moves on to the next prompt. Longer = fewer "
        "accidental skips mid-phrase, but slower.", ge=200, le=2000)
    MIN_SPEECH_PER_WORD_MS: float = setting(
        200, "recording", "A pause only moves on once this much speech (ms) per word on screen has been heard, so "
        "pausing between words ('Pilot... am... forehead') doesn't skip the rest.", ge=0, le=600)
    PROMPT_HINT_S: float = setting(
        6, "recording", "If no speech is heard for this long (seconds), highlight the Next button so nobody gets "
        "stuck (e.g. a quiet voice).", ge=2, le=30)

    # ── Output video ───────────────────────────────────────────────────────────
    PLAYBACK_SPEED: float = setting(
        0.6, "video", "How fast the finished sentence plays compared with how it was spoken (1.0 = as recorded, "
        "0.6 = 40% slower). The pitch doesn't change, and the video slows down with it.", ge=0.4, le=1.0)
    MIN_PIECE_MS: float = setting(
        300, "video", "After slowing down, sound pieces shorter than this (ms) are stretched further, up to 2x, so "
        "very short sounds are easier to hear. 0 = off.", ge=0, le=600)
    TIGHTEN_PIECES: bool = setting(
        True, "video", "Trim silence at the edges of cut pieces and shorten long silences inside them.")
    MAX_GAP_IN_WORD_MS: float = setting(
        70, "video", "Silences inside a cut piece longer than this (ms) are shortened, so rebuilt words have "
        "no audible gaps (words read on their own end in pauses, and t/k/p hold a silence).", ge=20, le=500)
    KEEP_GAP_IN_WORD_MS: float = setting(
        50, "video", "How much of a long silence to keep (ms): about a natural t/k/p.", ge=0, le=200)
    CROSSFADE_MS: float = setting(
        8, "video", "Overlap between stitched sound pieces (ms). Longer = smoother but blurrier.", ge=0, le=50)
    SNAP_WINDOW_MS: float = setting(
        15, "video", "How far (ms) each cut may move to land on a quieter moment.", ge=0, le=50)
    LEAD_IN_S: float = setting(
        0.3, "video", "Silent footage before and after the sentence (seconds).", ge=0.0, le=3.0)
    OUTPUT_HEIGHT: int = setting(480, "video", "Output video height in pixels.", ge=144, le=1080)
    FPS: int = setting(30, "video", "Output frames per second.", ge=10, le=60)
    AUDIO_SR: int = setting(48000, "video", "Output audio sample rate (Hz).", ge=16000, le=96000)

    # ── Party mode ─────────────────────────────────────────────────────────────
    PARTY_MODE: bool = setting(
        True, "party", "Also make the party version: a generated dance beat with each word landing on a beat. "
        "Shown by default; the plain video stays available.")
    PARTY_BPM: float = setting(124, "party", "Tempo of the dance beat (beats per minute).", ge=80, le=160)
    PARTY_PLAYBACK_SPEED: float = setting(
        0.85, "party", "Speech speed in the party version (1.0 = as recorded). The beat already spaces the words "
        "out, so it needn't be as slow as the plain video.", ge=0.4, le=1.0)
    PARTY_EFFECTS: bool = setting(
        True, "party", "Beat-timed video effects: zoom punch, wobble, a colour per word, a flash each bar.")
    PARTY_CAPTIONS: bool = setting(
        True, "party", "Show each word big on screen as it's said, plus the intro and 'misconstrued!' cards.")
    MUSIC_VOLUME: float = setting(0.5, "party", "How loud the music is under the voice (0-1).", ge=0.0, le=1.0)
    MUSIC_DUCKING: float = setting(
        0.6, "party", "How much the music dips while a word is spoken, so it stays clear (0 = not at all).",
        ge=0.0, le=1.0)

    # ── Limits ─────────────────────────────────────────────────────────────────
    MAX_TARGET_WORDS: int = setting(25, "limits", "Longest sentence User 1 may enter (words).", ge=1, le=100)
    MAX_UPLOAD_MB: int = setting(100, "limits", "Largest recording upload (MB).", ge=1, le=2000)

    # ── Models, paths & services ───────────────────────────────────────────────
    OLLAMA_URL: str = setting("http://localhost:11434", "system", "Where Ollama is listening.")
    WHISPER_MODEL: str = setting(
        "small.en", "system", "Whisper model for the retake check (tiny.en, base.en, small.en, medium.en).")
    ALIGNER_MODE: Literal["in_process", "command"] = setting(
        "in_process", "system", "How to run the aligner: 'in_process' keeps it loaded (~0.4 s per recording); "
        "'command' starts the mfa program each time (~4 s). in_process falls back to command if it breaks.")
    MFA_ACOUSTIC_MODEL: str = setting("english_us_arpa", "system", "Montreal Forced Aligner acoustic model.")
    MFA_DICTIONARY: str = setting("english_us_arpa", "system", "Montreal Forced Aligner pronunciation dictionary.")
    MFA_ROOT_DIR: Path = setting(Path.home() / "Documents" / "MFA", "system", "Where MFA keeps its models.")
    PRONUNCIATION_DICT: Path | None = setting(
        None, "system", "Dictionary file to plan with. Default: the MFA dictionary above, so planning and "
        "alignment always agree.")
    DATA_DIR: Path = setting(ROOT / "data", "system", "Where recordings, videos and the database are stored.")

    @field_validator("MFA_ROOT_DIR", "PRONUNCIATION_DICT", "DATA_DIR", mode="after")
    @classmethod
    def _resolve_path(cls, v: Path | None) -> Path | None:
        # "~/x" -> home folder; "./x" -> relative to the project root, wherever the app starts from.
        if v is None:
            return v
        v = v.expanduser()
        return v if v.is_absolute() else (ROOT / v).resolve()

    @model_validator(mode="after")
    def _derive_paths(self) -> Settings:
        if self.PRONUNCIATION_DICT is None:
            path = self.MFA_ROOT_DIR / "pretrained_models" / "dictionary" / f"{self.MFA_DICTIONARY}.dict"
            object.__setattr__(self, "PRONUNCIATION_DICT", path)
        return self


class SettingsError(SystemExit):
    """Bad settings: stop with a readable message instead of a traceback."""


def _read_sources() -> tuple[dict[str, str], dict[str, str]]:
    file_values = {k: v for k, v in dotenv_values(ENV_FILE).items() if v is not None} if ENV_FILE.exists() else {}
    env_values = {k: os.environ[k] for k in Settings.model_fields if k in os.environ}
    return file_values, env_values


def load() -> Settings:
    file_values, env_values = _read_sources()
    unknown = [k for k in file_values if k not in Settings.model_fields]
    if unknown:
        lines = []
        for k in unknown:
            close = difflib.get_close_matches(k, Settings.model_fields, n=1)
            lines.append(f"  {k}" + (f"  (did you mean {close[0]}?)" if close else ""))
        raise SettingsError(f"Unknown setting(s) in {ENV_FILE}:\n" + "\n".join(lines))
    try:
        return Settings(**{**file_values, **env_values})
    except ValidationError as exc:
        lines = []
        for err in exc.errors():
            name = str(err["loc"][0]) if err["loc"] else "?"
            given = {**file_values, **env_values}.get(name, err.get("input"))
            lines.append(f"  {name}={given}: {err['msg']}")
        raise SettingsError(f"Invalid setting(s) (from {ENV_FILE} or the environment):\n" + "\n".join(lines)) from None


def group_of(name: str) -> str:
    return (Settings.model_fields[name].json_schema_extra or {}).get("group", "")


def tunable(name: str) -> bool:
    return group_of(name) not in RESTART_GROUPS


# ── Tuning page layer ──────────────────────────────────────────────────────────


class TuningError(ValueError):
    def __init__(self, errors: dict[str, str]):
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))
        self.errors = errors


_listeners: list[Callable[[set[str]], None]] = []


def on_change(callback: Callable[[set[str]], None]) -> None:
    """Call `callback(changed_names)` whenever settings change at runtime."""
    _listeners.append(callback)


def _notify(names: set[str]) -> None:
    if names:
        for callback in _listeners:
            callback(names)


def _tuned_file(data_dir: Path) -> Path:
    return data_dir / "settings.json"


def _start(base: Settings) -> tuple[Settings, dict[str, Any]]:
    """Base settings plus the tuning page's saved changes (bad entries are skipped, not fatal)."""
    live = base.model_copy()
    tuned: dict[str, Any] = {}
    path = _tuned_file(base.DATA_DIR)
    raw = json.loads(path.read_text()) if path.exists() else {}
    for name, value in raw.items():
        if name not in Settings.model_fields or not tunable(name):
            log.warning("Ignoring %s in %s: not a tunable setting", name, path)
            continue
        try:
            setattr(live, name, value)
            tuned[name] = value
        except ValidationError as exc:
            log.warning("Ignoring %s=%r in %s: %s", name, value, path, exc.errors()[0]["msg"])
    return live, tuned


def _save_tuned() -> None:
    path = _tuned_file(_base.DATA_DIR)
    if _tuned:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_tuned, indent=2, sort_keys=True) + "\n")
    else:
        path.unlink(missing_ok=True)


def apply_tuning(changes: dict[str, Any]) -> set[str]:
    """Validate and apply settings changes from the tuning page, all or nothing; save them."""
    errors: dict[str, str] = {}
    candidate = settings.model_copy()
    for name, value in changes.items():
        if name not in Settings.model_fields:
            errors[name] = "unknown setting"
        elif not tunable(name):
            errors[name] = "needs a restart: change it in .env instead"
        else:
            try:
                setattr(candidate, name, value)
            except ValidationError as exc:
                errors[name] = exc.errors()[0]["msg"]
    if errors:
        raise TuningError(errors)

    changed_names = {n for n in changes if getattr(candidate, n) != getattr(settings, n)}
    for name in changes:
        value = getattr(candidate, name)
        setattr(settings, name, value)
        if value == getattr(_base, name):
            _tuned.pop(name, None)  # back to the .env/default value: nothing to remember
        else:
            _tuned[name] = candidate.model_dump(mode="json")[name]
    _save_tuned()
    _notify(changed_names)
    return changed_names


def reset_tuning() -> set[str]:
    """Forget every tuning-page change: back to defaults + .env + environment."""
    changed_names = {n for n in _tuned if getattr(settings, n) != getattr(_base, n)}
    for name in list(_tuned):
        setattr(settings, name, getattr(_base, name))
    _tuned.clear()
    _save_tuned()
    _notify(changed_names)
    return changed_names


def source(name: str) -> str:
    """Where a setting's current value comes from: tuning page, env var, .env or default."""
    if name in _tuned:
        return "tuning page"
    file_values, env_values = _read_sources()
    if name in env_values:
        return "env var"
    if name in file_values:
        return ".env"
    return "default"


def changed() -> dict[str, Any]:
    """Settings that differ from their built-in defaults."""
    defaults = Settings()
    return {k: v for k, v in settings.model_dump().items() if v != getattr(defaults, k)}


def describe() -> str:
    """Human-readable list of the settings in use, grouped, with changes marked."""
    diff = changed()
    out = [f"Settings (defaults, then {ENV_FILE.name if ENV_FILE.exists() else 'no .env file'}, then environment, "
           "then tuning page)"]
    for group, title in GROUPS.items():
        out.append(f"\n{title}")
        for name, field in Settings.model_fields.items():
            if (field.json_schema_extra or {}).get("group") != group:
                continue
            mark = ""
            if name in diff:
                mark = f"  * {source(name)}"
            out.append(f"  {name:28} {getattr(settings, name)}{mark}")
    out.append("\n* = changed from the default")
    return "\n".join(out)


def example_env() -> str:
    """Contents for .env.example, generated from the settings above so they can't drift apart."""
    out = [
        "# misconstrue settings",
        "# Copy this file to .env and uncomment any line to change it, then restart (make dev).",
        "# Environment variables with the same name override .env.",
        "# Check what's in use with: make settings",
    ]
    defaults = Settings()
    for group, title in GROUPS.items():
        out += ["", f"# {'─' * 76}", f"# {title}", f"# {'─' * 76}"]
        for name, field in Settings.model_fields.items():
            if (field.json_schema_extra or {}).get("group") != group:
                continue
            bounds = [f"min {m.ge}" for m in field.metadata if hasattr(m, "ge")]
            bounds += [f"max {m.le}" for m in field.metadata if hasattr(m, "le")]
            rng = f" [{', '.join(bounds)}]" if bounds else ""
            out += [""] + ["# " + line for line in textwrap.wrap(f"{field.description}{rng}", 88)]
            default = getattr(defaults, name) if name != "PRONUNCIATION_DICT" else ""
            if isinstance(default, Path):
                default = str(default).replace(str(ROOT), ".").replace(str(Path.home()), "~")
            out.append(f"# {name}={default}")
    return "\n".join(out) + "\n"


_base = load()  # defaults + .env + environment
settings, _tuned = _start(_base)  # + tuning page


def __getattr__(name: str) -> Any:
    # `config.NAME` -> the live settings object.
    if name in Settings.model_fields:
        return getattr(settings, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
