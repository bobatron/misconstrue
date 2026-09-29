"""ffmpeg helpers: normalise uploads, read frames, write the final video."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app import config


class MediaError(RuntimeError):
    pass


class NoAudioError(MediaError):
    """The upload has no sound track (microphone blocked or missing)."""


def run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise MediaError(proc.stderr[-2000:])


@dataclass
class Normalised:
    video: Path  # constant FPS, OUTPUT_HEIGHT tall, no audio
    wav16: Path  # mono 16 kHz for speech models
    wav48: Path  # mono 48 kHz for output audio


def stream_types(path: Path) -> set[str]:
    """Kinds of stream in the file ("video", "audio"); MediaError if it can't be read at all."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    streams = json.loads(out.stdout or "{}").get("streams") or []
    if out.returncode != 0 or not streams:
        raise MediaError(f"Unreadable recording: {out.stderr.strip()[:300]}")
    return {s.get("codec_type") for s in streams}


def duration(path: Path) -> float:
    """Length of a media file in seconds."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    return float(out.stdout.strip() or 0)


def normalise(src: Path, workdir: Path) -> Normalised:
    workdir.mkdir(parents=True, exist_ok=True)
    kinds = stream_types(src)
    if "audio" not in kinds:
        raise NoAudioError("The recording has no audio track")
    if "video" not in kinds:
        raise MediaError("The recording has no video track")
    n = Normalised(workdir / "video.mp4", workdir / "audio16.wav", workdir / "audio48.wav")
    base = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src)]
    run(base + ["-an", "-vf", f"fps={config.FPS},scale=-2:{config.OUTPUT_HEIGHT},format=yuv420p",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", str(n.video)])
    run(base + ["-vn", "-ac", "1", "-ar", "16000", str(n.wav16)])
    run(base + ["-vn", "-ac", "1", "-ar", str(config.AUDIO_SR), str(n.wav48)])
    return n


def read_frames(video: Path) -> np.ndarray:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
         "-of", "json", str(video)],
        capture_output=True, text=True,
    )
    stream = json.loads(probe.stdout)["streams"][0]
    w, h = stream["width"], stream["height"]
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3)


def watermark_png(path: Path, width: int) -> Path:
    from PIL import Image, ImageDraw, ImageFont

    text = "misconstrued"
    size = max(14, width // 28)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", size)
    except OSError:
        font = ImageFont.load_default()
    box = ImageDraw.Draw(Image.new("RGBA", (1, 1))).textbbox((0, 0), text, font=font)
    img = Image.new("RGBA", (box[2] + 12, box[3] + 10), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.text((7, 6), text, font=font, fill=(0, 0, 0, 120))
    draw.text((6, 5), text, font=font, fill=(255, 255, 255, 190))
    img.save(path)
    return path


def write_video(frames: np.ndarray, audio_wav: Path, out: Path, workdir: Path) -> None:
    n, h, w, _ = frames.shape
    mark = watermark_png(workdir / "watermark.png", w)
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(config.FPS), "-i", "-",
        "-i", str(audio_wav), "-i", str(mark),
        "-filter_complex", "[0:v][2:v]overlay=W-w-10:H-h-10,format=yuv420p[v]",
        "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-shortest", str(out),
    ]
    proc = subprocess.run(cmd, input=frames.tobytes(), capture_output=True)
    if proc.returncode != 0:
        raise MediaError(proc.stderr.decode()[-2000:])
