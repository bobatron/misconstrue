"""Recording in, misconstrued video out (or a request to try again)."""
from __future__ import annotations

import logging
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


def run(video: Path, masked_text: str, target_text: str, workdir: Path, out: Path) -> PipelineResult:
    try:
        norm = media.normalise(video, workdir)
    except media.MediaError as exc:
        return PipelineResult("needs_retake", f"We couldn't read that recording ({exc}). Please try again.")

    heard = verify_read.transcribe(norm.wav16)
    log.info("heard: %s", " ".join(h.word for h in heard))
    if not heard:
        gate = verify_read.check(masked_text, heard, None, set())
        return PipelineResult("needs_retake", gate.message, gate.missing)

    try:
        alignment = aligner.align(norm.wav16, masked_text)
    except aligner.AlignmentError as exc:
        log.warning("%s", exc)
        return PipelineResult("needs_retake", "We couldn't follow that recording. Please read the sentence again.")

    target = phonetics.sentence_phones(phonetics.tokenize(target_text))
    plan = plan_splice(target, alignment.phones, alignment.times)
    critical = {alignment.phones[k].word_index for sp in plan[0] for k in range(sp.s_start, sp.s_end)} if plan else set()

    gate = verify_read.check(masked_text, heard, alignment, critical)
    if not gate.ok:
        return PipelineResult("needs_retake", gate.message, gate.missing)
    if plan is None:
        return PipelineResult("failed", "Some sounds were missing from the recording.")

    editor.render(plan[0], alignment, norm, out, workdir)
    return PipelineResult("done", output=out)
