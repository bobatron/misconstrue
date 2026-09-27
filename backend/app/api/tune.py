"""Tuning page API: change settings live, re-render saved recordings, compare the results.

Local only: every route refuses requests that don't come from this computer. Before the app
is hosted this needs proper protection (backlog HOST-10).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Literal, get_args, get_origin

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import func, select

from app import config
from app.core import pipeline, scoring
from app.models import Challenge, Recording, Render, session, work_dir
from app.worker import worker

log = logging.getLogger(__name__)

LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


def local_only(request: Request) -> None:
    if not request.client or request.client.host not in LOCAL_HOSTS:
        raise HTTPException(403, "The tuning page is only available on this computer")


router = APIRouter(prefix="/api/tune", dependencies=[Depends(local_only)])

AFFECTS = {
    "masking": "New links",
    "check": "Checking uploads and re-renders",
    "recording": "The record page (reload it)",
    "video": "Videos and re-renders",
    "limits": "New links and uploads",
    "system": "Needs a restart: change in .env",
}


# ── Settings ───────────────────────────────────────────────────────────────────


def _field_info(name: str) -> dict[str, Any]:
    field = config.Settings.model_fields[name]
    annotation = field.annotation
    info: dict[str, Any] = {
        "name": name,
        "group": config.group_of(name),
        "description": field.description,
        "value": config.settings.model_dump(mode="json")[name],
        "default": config.Settings().model_dump(mode="json")[name],
        "editable": config.tunable(name),
        "source": config.source(name),
    }
    if get_origin(annotation) is Literal:
        info["type"] = "choice"
        info["choices"] = list(get_args(annotation))
    elif annotation in (int, float):
        info["type"] = annotation.__name__
        lo = next((m.ge for m in field.metadata if hasattr(m, "ge")), None)
        hi = next((m.le for m in field.metadata if hasattr(m, "le")), None)
        info["min"], info["max"] = lo, hi
        if annotation is int:
            info["step"] = 1
        else:
            span = (hi or 1) - (lo or 0)
            info["step"] = 0.01 if span <= 1 else 0.05 if span <= 5 else 0.1 if span <= 10 else 1
    else:
        info["type"] = "text"
    return info


def _settings_payload() -> dict:
    return {
        "groups": [
            {
                "id": group,
                "title": title,
                "affects": AFFECTS.get(group, ""),
                "settings": [
                    _field_info(n) for n in config.Settings.model_fields if config.group_of(n) == group
                ],
            }
            for group, title in config.GROUPS.items()
        ]
    }


class SettingsChange(BaseModel):
    changes: dict[str, Any]


@router.get("/settings")
def get_settings() -> dict:
    return _settings_payload()


@router.put("/settings")
def update_settings(body: SettingsChange) -> dict:
    try:
        changed = config.apply_tuning(body.changes)
    except config.TuningError as exc:
        raise HTTPException(422, {"errors": exc.errors}) from exc
    if changed:
        log.info("tuning page changed: %s", ", ".join(f"{n}={getattr(config, n)}" for n in sorted(changed)))
    return _settings_payload()


@router.post("/settings/reset")
def reset_settings() -> dict:
    config.reset_tuning()
    return _settings_payload()


# ── Recordings & re-renders ────────────────────────────────────────────────────


def _render_json(r: Render) -> dict:
    return {
        "id": r.id,
        "recording_id": r.recording_id,
        "status": r.status,
        "message": r.message,
        "settings": json.loads(r.settings_json),
        "timings": json.loads(r.timings_json),
        "clarity": r.clarity,
        "sounds": r.sounds,
        "heard": r.heard,
        "video_url": f"/api/tune/renders/{r.id}/video" if r.status == "done" else None,
        "created_at": r.created_at.isoformat(),
    }


@router.get("/recordings")
def list_recordings() -> list[dict]:
    with session() as s:
        rows = s.exec(
            select(Recording, Challenge).join(Challenge, Challenge.id == Recording.challenge_id)
            .order_by(Recording.id.desc())
        ).all()
        counts = dict(s.exec(select(Render.recording_id, func.count()).group_by(Render.recording_id)).all())
    out = []
    for rec, ch in rows:
        path = Path(rec.input_path) if rec.input_path else None
        if not path or not path.exists() or path.stat().st_size == 0:
            continue
        out.append({
            "id": rec.id,
            "slug": ch.slug,
            "target_text": ch.target_text,
            "masked_text": ch.masked_text,
            "status": rec.status,
            "created_at": rec.created_at.isoformat(),
            "original_video_url": f"/api/recordings/{rec.id}/video" if rec.status == "done" else None,
            "analysed": (work_dir(rec) / pipeline.ANALYSIS_FILE).exists(),
            "renders": counts.get(rec.id, 0),
        })
    return out


@router.get("/recordings/{recording_id}/renders")
def list_renders(recording_id: int) -> list[dict]:
    with session() as s:
        renders = s.exec(select(Render).where(Render.recording_id == recording_id).order_by(Render.id.desc())).all()
    return [_render_json(r) for r in renders]


@router.post("/recordings/{recording_id}/renders")
def create_render(recording_id: int) -> dict:
    with session() as s:
        if not s.get(Recording, recording_id):
            raise HTTPException(404, "Recording not found")
        render = Render(recording_id=recording_id)
        s.add(render)
        s.commit()
        s.refresh(render)
        body = _render_json(render)
    worker.submit(_run_render, body["id"])
    return body


def _run_render(render_id: int) -> None:
    with session() as s:
        render = s.get(Render, render_id)
        rec = s.get(Recording, render.recording_id)
        ch = s.get(Challenge, rec.challenge_id)
        render.status = "processing"
        # Snapshot when the job starts: these are the settings it actually runs with.
        render.settings_json = json.dumps({k: str(v) for k, v in config.changed().items()})
        s.add(render)
        s.commit()
        inp, workdir, masked, target = Path(rec.input_path), work_dir(rec), ch.masked_text, ch.target_text

    out = inp.parent / "renders" / f"{render_id}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    clarity = None
    try:
        res = pipeline.run(inp, masked, target, workdir, out)
        if res.output:
            clarity = scoring.clarity(res.output, target)
    except Exception:
        log.exception("re-render %s failed", render_id)
        res = pipeline.PipelineResult("failed", "Something went wrong: see the API log.")

    with session() as s:
        render = s.get(Render, render_id)
        render.status = res.status
        render.message = res.message
        render.timings_json = json.dumps(res.timings)
        render.output_path = str(res.output or "")
        if clarity:
            render.clarity, render.sounds, render.heard = clarity.score, clarity.sounds, clarity.heard
        s.add(render)
        s.commit()


@router.get("/renders/{render_id}/video")
def render_video(render_id: int) -> FileResponse:
    with session() as s:
        render = s.get(Render, render_id)
    if not render or render.status != "done" or not Path(render.output_path).exists():
        raise HTTPException(404, "Video not ready")
    return FileResponse(render.output_path, media_type="video/mp4")


@router.delete("/renders/{render_id}")
def delete_render(render_id: int) -> dict:
    with session() as s:
        render = s.get(Render, render_id)
        if not render:
            raise HTTPException(404, "Render not found")
        if render.status in ("queued", "processing"):
            raise HTTPException(409, "Wait for it to finish first")
        if render.output_path:
            Path(render.output_path).unlink(missing_ok=True)
        s.delete(render)
        s.commit()
    return {"ok": True}
