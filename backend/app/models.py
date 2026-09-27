from __future__ import annotations

import secrets
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Field, Session, SQLModel, create_engine

from app import config

ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no look-alikes (l/1, o/0)


def new_slug() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(8))


def now() -> datetime:
    return datetime.now(timezone.utc)


class Challenge(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(default_factory=new_slug, index=True, unique=True)
    target_text: str
    masked_text: str
    mask_source: str  # "llm" | "template"
    created_at: datetime = Field(default_factory=now)


class Recording(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    challenge_id: int = Field(foreign_key="challenge.id", index=True)
    status: str = "uploaded"  # uploaded | processing | done | needs_retake | failed
    message: str = ""
    missing: str = ""  # comma-separated masked word indices the speaker missed
    input_path: str
    output_path: str = ""
    created_at: datetime = Field(default_factory=now)


class Render(SQLModel, table=True):
    """A re-render of a recording from the tuning page, with the settings it used."""

    id: int | None = Field(default=None, primary_key=True)
    recording_id: int = Field(foreign_key="recording.id", index=True)
    status: str = "queued"  # queued | processing | done | needs_retake | failed
    message: str = ""
    settings_json: str = "{}"  # settings that differed from the defaults
    timings_json: str = "{}"
    clarity: float | None = None
    sounds: float | None = None
    heard: str = ""
    output_path: str = ""
    created_at: datetime = Field(default_factory=now)


def work_dir(recording: Recording) -> Path:
    """Where a recording's analysis (converted media, transcript, alignment) is kept."""
    return Path(recording.input_path).parent / f"{recording.id}-work"


config.DATA_DIR.mkdir(parents=True, exist_ok=True)
engine = create_engine(f"sqlite:///{config.DATA_DIR / 'misconstrue.db'}", connect_args={"check_same_thread": False})


def init_db() -> None:
    SQLModel.metadata.create_all(engine)


def session() -> Session:
    return Session(engine)
