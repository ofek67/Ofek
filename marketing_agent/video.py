"""יצירת סרטוני שיווק קצרים (MP4) מטקסט ותמונות.

הסרטון נבנה מ"שקופיות": בכל שקופית יש טקסט מונפש (נכנס בהדרגה מלמטה),
רקע בצבעי גרדיאנט או תמונה עם זום איטי, ומעבר רך בין השקופיות.
ffmpeg מגיע מוכן דרך החבילה imageio-ffmpeg, כך שאין צורך להתקין אותו בנפרד.
"""

from __future__ import annotations

import math
import os
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, features

FORMATS = {
    "vertical": (1080, 1920),  # טיקטוק, רילס, סטוריז, שורטס
    "square": (1080, 1080),  # פיד אינסטגרם/פייסבוק
    "horizontal": (1920, 1080),  # יוטיוב
}

THEMES = {
    "sunset": ((255, 94, 98), (255, 195, 113)),
    "ocean": ((33, 147, 176), (109, 213, 237)),
    "royal": ((65, 41, 90), (47, 7, 67)),
    "fresh": ((17, 153, 142), (56, 239, 125)),
    "dark": ((20, 20, 30), (60, 60, 80)),
    "fire": ((203, 45, 62), (239, 71, 58)),
    "gold": ((40, 30, 10), (191, 149, 63)),
}

FONT_CANDIDATES = [
    os.environ.get("VIDEO_FONT", ""),
    # Windows
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    # macOS
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    # Linux
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansHebrew-Bold.ttf",
]

FPS = 30
TRANSITION = 0.5  # שניות של מעבר בין שקופיות

_HAS_RAQM = features.check("raqm")


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if path and Path(path).exists():
            engine = ImageFont.Layout.RAQM if _HAS_RAQM else ImageFont.Layout.BASIC
            return ImageFont.truetype(path, size, layout_engine=engine)
    return ImageFont.load_default(size)


def _has_hebrew(text: str) -> bool:
    return any("\u0590" <= ch <= "\u05ff" for ch in text)


def _visual(text: str) -> str:
    """בלי libraqm, Pillow מצייר עברית הפוך - מסדרים את האותיות ידנית."""
    if _HAS_RAQM or not _has_hebrew(text):
        return text
    from bidi.algorithm import get_display

    return get_display(text)


def _text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    kwargs = {"direction": "rtl"} if _HAS_RAQM and _has_hebrew(text) else {}
    box = draw.textbbox((0, 0), _visual(text), font=font, **kwargs)
    return box[2] - box[0], box[3] - box[1]


def _wrap(draw, text: str, font, max_width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        current = ""
        for word in words:
            test = f"{current} {word}".strip()
            if _text_size(draw, test, font)[0] <= max_width or not current:
                current = test
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def _gradient(size: tuple[int, int], c1, c2) -> Image.Image:
    w, h = size
    base = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(h - 1, 1)
        base.putpixel((0, y), tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3)))
    return base.resize((w, h))


