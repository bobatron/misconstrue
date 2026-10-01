from __future__ import annotations

import secrets
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Field, Session, SQLModel, create_engine, select

from app import config

ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no look-alikes (l/1, o/0)


def new_slug() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(8))


def new_secret() -> str:
    """Unguessable code for links that must stay private (results pages, videos)."""
    return secrets.token_urlsafe(12)


def now() -> datetime:
    return datetime.now(timezone.utc)


class Challenge(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(default_factory=new_slug, index=True, unique=True)  # User 2's share link
    results_token: str | None = Field(default_factory=new_secret, index=True)  # User 1's private results link
    target_text: str
    masked_text: str
    mask_source: str  # "llm" | "template"
    created_at: datetime = Field(default_factory=now)


class Recording(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    public_id: str | None = Field(default_factory=new_secret, index=True)  # used in URLs, never the number
    challenge_id: int = Field(foreign_key="challenge.id", index=True)
    status: str = "uploaded"  # uploaded | processing | done | needs_retake | failed
    message: str = ""
    missing: str = ""  # comma-separated masked word indices the speaker missed
    input_path: str
    output_path: str = ""
    party_output_path: str = ""  # party-mode version (music, words on the beat)
    prompt_timings: str = ""  # JSON from the prompter: when each prompt was shown and spoken
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
    party_output_path: str = ""
    cadence_json: str = "{}"  # rhythm vs the link's reference voice, if it has one
    created_at: datetime = Field(default_factory=now)


def work_dir(recording: Recording) -> Path:
    """Where a recording's analysis (converted media, transcript, alignment) is kept."""
    return Path(recording.input_path).parent / f"{recording.id}-work"


config.DATA_DIR.mkdir(parents=True, exist_ok=True)
engine = create_engine(f"sqlite:///{config.DATA_DIR / 'misconstrue.db'}", connect_args={"check_same_thread": False})


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    _add_missing_columns()
    _backfill_secrets()


def _backfill_secrets() -> None:
    """Rows made before a secret column existed get one now."""
    with Session(engine) as s:
        for ch in s.exec(select(Challenge).where(Challenge.results_token == None)):  # noqa: E711
            ch.results_token = new_secret()
            s.add(ch)
        for rec in s.exec(select(Recording).where(Recording.public_id == None)):  # noqa: E711
            rec.public_id = new_secret()
            s.add(rec)
        s.commit()


def _add_missing_columns() -> None:
    """create_all() makes new tables but doesn't add new columns to existing ones: do that here."""
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table.name})")}
            for column in table.columns:
                if column.name not in existing:
                    ddl = column.type.compile(engine.dialect)
                    default = column.default.arg if column.default is not None and not callable(column.default.arg) else None
                    clause = f" NOT NULL DEFAULT {default!r}" if default is not None else ""
                    conn.exec_driver_sql(f"ALTER TABLE {table.name} ADD COLUMN {column.name} {ddl}{clause}")


def session() -> Session:
    return Session(engine)
