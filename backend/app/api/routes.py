from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlmodel import func, select

from app import config
from app.core import masker, phonetics, pipeline
from app.core.prompts import split_prompts
from app.models import Challenge, Recording, session, work_dir
from app.worker import worker

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

UPLOAD_SUFFIXES = {".webm", ".mp4", ".mov", ".m4v", ".mkv"}


class CreateChallenge(BaseModel):
    text: str = Field(min_length=1, max_length=200)


def display_tokens(masked_text: str) -> list[list[int]]:
    """For each whitespace token shown on screen, the tokenize() word indices it contains."""
    out, n = [], 0
    for tok in masked_text.split():
        k = len(phonetics.tokenize(tok))
        out.append(list(range(n, n + k)))
        n += k
    return out


def _challenge(slug: str) -> Challenge:
    with session() as s:
        ch = s.exec(select(Challenge).where(Challenge.slug == slug)).first()
    if not ch:
        raise HTTPException(404, "That link doesn't exist")
    return ch


@router.post("/challenges")
def create_challenge(body: CreateChallenge) -> dict:
    words = phonetics.tokenize(body.text)
    if not words:
        raise HTTPException(422, "Type a sentence with some words in it")
    if len(words) > config.MAX_TARGET_WORDS:
        raise HTTPException(422, f"Keep it to {config.MAX_TARGET_WORDS} words or fewer")
    try:
        result = masker.mask(body.text)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    with session() as s:
        ch = Challenge(target_text=body.text.strip(), masked_text=result.masked_text, mask_source=result.source)
        s.add(ch)
        s.commit()
        s.refresh(ch)
    return {"slug": ch.slug, "masked_text": ch.masked_text, "results_token": ch.results_token}


@router.get("/challenges/{slug}")
def get_challenge(slug: str) -> dict:
    ch = _challenge(slug)
    # Never send the target text here: the reader mustn't see it before the reveal.
    return {
        "slug": ch.slug,
        "masked_text": ch.masked_text,
        "tokens": ch.masked_text.split(),
        "prompts": split_prompts(ch.masked_text, config.WORDS_PER_PROMPT),
        "prompter": {
            "advance_silence_ms": config.ADVANCE_SILENCE_MS,
            "min_speech_per_word_ms": config.MIN_SPEECH_PER_WORD_MS,
            "hint_after_s": config.PROMPT_HINT_S,
        },
    }


@router.post("/challenges/{slug}/recordings")
async def upload_recording(slug: str, video: UploadFile, prompt_timings: str = Form("")) -> dict:
    ch = _challenge(slug)
    suffix = Path(video.filename or "").suffix.lower()
    if suffix not in UPLOAD_SUFFIXES:
        suffix = ".webm" if "webm" in (video.content_type or "") else ".mp4"
    folder = config.DATA_DIR / "recordings" / ch.slug
    folder.mkdir(parents=True, exist_ok=True)

    with session() as s:
        rec = Recording(challenge_id=ch.id, input_path="")
        s.add(rec)
        s.commit()
        rec_id, public_id = rec.id, rec.public_id
        attempts = s.exec(select(func.count()).select_from(Recording).where(Recording.challenge_id == ch.id)).one()

    dest = folder / f"{rec_id}-input{suffix}"
    size = 0
    with dest.open("wb") as f:
        while chunk := await video.read(1 << 20):
            size += len(chunk)
            if size > config.MAX_UPLOAD_MB * 1024 * 1024:
                break
            f.write(chunk)

    with session() as s:
        rec = s.get(Recording, rec_id)
        if size > config.MAX_UPLOAD_MB * 1024 * 1024:
            dest.unlink(missing_ok=True)
            s.delete(rec)
            s.commit()
            raise HTTPException(413, "That recording is too big")
        rec.input_path = str(dest)
        rec.prompt_timings = prompt_timings[:20000]
        s.add(rec)
        s.commit()

    worker.submit(_process, rec_id, ch.id, attempts >= config.MAX_RETAKES)
    return {"recording": public_id, "status": "uploaded"}


def _process(recording_id: int, challenge_id: int, force: bool) -> None:
    with session() as s:
        rec = s.get(Recording, recording_id)
        ch = s.get(Challenge, challenge_id)
        rec.status = "processing"
        s.add(rec)
        s.commit()
        inp, masked, target = Path(rec.input_path), ch.masked_text, ch.target_text
        timings = rec.prompt_timings
        workdir = work_dir(rec)  # kept: the tuning page re-renders from it

    out = inp.parent / f"{recording_id}-output.mp4"
    try:
        res = pipeline.run(inp, masked, target, workdir, out, force=force, prompt_timings=timings)
    except Exception:
        log.exception("processing recording %s failed", recording_id)
        res = pipeline.PipelineResult("failed", "Something went wrong on our side. Please try recording again.")

    with session() as s:
        rec = s.get(Recording, recording_id)
        rec.status = res.status
        rec.message = res.message
        rec.missing = ",".join(map(str, res.missing))
        rec.output_path = str(res.output or "")
        rec.party_output_path = str(res.party_output or "")
        s.add(rec)
        s.commit()


def _recording(public_id: str) -> tuple[Recording, Challenge]:
    with session() as s:
        rec = s.exec(select(Recording).where(Recording.public_id == public_id)).first()
        if not rec:
            raise HTTPException(404, "Recording not found")
        return rec, s.get(Challenge, rec.challenge_id)


def video_url(rec: Recording) -> str | None:
    return f"/api/recordings/{rec.public_id}/video" if rec.status == "done" else None


def party_video_url(rec: Recording) -> str | None:
    if rec.status == "done" and rec.party_output_path and Path(rec.party_output_path).exists():
        return f"/api/recordings/{rec.public_id}/video?version=party"
    return None


@router.get("/recordings/{public_id}")
def recording_status(public_id: str) -> dict:
    rec, ch = _recording(public_id)
    body: dict = {"status": rec.status, "message": rec.message}
    if rec.status == "needs_retake":
        missing = {int(i) for i in rec.missing.split(",") if i}
        body["missing_tokens"] = [t for t, words in enumerate(display_tokens(ch.masked_text)) if set(words) & missing]
    if rec.status == "done":
        body["video_url"] = video_url(rec)
        body["party_video_url"] = party_video_url(rec)
        body["target_text"] = ch.target_text  # the reveal
    return body


@router.get("/recordings/{public_id}/video")
def recording_video(public_id: str, version: str = "plain") -> FileResponse:
    rec, _ = _recording(public_id)
    path = rec.party_output_path if version == "party" else rec.output_path
    if rec.status != "done" or not path or not Path(path).exists():
        raise HTTPException(404, "Video not ready")
    name = "misconstrued-party.mp4" if version == "party" else "misconstrued.mp4"
    return FileResponse(path, media_type="video/mp4", filename=name)


@router.get("/results/{token}")
def results(token: str) -> dict:
    """User 1's private page: the sentence, the share link and every attempt, with finished videos."""
    with session() as s:
        ch = s.exec(select(Challenge).where(Challenge.results_token == token)).first() if token else None
        if not ch:
            raise HTTPException(404, "That results link doesn't exist")
        recs = s.exec(select(Recording).where(Recording.challenge_id == ch.id).order_by(Recording.id.desc())).all()
    return {
        "slug": ch.slug,
        "target_text": ch.target_text,
        "masked_text": ch.masked_text,
        "created_at": ch.created_at.isoformat(),
        "recordings": [
            {"id": r.public_id, "status": r.status, "created_at": r.created_at.isoformat(),
             "video_url": video_url(r), "party_video_url": party_video_url(r)}
            for r in recs
        ],
    }
