"""Command-line access to the pipeline, for testing without the web app.

  python scripts/cli.py mask "hello sir this is not what I originally said"
  python scripts/cli.py synth "Some masked sentence." clip.mp4      # fake recording via macOS `say`
  python scripts/cli.py run clip.mp4 --masked "..." --target "..." -o out.mp4
"""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core import masker, pipeline  # noqa: E402


def cmd_mask(args: argparse.Namespace) -> None:
    r = masker.mask(args.text, use_llm=not args.no_llm, seed=args.seed)
    print(f"Masked ({r.source}): {r.masked_text}")
    print(f"Cuts: {len(r.spans)}   cost: {r.cost:.2f}")


def cmd_synth(args: argparse.Namespace) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        aiff = Path(tmp) / "speech.aiff"
        subprocess.run(["say", "-v", args.voice, "-r", str(args.rate), "-o", str(aiff), args.text], check=True)
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=size=640x480:rate=30",
             "-i", str(aiff), "-af", "adelay=500:all=1,apad=pad_dur=0.5", "-shortest",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", args.out],
            check=True,
        )
    print(f"Wrote {args.out}")


def cmd_run(args: argparse.Namespace) -> None:
    out = Path(args.output).resolve()
    workdir = Path(tempfile.mkdtemp(prefix="misconstrue_"))
    res = pipeline.run(Path(args.video), args.masked, args.target, workdir, out)
    print(f"Status: {res.status}")
    if res.message:
        print(f"Message: {res.message}")
    if res.output:
        print(f"Output: {res.output}")
    print(f"Work files: {workdir}")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(required=True)

    m = sub.add_parser("mask", help="make a masked sentence")
    m.add_argument("text")
    m.add_argument("--no-llm", action="store_true")
    m.add_argument("--seed", type=int)
    m.set_defaults(func=cmd_mask)

    s = sub.add_parser("synth", help="make a fake recording with macOS text-to-speech")
    s.add_argument("text")
    s.add_argument("out")
    s.add_argument("--voice", default="Samantha")
    s.add_argument("--rate", type=int, default=170)
    s.set_defaults(func=cmd_synth)

    r = sub.add_parser("run", help="turn a recording into the misconstrued video")
    r.add_argument("video")
    r.add_argument("--masked", required=True)
    r.add_argument("--target", required=True)
    r.add_argument("-o", "--output", default="misconstrued.mp4")
    r.set_defaults(func=cmd_run)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
