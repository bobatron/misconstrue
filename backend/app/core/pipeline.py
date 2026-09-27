"""Recording in, misconstrued video out (or a request to try again)."""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from app.core import aligner, editor, media, phonetics, verify_read
from app.core.splice import plan_splice

log = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    status: str  # "done" | "needs_retake" | "failed"
    message: str = ""
    missing: list[int] = field(default_factory=list)
    output: Path | None = None
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


def run(video: Path, masked_text: str, target_text: str, workdir: Path, out: Path, force: bool = False) -> PipelineResult:
    """`force`: after too many retakes, render whatever we can instead of asking again."""
    timer = _Timer()
    start = time.perf_counter()
    result = _run(video, masked_text, target_text, workdir, out, force, timer)
    result.timings = {**timer.steps, "total": round(time.perf_counter() - start, 3)}
    log.info("%s in %.1fs: %s", result.status, result.timings["total"],
             ", ".join(f"{k} {v:.1f}s" for k, v in timer.steps.items()))
    return result


def _run(
    video: Path, masked_text: str, target_text: str, workdir: Path, out: Path, force: bool, timer: _Timer
) -> PipelineResult:
    try:
        with timer("normalise"):
            norm = media.normalise(video, workdir)
    except media.MediaError as exc:
        return PipelineResult("needs_retake", f"We couldn't read that recording ({exc}). Please try again.")

    with timer("transcribe"):
        heard = verify_read.transcribe(norm.wav16)
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

    try:
        with timer("align"):
            alignment = aligner.align(norm.wav16, masked_text)
    except aligner.AlignmentError as exc:
        log.warning("%s", exc)
        return PipelineResult("needs_retake", gate.message or "We couldn't follow that recording. Please read the sentence again.", gate.missing)

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
    return PipelineResult("done", output=out)
