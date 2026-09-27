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


def _critical_words(spans, phones) -> set[int]:
    """Indices of the words the splice plan cuts from."""
    return {phones[k].word_index for sp in spans for k in range(sp.s_start, sp.s_end)}


def run(video: Path, masked_text: str, target_text: str, workdir: Path, out: Path, force: bool = False) -> PipelineResult:
    """`force`: after too many retakes, render whatever we can instead of asking again."""
    try:
        norm = media.normalise(video, workdir)
    except media.MediaError as exc:
        return PipelineResult("needs_retake", f"We couldn't read that recording ({exc}). Please try again.")

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
        alignment = aligner.align(norm.wav16, masked_text)
    except aligner.AlignmentError as exc:
        log.warning("%s", exc)
        return PipelineResult("needs_retake", gate.message or "We couldn't follow that recording. Please read the sentence again.", gate.missing)

    plan = plan_splice(target, alignment.phones, alignment.times)
    critical = _critical_words(plan[0], alignment.phones) if plan else set()

    gate = verify_read.check(masked_text, heard, alignment, critical)
    if not gate.ok and not (force and plan):
        return PipelineResult("needs_retake", gate.message, gate.missing)
    if plan is None:
        return PipelineResult("failed", "Some sounds were missing from the recording.")

    editor.render(plan[0], alignment, norm, out, workdir)
    return PipelineResult("done", output=out)
