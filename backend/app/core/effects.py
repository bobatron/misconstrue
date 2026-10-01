"""Party-mode video effects, timed to the beat: zoom punch, wobble, a colour per word, a flash on
each bar, big word captions, and intro/end cards. Drawn frame by frame with Pillow (this ffmpeg
build has no text filter, and it keeps everything in one place)."""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONTS = [
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Debian/Ubuntu: fonts-dejavu-core
]
# One tint per word, cycling: pink, cyan, yellow, purple, green, orange.
TINTS = [(255, 64, 160), (0, 220, 255), (255, 230, 0), (170, 90, 255), (60, 255, 120), (255, 140, 0)]

PUNCH = 0.09  # extra zoom right on the beat
PUNCH_DECAY_S = 0.14
WOBBLE_DEG = 2.5
BASE_ZOOM = 1.07  # always zoomed in a little so rotated corners never show
TINT_ALPHA = 0.16
FLASH_ALPHA = 0.35
FLASH_DECAY_S = 0.09


@lru_cache(maxsize=8)
def _font(size: int) -> ImageFont.ImageFont:
    for path in FONTS:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


@lru_cache(maxsize=64)
def _text_image(text: str, size: int, colour: tuple[int, int, int]) -> Image.Image:
    """Bold text with a thick dark outline, on a transparent background."""
    font = _font(size)
    stroke = max(2, size // 12)
    box = ImageDraw.Draw(Image.new("RGBA", (1, 1))).textbbox((0, 0), text, font=font, stroke_width=stroke)
    img = Image.new("RGBA", (box[2] - box[0] + 4, box[3] - box[1] + 4), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((2 - box[0], 2 - box[1]), text, font=font, fill=colour + (255,),
                             stroke_width=stroke, stroke_fill=(20, 10, 30, 255))
    return img


def _fit_text(text: str, width: int, height: int, colour: tuple[int, int, int], max_frac: float) -> Image.Image:
    """The biggest size of `text` that fits within max_frac of the frame width."""
    size = int(height * 0.13)
    img = _text_image(text, size, colour)
    while img.width > width * max_frac and size > 12:
        size = int(size * 0.9)
        img = _text_image(text, size, colour)
    return img


def _paste_centred(frame: Image.Image, img: Image.Image, cy: float, scale: float = 1.0) -> None:
    if scale != 1.0:
        img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.BILINEAR)
    x = (frame.width - img.width) // 2
    y = int(cy - img.height / 2)
    frame.paste(img, (x, max(0, y)), img)  # the caption's own transparency is the mask


def _affine(w: int, h: int, zoom: float, angle_deg: float) -> tuple[float, ...]:
    """Pillow's AFFINE maps each output pixel back to an input pixel: rotate about the centre and
    zoom in, in one resampling step (rotating, cropping and resizing separately was 3x slower)."""
    a = math.radians(angle_deg)
    cos, sin = math.cos(a) / zoom, math.sin(a) / zoom
    cx, cy = w / 2, h / 2
    return (cos, sin, cx - cos * cx - sin * cy, -sin, cos, cy + sin * cx - cos * cy)


def apply(
    frames: np.ndarray,
    fps: float,
    bpm: float,
    beats: int,
    words: list[tuple[str, float, float]],  # (caption text, start_s, end_s) for each word on its beat
    captions: bool = True,
    motion: bool = True,
) -> np.ndarray:
    """Return a new frames array with the effects drawn on. Frames are independent, so they're drawn
    on several threads (Pillow releases the interpreter lock while transforming images)."""
    from concurrent.futures import ThreadPoolExecutor

    n = len(frames)
    out = np.empty_like(frames)
    workers = 4
    chunks = [range(i, min(n, i + (n + workers - 1) // workers)) for i in range(0, n, max(1, (n + workers - 1) // workers))]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(lambda r: _draw(frames, out, r, fps, bpm, words, captions, motion), chunks))
    return out


def _draw(frames: np.ndarray, out: np.ndarray, frame_range: range, fps: float, bpm: float,
          words: list[tuple[str, float, float]], captions: bool, motion: bool) -> None:
    beat = 60.0 / bpm
    _, h, w, _ = frames.shape
    first_word = words[0][1] if words else 0.0
    last_end = words[-1][2] if words else 0.0
    word_starts = [s for _, s, _ in words]

    for f in frame_range:
        t = f / fps
        since_beat = t % beat
        beat_no = int(t // beat)
        i = int(np.searchsorted(word_starts, t, side="right")) - 1  # the word that's "on" now
        speaking = 0 <= i < len(words) and t < (words[i + 1][1] if i + 1 < len(words) else last_end + beat)

        frame = frames[f]
        if motion:
            # Colour for the current word, and a white flash on each bar's first beat, blended in one go.
            colour = np.zeros(3, dtype=np.float32)
            alpha = 0.0
            if speaking:
                colour, alpha = np.array(TINTS[i % len(TINTS)], dtype=np.float32), TINT_ALPHA
            if beat_no % 4 == 0 and since_beat < 4 * FLASH_DECAY_S:
                flash = FLASH_ALPHA * math.exp(-since_beat / FLASH_DECAY_S)
                colour = (colour * alpha + 255 * flash) / max(alpha + flash, 1e-6)
                alpha = min(1.0, alpha + flash)
            if alpha:
                frame = (frame.astype(np.float32) * (1 - alpha) + colour * alpha).astype(np.uint8)
        img = Image.fromarray(frame)
        if motion:
            zoom = BASE_ZOOM + PUNCH * math.exp(-since_beat / PUNCH_DECAY_S)
            angle = WOBBLE_DEG * math.sin(2 * math.pi * t / (2 * beat))
            img = img.transform((w, h), Image.AFFINE, _affine(w, h, zoom, angle), resample=Image.BILINEAR)

        if captions:
            if speaking:
                text, start, _ = words[i]
                pop = 1.0 + 0.25 * math.exp(-(t - start) / 0.08)  # pops in, settles
                _paste_centred(img, _fit_text(text.upper(), w, h, (255, 255, 255), 0.9), h * 0.78, pop)
            elif t < first_word:
                _paste_centred(img, _fit_text("misconstrue", w, h, TINTS[0], 0.8), h * 0.42)
                _paste_centred(img, _fit_text("presents…", w, h, (255, 255, 255), 0.5), h * 0.55)
            elif t >= last_end + beat:
                pop = 1.0 + 0.3 * math.exp(-(t - last_end - beat) / 0.1)
                _paste_centred(img, _fit_text("misconstrued!", w, h, TINTS[2], 0.9), h * 0.5, pop)

        out[f] = np.asarray(img)