def _cover(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    w, h = size
    scale = max(w / img.width, h / img.height)
    img = img.resize((math.ceil(img.width * scale), math.ceil(img.height * scale)), Image.LANCZOS)
    left, top = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((left, top, left + w, top + h))


def _text_layer(size, text: str, text_color, font_size: int) -> Image.Image:
    w, h = size
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    if not text.strip():
        return layer
    draw = ImageDraw.Draw(layer)
    font = _font(font_size)
    lines = _wrap(draw, text, font, int(w * 0.84))
    line_h = int(font_size * 1.35)
    total_h = line_h * len(lines)
    y = (h - total_h) // 2

    # כרטיס חצי-שקוף מאחורי הטקסט כדי שיהיה קריא על כל רקע
    widest = max((_text_size(draw, ln, font)[0] for ln in lines), default=0)
    pad = int(font_size * 0.6)
    card = (
        (w - widest) // 2 - pad,
        y - pad,
        (w + widest) // 2 + pad,
        y + total_h + pad // 2,
    )
    draw.rounded_rectangle(card, radius=pad, fill=(0, 0, 0, 90))

    for line in lines:
        rtl = _HAS_RAQM and _has_hebrew(line)
        kwargs = {"direction": "rtl"} if rtl else {}
        tw, _ = _text_size(draw, line, font)
        x = (w - tw) // 2
        shown = _visual(line)
        draw.text((x + 4, y + 4), shown, font=font, fill=(0, 0, 0, 140), **kwargs)
        draw.text((x, y), shown, font=font, fill=text_color, **kwargs)
        y += line_h
    return layer


def _ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def make_video(
    slides: list[str],
    output_path: str,
    video_format: str = "vertical",
    theme: str = "sunset",
    seconds_per_slide: float = 3.0,
    images: list[str] | None = None,
    text_color: str = "#FFFFFF",
    music_path: str | None = None,
) -> str:
    """בונה סרטון MP4 ומחזיר את הנתיב שלו."""
    import imageio_ffmpeg

    if not slides:
        raise ValueError("צריך לפחות שקופית אחת")
    size = FORMATS.get(video_format, FORMATS["vertical"])
    w, h = size
    c1, c2 = THEMES.get(theme, THEMES["sunset"])
    color = tuple(int(text_color.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4)) + (255,)
    font_size = int(min(w, h) * (0.085 if video_format != "horizontal" else 0.075))
    images = images or []

    # הכנת רקע ושכבת טקסט לכל שקופית מראש
    prepared = []
    for i, text in enumerate(slides):
        img_path = images[i] if i < len(images) and images[i] else None
        big = (int(w * 1.12), int(h * 1.12))
        if img_path and Path(img_path).exists() and not text.strip():
            # שקופית בלי טקסט: מציגים את כל התמונה (למשל פלייר) על רקע מטושטש שלה
            src = Image.open(img_path).convert("RGB")
            bg = _cover(src, big).filter(ImageFilter.GaussianBlur(40))
            bg = Image.blend(bg, Image.new("RGB", big, (0, 0, 0)), 0.45)
            scale = min(w * 0.96 / src.width, h * 0.96 / src.height)
            fg = src.resize((int(src.width * scale), int(src.height * scale)), Image.LANCZOS)
            bg.paste(fg, ((big[0] - fg.width) // 2, (big[1] - fg.height) // 2))
        elif img_path and Path(img_path).exists():
            bg = Image.open(img_path).convert("RGB")
            # מכינים תמונה קצת יותר גדולה בשביל אפקט זום
            bg = _cover(bg, big)
            bg = Image.blend(bg, Image.new("RGB", bg.size, (0, 0, 0)), 0.25)
        else:
            # מסובבים את הגרדיאנט בין שקופיות כדי ליצור גיוון
            a, b = (c1, c2) if i % 2 == 0 else (c2, c1)
            bg = _gradient(big, a, b)
            glow = Image.new("RGBA", bg.size, (0, 0, 0, 0))
            gd = ImageDraw.Draw(glow)
            r = int(min(w, h) * 0.45)
            cx, cy = (int(bg.width * 0.75), int(bg.height * 0.25)) if i % 2 == 0 else (int(bg.width * 0.25), int(bg.height * 0.75))
            gd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255, 50))
            glow = glow.filter(ImageFilter.GaussianBlur(r // 3))
            bg = Image.alpha_composite(bg.convert("RGBA"), glow).convert("RGB")
        prepared.append((bg, _text_layer(size, text, color, font_size)))

    frames_per_slide = int(seconds_per_slide * FPS)
    trans_frames = int(TRANSITION * FPS)

    def render(idx: int, f: int) -> Image.Image:
        bg, txt = prepared[idx]
        t = f / max(frames_per_slide - 1, 1)
        # Ken Burns: זום איטי פנימה
        zoom = 1.12 - 0.10 * t
        cw, ch = int(w * zoom), int(h * zoom)
        left, top = (bg.width - cw) // 2, (bg.height - ch) // 2
        frame = bg.crop((left, top, left + cw, top + ch)).resize(size, Image.BILINEAR).convert("RGBA")
        # הטקסט עולה מלמטה ומופיע בהדרגה
        p = _ease(f / max(int(0.6 * FPS), 1))
        offset = int((1 - p) * h * 0.05)
        moved = Image.new("RGBA", size, (0, 0, 0, 0))
        moved.paste(txt, (0, offset))
        if p < 1:
            alpha = moved.getchannel("A").point(lambda a: int(a * p))
            moved.putalpha(alpha)
        return Image.alpha_composite(frame, moved).convert("RGB")

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    total_seconds = seconds_per_slide * len(slides)
    cmd = [
        imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(FPS), "-i", "-",
    ]
    if music_path and Path(music_path).exists():
        cmd += ["-i", music_path, "-af", f"afade=t=out:st={max(total_seconds - 1.5, 0)}:d=1.5", "-shortest"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "20", "-movflags", "+faststart"]
    if music_path and Path(music_path).exists():
        cmd += ["-c:a", "aac", "-b:a", "192k"]
    cmd.append(str(out))

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    assert proc.stdin is not None
    try:
        for idx in range(len(slides)):
            for f in range(frames_per_slide):
                frame = render(idx, f)
                # מעבר רך (crossfade) לשקופית הבאה בסוף כל שקופית
                remaining = frames_per_slide - f
                if idx + 1 < len(slides) and remaining <= trans_frames:
                    k = 1 - (remaining - 1) / trans_frames
                    frame = Image.blend(frame, render(idx + 1, 0), k * 0.999)
                proc.stdin.write(frame.tobytes())
    finally:
        proc.stdin.close()
        proc.wait()
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg נכשל ביצירת הסרטון")
    return str(out)


if __name__ == "__main__":
    path = make_video(
        ["ברוכים הבאים!", "המוצר החדש שלנו כבר כאן", "50% הנחה השבוע בלבד", "הזמינו עכשיו בקישור בביו"],
        "output/videos/demo.mp4",
    )
    print("נוצר:", path)
