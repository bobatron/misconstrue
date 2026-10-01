"""Recording in, misconstrued video out (or a request to try again)."""
from __future__ import annotations

import hashlib
import json
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from app import config
from app.core import aligner, editor, media, phonetics, segments, verify_read
from app.core.splice import plan_splice

log = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    status: str  # "done" | "needs_retake" | "failed"
    message: str = ""
    missing: list[int] = field(default_factory=list)
    output: Path | None = None
    party_output: Path | None = None  # the party-mode version (music + words on the beat)
    timings: dict[str, float] = field(default_factory=dict)  # seconds per step


class _Timer:
    def __init__(self) -> None:
        self.steps: dict[str, float] = {}

    @contextmanager
    def __call__(self, step: str):
        start = time.perf_counter()
        try:
            yield
        finally:
            self.steps[step] = round(time.perf_counter() - start, 3)


def _critical_words(spans, phones) -> set[int]:
    """Indices of the words the splice plan cuts from."""
    return {phones[k].word_index for sp in spans for k in range(sp.s_start, sp.s_end)}


def run(
    video: Path, masked_text: str, target_text: str, workdir: Path, out: Path, force: bool = False,
    prompt_timings: str | list | None = None,
) -> PipelineResult:
    """`force`: after too many retakes, render whatever we can instead of asking again.
    `prompt_timings`: the prompter's record of when each word was on screen (JSON or list). With
    one word per prompt, each word is checked and aligned in its own clip (see segments.py)."""
    timer = _Timer()
    start = time.perf_counter()
    timings = json.loads(prompt_timings) if isinstance(prompt_timings, str) and prompt_timings else prompt_timings or []
    result = _run(video, masked_text, target_text, workdir, out, force, timer, timings)
    result.timings = {**timer.steps, "total": round(time.perf_counter() - start, 3)}
    log.info("%s in %.1fs: %s", result.status, result.timings["total"],
             ", ".join(f"{k} {v:.1f}s" for k, v in timer.steps.items()))
    return result


# ── Analysis cache ─────────────────────────────────────────────────────────────
# Converting, transcribing and aligning a recording are the slow steps, and their results only
# depend on the recording and a few settings. They're saved in the work folder so a re-render
# (tuning page) only redoes the check, plan and render.

ANALYSIS_FILE = "analysis.json"
ANALYSIS_SETTINGS = (
    "FPS", "OUTPUT_HEIGHT", "AUDIO_SR", "WHISPER_MODEL", "MFA_ACOUSTIC_MODEL", "MFA_DICTIONARY", "PRONUNCIATION_DICT",
)


def _analysis_key(video: Path, masked_text: str, timings: list) -> str:
    stat = video.stat()
    parts = [str(video.resolve()), str(stat.st_size), str(stat.st_mtime_ns), masked_text, json.dumps(timings)]
    parts += [str(getattr(config, name)) for name in ANALYSIS_SETTINGS]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


def _normalised(workdir: Path) -> media.Normalised:
    return media.Normalised(workdir / "video.mp4", workdir / "audio16.wav", workdir / "audio48.wav")


def _load_analysis(workdir: Path, key: str) -> dict | None:
    path = workdir / ANALYSIS_FILE
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    norm = _normalised(workdir)
    if data.get("key") != key or not all(p.exists() for p in (norm.video, norm.wav16, norm.wav48)):
        return None
    return data


def _save_analysis(workdir: Path, key: str, heard: list, alignment: aligner.Alignment | None) -> None:
    data = {
        "key": key,
        "heard": [vars(h) for h in heard],
        "alignment": alignment.to_json() if alignment else None,
    }
    (workdir / ANALYSIS_FILE).write_text(json.dumps(data))


def _run(
    video: Path, masked_text: str, target_text: str, workdir: Path, out: Path, force: bool, timer: _Timer,
    timings: list,
) -> PipelineResult:
    key = _analysis_key(video, masked_text, timings)
    cached = _load_analysis(workdir, key)
    alignment: aligner.Alignment | None = None
    if cached:
        norm = _normalised(workdir)
        heard = [verify_read.Heard(**h) for h in cached["heard"]]
        if cached["alignment"]:
            alignment = aligner.Alignment.from_json(cached["alignment"])
        log.info("re-using saved analysis")
    else:
        try:
            with timer("normalise"):
                norm = media.normalise(video, workdir)
        except media.MediaError as exc:
            log.warning("couldn't read recording %s: %s", video, exc)
            if isinstance(exc, media.NoAudioError):
                message = ("We couldn't hear anything: the recording had no sound. Check that this page is allowed "
                           "to use your microphone, then try again.")
            else:
                message = "That recording couldn't be opened. Please record it again."
            return PipelineResult("needs_retake", message)
        words = phonetics.tokenize(masked_text)
        wins = segments.windows(timings, len(words), media.duration(norm.wav16)) if timings else None
        if wins:
            # One word at a time: take out the long pauses, then transcribe and align once.
            heard, alignment, spent = segments.analyse(norm.wav16, masked_text, timings, wins)
            timer.steps.update({k: round(v, 3) for k, v in spent.items()})
            _save_analysis(workdir, key, heard, alignment)
        else:
            with timer("transcribe"):
                heard = verify_read.transcribe(norm.wav16)
            _save_analysis(workdir, key, heard, None)
    log.info("heard: %s", " ".join(h.word for h in heard))
    target = phonetics.sentence_phones(phonetics.tokenize(target_text))

    # Quick check on the transcript alone, using the dictionary plan to decide which words
    # matter. Catches partial readings before the (slow, easily confused) aligner runs.
    masked_phones = phonetics.sentence_phones(phonetics.tokenize(masked_text))
    expected = plan_splice(target, masked_phones)
    expected_critical = _critical_words(expected[0], masked_phones) if expected else set()
    gate = verify_read.check(masked_text, heard, None, expected_critical)
    if not gate.ok and (not force or not heard):
        return PipelineResult("needs_retake", gate.message, gate.missing)

    if alignment is None:
        try:
            with timer("align"):
                alignment = aligner.align(norm.wav16, masked_text)
        except aligner.AlignmentError as exc:
            log.warning("%s", exc)
            return PipelineResult(
                "needs_retake",
                gate.message or "We couldn't follow that recording. Please go through the words again.",
                gate.missing,
            )
        _save_analysis(workdir, key, heard, alignment)

    with timer("plan"):
        plan = plan_splice(target, alignment.phones, alignment.times)
    critical = _critical_words(plan[0], alignment.phones) if plan else set()

    gate = verify_read.check(masked_text, heard, alignment, critical)
    if not gate.ok and not (force and plan):
        return PipelineResult("needs_retake", gate.message, gate.missing)
    if plan is None:
        return PipelineResult("failed", "Some sounds were missing from the recording.")

    with timer("render"):
        editor.render(plan[0], alignment, norm, out, workdir)
    party_out = None
    if config.PARTY_MODE:
        party_out = out.with_name(f"{out.stem}-party{out.suffix}")
        try:
            with timer("party"):
                editor.render_party(plan[0], target, alignment, norm, party_out, workdir)
        except Exception:  # the plain video is what matters; never lose it to a party-mode problem
            log.exception("party-mode render failed")
            party_out = None
    return PipelineResult("done", output=out, party_output=party_out)
