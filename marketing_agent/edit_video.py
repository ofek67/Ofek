"""עריכת סרטון קיים (למשל סרטון שצילמת בטלפון): כיתובים, פס מיתוג וכרטיס סיום.

- מוסיף כיתובים בעברית בזמנים שבוחרים, עם כניסה ויציאה רכות.
- אפשר להוסיף פס מלא ברוחב המסך כדי לכסות משהו (סימן מים או טלפון ישן).
- סרטוני אייפון ב-HDR מומרים לצבעים רגילים, כדי שלא ייראו דהויים באינסטגרם ובווטסאפ.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from video import _font, _has_hebrew, _HAS_RAQM, _text_size, _visual, _wrap

POSITIONS = {"top": 0.08, "upper": 0.25, "center": 0.5, "lower": 0.72, "bottom": 0.86}


def _ffmpeg() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def probe(path: str) -> dict:
    out = subprocess.run([_ffmpeg(), "-hide_banner", "-i", path], capture_output=True, text=True).stderr
    dur = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out)
    size = re.search(r"Video:.*?(\d{3,5})x(\d{3,5})", out)
    rotate = re.search(r"rotation of (-?[\d.]+)", out)
    w, h = (int(size.group(1)), int(size.group(2))) if size else (1080, 1920)
    if rotate and abs(float(rotate.group(1))) in (90.0, 270.0):
        w, h = h, w
    return {
        "duration": int(dur.group(1)) * 3600 + int(dur.group(2)) * 60 + float(dur.group(3)) if dur else 0.0,
        "width": w,
        "height": h,
        "hdr": "arib-std-b67" in out or "smpte2084" in out,
        "hlg": "arib-std-b67" in out,
        "audio": "Audio:" in out,
    }


def _hex(color: str, alpha: int = 255) -> tuple:
    color = color.lstrip("#")
    return tuple(int(color[i : i + 2], 16) for i in (0, 2, 4)) + (alpha,)


def _draw_lines(draw, lines, font, font_size, w, y, color):
    line_h = int(font_size * 1.3)
    for line in lines:
        kwargs = {"direction": "rtl"} if _HAS_RAQM and _has_hebrew(line) else {}
        tw, _ = _text_size(draw, line, font)
        x = (w - tw) // 2
        shown = _visual(line)
        draw.text((x + 3, y + 3), shown, font=font, fill=(0, 0, 0, 160), **kwargs)
        draw.text((x, y), shown, font=font, fill=color, **kwargs)
        y += line_h


def caption_png(size, text, position="lower", style="card", color="#FFFFFF", bg="#000000", scale=1.0, pad=1.0) -> Image.Image:
    """שכבה שקופה בגודל הסרטון עם כיתוב. style: card (כרטיס מעוגל) / band (פס מלא) / plain."""
    w, h = size
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    font_size = int(min(w, h) * 0.07 * scale)
    font = _font(font_size)
    lines = _wrap(draw, text, font, int(w * 0.86))
    line_h = int(font_size * 1.3)
    total = line_h * len(lines)
    center = POSITIONS.get(position, position if isinstance(position, float) else 0.72)
    y = int(h * float(center) - total / 2)
    pad = int(font_size * 0.45 * pad)
    if style == "band":
        draw.rectangle((0, y - pad, w, y + total + pad // 2), fill=_hex(bg, 250))
    elif style == "card":
        widest = max(_text_size(draw, ln, font)[0] for ln in lines)
        draw.rounded_rectangle(
            ((w - widest) // 2 - pad * 2, y - pad, (w + widest) // 2 + pad * 2, y + total + pad // 2),
            radius=pad * 2,
            fill=_hex(bg, 170),
        )
    _draw_lines(draw, lines, font, font_size, w, y, _hex(color))
    return layer


def end_card_png(size, title, subtitle="", phone="", accent="#FFD23F") -> Image.Image:
    w, h = size
    layer = Image.new("RGBA", size, (10, 5, 25, 242))
    draw = ImageDraw.Draw(layer)
    y = int(h * 0.30)
    for text, scale, color in ((title, 1.15, "#FFFFFF"), (subtitle, 0.75, "#E0D7FF"), (phone, 1.35, accent)):
        if not text:
            continue
        fs = int(min(w, h) * 0.075 * scale)
        font = _font(fs)
        lines = _wrap(draw, text, font, int(w * 0.86))
        _draw_lines(draw, lines, font, fs, w, y, _hex(color))
        y += int(fs * 1.3) * len(lines) + int(fs * 0.9)
    return layer


def edit_video(
    input_path: str,
    output_path: str,
    captions: list[dict] | None = None,
    end_card: dict | None = None,
    trim_start: float = 0.0,
    trim_end: float | None = None,
    keep_audio: bool = True,
    music_path: str | None = None,
) -> str:
    """captions: [{text, start, end, position, style, color, bg, scale}]
    end_card: {title, subtitle, phone, seconds}"""
    info = probe(input_path)
    w, h = info["width"], info["height"]
    end = min(trim_end or info["duration"], info["duration"])
    duration = max(end - trim_start, 0.5)

    tmp = Path(tempfile.mkdtemp())
    layers: list[tuple[str, float, float]] = []
    for i, cap in enumerate(captions or []):
        png = tmp / f"cap{i}.png"
        caption_png(
            (w, h), cap["text"], cap.get("position", "lower"), cap.get("style", "card"),
            cap.get("color", "#FFFFFF"), cap.get("bg", "#000000"), float(cap.get("scale", 1.0)), float(cap.get("pad", 1.0)),
        ).save(png)
        s = max(0.0, float(cap.get("start", 0)))
        e = min(float(cap.get("end", duration)), duration)
        if e > s:
            layers.append((str(png), s, e))
    if end_card:
        secs = min(float(end_card.get("seconds", 3.5)), duration)
        png = tmp / "end.png"
        end_card_png((w, h), end_card.get("title", ""), end_card.get("subtitle", ""), end_card.get("phone", "")).save(png)
        layers.append((str(png), duration - secs, duration))

    cmd = [_ffmpeg(), "-y", "-loglevel", "error", "-ss", str(trim_start), "-t", str(duration), "-i", input_path]
    for png, s, e in layers:
        cmd += ["-loop", "1", "-t", f"{e - s:.3f}", "-i", png]
    music_idx = None
    if music_path and Path(music_path).exists():
        music_idx = len(layers) + 1
        cmd += ["-i", music_path]

    if info["hdr"]:
        tin = "arib-std-b67" if info["hlg"] else "smpte2084"
        base = (
            f"[0:v]zscale=tin={tin}:min=bt2020nc:pin=bt2020:rin=tv:t=linear:npl=203,format=gbrpf32le,"
            "zscale=p=bt709,tonemap=tonemap=mobius:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p"
        )
    else:
        base = "[0:v]format=yuv420p"
    parts = [f"{base},setsar=1[v0]"]
    last = "v0"
    for i, (_, s, e) in enumerate(layers, start=1):
        d = e - s
        fade = min(0.3, d / 3)
        parts.append(
            f"[{i}:v]format=rgba,fade=t=in:st=0:d={fade:.2f}:alpha=1,"
            f"fade=t=out:st={d - fade:.2f}:d={fade:.2f}:alpha=1,setpts=PTS-STARTPTS+{s:.3f}/TB[o{i}]"
        )
        parts.append(f"[{last}][o{i}]overlay=0:0:eof_action=pass:enable='between(t,{s:.3f},{e:.3f})'[v{i}]")
        last = f"v{i}"

    audio_map: list[str] = []
    if music_idx is not None:
        fade_st = max(duration - 1.5, 0)
        if keep_audio and info["audio"]:
            parts.append(f"[0:a]volume=0.35[a0];[{music_idx}:a]volume=0.9,afade=t=out:st={fade_st}:d=1.5[a1];"
                         "[a0][a1]amix=inputs=2:duration=first[aout]")
        else:
            parts.append(f"[{music_idx}:a]afade=t=out:st={fade_st}:d=1.5[aout]")
        audio_map = ["-map", "[aout]"]
    elif keep_audio and info["audio"]:
        audio_map = ["-map", "0:a"]

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd += ["-filter_complex", ";".join(parts), "-map", f"[{last}]", *audio_map]
    cmd += ["-t", f"{duration:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg נכשל: {result.stderr[-800:]}")
    return str(out)
