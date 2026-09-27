"""App-wide settings.

Every setting has a built-in default. Override it in a `.env` file at the project root
(see `.env.example`), or with an environment variable of the same name, which wins over `.env`.

Code reads settings as `config.NAME`. They're served from the live `settings` object, so a
change made at runtime (e.g. by a future tuning page) applies to the next video.
"""
from __future__ import annotations

import difflib
import os
import textwrap
from pathlib import Path
from typing import Any, Literal

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = Path(os.getenv("MISCONSTRUE_ENV_FILE", ROOT / ".env"))

GROUPS = {
    "masking": "Masking: how the disguise sentence is made",
    "check": "Retake check: how strict we are about reading the whole sentence",
    "video": "Output video",
    "limits": "Limits",
    "system": "Models, paths & services (advanced)",
}


def setting(default: Any, group: str, help: str, **constraints: Any) -> Any:
    return Field(default, description=help, json_schema_extra={"group": group}, **constraints)


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    # ── Masking ────────────────────────────────────────────────────────────────
    LLM_PROVIDER: Literal["ollama", "none"] = setting(
        "ollama", "masking",
        "Which AI writes natural phrases around the carrier words. 'none' = plain word lists.")
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
    MAX_WORD_TIME_DRIFT_S: float = setting(
        0.6, "check", "How far (seconds) the aligner and the transcriber may disagree about when a needed "
        "word was said. Lower = stricter.", ge=0.05, le=5.0)
    MAX_RETAKES: int = setting(
        5, "check", "After this many attempts, make the best video we can instead of asking again.",
        ge=1, le=50)

    # ── Output video ───────────────────────────────────────────────────────────
    CROSSFADE_MS: float = setting(
        8, "video", "Overlap between stitched sound pieces (ms). Longer = smoother but blurrier.", ge=0, le=50)
    SNAP_WINDOW_MS: float = setting(
        15, "video", "How far (ms) each cut may move to land on a quieter moment.", ge=0, le=50)
    LEAD_IN_S: float = setting(
        0.3, "video", "Silent footage before and after the sentence (seconds).", ge=0.0, le=3.0)
    OUTPUT_HEIGHT: int = setting(480, "video", "Output video height in pixels.", ge=144, le=1080)
    FPS: int = setting(30, "video", "Output frames per second.", ge=10, le=60)
    AUDIO_SR: int = setting(48000, "video", "Output audio sample rate (Hz).", ge=16000, le=96000)

    # ── Limits ─────────────────────────────────────────────────────────────────
    MAX_TARGET_WORDS: int = setting(25, "limits", "Longest sentence User 1 may enter (words).", ge=1, le=100)
    MAX_UPLOAD_MB: int = setting(100, "limits", "Largest recording upload (MB).", ge=1, le=2000)

    # ── Models, paths & services ───────────────────────────────────────────────
    OLLAMA_URL: str = setting("http://localhost:11434", "system", "Where Ollama is listening.")
    WHISPER_MODEL: str = setting(
        "small.en", "system", "Whisper model for the retake check (tiny.en, base.en, small.en, medium.en).")
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


def changed() -> dict[str, Any]:
    """Settings that differ from their built-in defaults."""
    defaults = Settings()
    return {k: v for k, v in settings.model_dump().items() if v != getattr(defaults, k)}


def describe() -> str:
    """Human-readable list of the settings in use, grouped, with changes marked."""
    diff = changed()
    file_values, env_values = _read_sources()
    out = [f"Settings (defaults, then {ENV_FILE.name if ENV_FILE.exists() else 'no .env file'}, then environment)"]
    for group, title in GROUPS.items():
        out.append(f"\n{title}")
        for name, field in Settings.model_fields.items():
            if (field.json_schema_extra or {}).get("group") != group:
                continue
            mark = ""
            if name in diff:
                mark = "  * env var" if name in env_values else "  * .env" if name in file_values else "  *"
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


settings = load()


def __getattr__(name: str) -> Any:
    # `config.NAME` -> the live settings object.
    if name in Settings.model_fields:
        return getattr(settings, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
