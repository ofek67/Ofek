"""הכלים שהסוכן יכול להפעיל: סרטונים, פוסטים, רשימת לקוחות פוטנציאליים וקבצים.

כל הקבצים נשמרים רק בתוך התיקייה output/ - הסוכן לא יכול לכתוב לשום מקום אחר במחשב.
"""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path

from video import FORMATS, THEMES, make_video

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
PROFILE_PATH = BASE_DIR / "business_profile.md"
LEADS_PATH = OUTPUT_DIR / "leads.csv"

LEAD_FIELDS = [
    "date_found",
    "name",
    "business_type",
    "city",
    "website",
    "public_contact",
    "source_url",
    "why_good_fit",
    "suggested_message",
    "status",
]


def _safe_name(name: str, default_ext: str) -> str:
    """שם קובץ בטוח - בלי תיקיות ובלי תווים מסוכנים."""
    name = Path(name or "").name
    name = re.sub(r"[^\w֐-׿.\- ]", "_", name).strip(" .") or "file"
    if not Path(name).suffix:
        name += default_ext
    return name


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _input_file(path: str) -> str | None:
    """קבצי קלט (תמונות/מוזיקה) נקראים רק מתוך התיקייה assets/ או output/."""
    if not path:
        return None
    for root in (BASE_DIR / "assets", OUTPUT_DIR):
        candidate = (root / path).resolve()
        if candidate.is_relative_to(root.resolve()) and candidate.exists():
            return str(candidate)
    return None


# ---------- הגדרות הכלים (מה Claude רואה) ----------

TOOL_DEFINITIONS = [
    {
        "name": "create_video",
        "description": (
            "יוצר סרטון שיווקי קצר (MP4) עם טקסט מונפש, רקע צבעוני או תמונות, ומעברים. "
            "כל פריט ב-slides הוא שקופית אחת עם משפט קצר (עד ~10 מילים). "
            "מבנה מומלץ: פתיח שתופס תשומת לב (hook), יתרונות, הצעה, וקריאה לפעולה בסוף."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "slides": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "הטקסט של כל שקופית, לפי הסדר. 3-8 שקופיות.",
                },
                "file_name": {"type": "string", "description": "שם קצר לקובץ, באנגלית, בלי סיומת."},
                "video_format": {
                    "type": "string",
                    "enum": list(FORMATS),
                    "description": "vertical לטיקטוק/רילס/סטוריז, square לפיד, horizontal ליוטיוב.",
                },
                "theme": {"type": "string", "enum": list(THEMES), "description": "ערכת הצבעים של הרקע."},
                "seconds_per_slide": {"type": "number", "description": "כמה שניות כל שקופית (2-5)."},
                "images": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "אופציונלי: שמות קבצי תמונות מתוך התיקייה assets/, אחת לכל שקופית (ריק = רקע צבעוני).",
                },
                "music": {"type": "string", "description": "אופציונלי: שם קובץ מוזיקה (mp3) מתוך assets/."},
            },
            "required": ["slides", "file_name"],
        },
    },
    {
        "name": "save_post",
        "description": "שומר פוסט מוכן לפרסום (טקסט + האשטגים) כקובץ, כדי שהמשתמש יעתיק ויפרסם.",
        "input_schema": {
            "type": "object",
            "properties": {
                "platform": {
                    "type": "string",
                    "description": "instagram / facebook / tiktok / linkedin / whatsapp / other",
                },
                "title": {"type": "string", "description": "כותרת פנימית קצרה לפוסט."},
                "content": {"type": "string", "description": "הטקסט המלא של הפוסט, כולל אימוג'ים והאשטגים."},
                "image_or_video_idea": {"type": "string", "description": "רעיון לתמונה או לסרטון שילוו את הפוסט."},
            },
            "required": ["platform", "title", "content"],
        },
    },
    {
        "name": "save_leads",
        "description": (
            "מוסיף לקוחות פוטנציאליים לקובץ output/leads.csv (נפתח באקסל). "
            "רק עסקים או אנשים שפרסמו את פרטי הקשר שלהם בפומבי לצורך עסקי, עם קישור למקור."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "leads": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "business_type": {"type": "string"},
                            "city": {"type": "string"},
                            "website": {"type": "string"},
                            "public_contact": {
                                "type": "string",
                                "description": "פרטי קשר עסקיים שפורסמו בפומבי (טלפון/מייל/עמוד). ריק אם אין.",
                            },
                            "source_url": {"type": "string", "description": "הקישור שבו נמצא המידע."},
                            "why_good_fit": {"type": "string", "description": "למה הוא לקוח מתאים."},
                            "suggested_message": {"type": "string", "description": "הודעת פנייה אישית ומנומסת."},
                        },
                        "required": ["name", "source_url", "why_good_fit"],
                    },
                }
            },
            "required": ["leads"],
        },
    },
    {
        "name": "read_leads",
        "description": "קורא את רשימת הלקוחות הפוטנציאליים שכבר נשמרו, כדי לא לשמור כפילויות.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "save_file",
        "description": (
            "שומר קובץ טקסט בתיקייה output/ - למשל תסריט לסרטון, פרומפטים לכלי וידאו AI "
            "(Runway, Sora, Veo, Kling), לוח תוכן שבועי או תוכנית שיווק."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_name": {"type": "string", "description": "שם הקובץ, למשל video-prompts.md"},
                "content": {"type": "string"},
            },
            "required": ["file_name", "content"],
        },
    },
    {
        "name": "read_business_profile",
        "description": "קורא את פרופיל העסק (מה מוכרים, למי, סגנון, מחירים). כדאי לקרוא לפני כל משימה שיווקית.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "update_business_profile",
        "description": "מעדכן את פרופיל העסק כשהמשתמש מספר פרטים חדשים על העסק. שולחים את הפרופיל המלא והמעודכן.",
        "input_schema": {
            "type": "object",
            "properties": {"content": {"type": "string", "description": "הפרופיל המלא בפורמט Markdown."}},
            "required": ["content"],
        },
    },
    {
        "name": "list_outputs",
        "description": "מציג את כל הקבצים שהסוכן יצר עד עכשיו ואת קבצי התמונות/מוזיקה שבתיקייה assets/.",
        "input_schema": {"type": "object", "properties": {}},
    },
]

# כלים שרצים על השרתים של Anthropic: חיפוש וקריאת דפי אינטרנט
SERVER_TOOLS = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 8},
    {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 8},
]


# ---------- המימוש ----------


def create_video(
    slides: list[str],
    file_name: str,
    video_format: str = "vertical",
    theme: str = "sunset",
    seconds_per_slide: float = 3.0,
    images: list[str] | None = None,
    music: str = "",
) -> str:
    seconds_per_slide = max(1.5, min(float(seconds_per_slide), 8.0))
    missing = [img for img in (images or []) if img and not _input_file(img)]
    image_paths = [_input_file(img) or "" for img in (images or [])]
    music_path = _input_file(music) if music else None
    out = OUTPUT_DIR / "videos" / f"{_stamp()}-{_safe_name(file_name, '.mp4')}"
    if out.suffix != ".mp4":
        out = out.with_suffix(".mp4")
    print(f"   🎬 מרנדר סרטון ({len(slides)} שקופיות)... זה לוקח כמה שניות")
    path = make_video(slides, str(out), video_format, theme, seconds_per_slide, image_paths, music_path=music_path)
    note = f" (לא נמצאו התמונות: {', '.join(missing)} - הוצב רקע צבעוני)" if missing else ""
    if music and not music_path:
        note += f" (קובץ המוזיקה {music} לא נמצא ב-assets/)"
    return f"הסרטון נשמר: {Path(path).relative_to(BASE_DIR)}{note}"


def save_post(platform: str, title: str, content: str, image_or_video_idea: str = "") -> str:
    folder = OUTPUT_DIR / "posts"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{_stamp()}-{_safe_name(platform, '')}-{_safe_name(title, '.md')}"
    if path.suffix != ".md":
        path = path.with_suffix(".md")
    body = f"# {title}\n\nפלטפורמה: {platform}\n\n---\n\n{content}\n"
    if image_or_video_idea:
        body += f"\n---\n\nרעיון לתמונה/סרטון: {image_or_video_idea}\n"
    path.write_text(body, encoding="utf-8")
    return f"הפוסט נשמר: {path.relative_to(BASE_DIR)}"


def save_leads(leads: list[dict]) -> str:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    existing = {(row.get("name", "").strip().lower(), row.get("website", "").strip().lower()) for row in _read_leads()}
    new_file = not LEADS_PATH.exists()
    added = 0
    # utf-8-sig כדי שאקסל יציג עברית נכון
    with LEADS_PATH.open("a", newline="", encoding="utf-8-sig" if new_file else "utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LEAD_FIELDS)
        if new_file:
            writer.writeheader()
        for lead in leads:
            key = (lead.get("name", "").strip().lower(), lead.get("website", "").strip().lower())
            if key in existing:
                continue
            existing.add(key)
            row = {k: str(lead.get(k, "")) for k in LEAD_FIELDS}
            row["date_found"] = datetime.now().strftime("%Y-%m-%d")
            row["status"] = "חדש - לא פנו עדיין"
            writer.writerow(row)
            added += 1
    return f"נוספו {added} לקוחות פוטנציאליים ל-output/leads.csv ({len(leads) - added} כפילויות דולגו)"


def _read_leads() -> list[dict]:
    if not LEADS_PATH.exists():
        return []
    with LEADS_PATH.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def read_leads() -> str:
    rows = _read_leads()
    if not rows:
        return "עדיין אין לקוחות פוטנציאליים שמורים."
    summary = [{"name": r["name"], "city": r["city"], "website": r["website"], "status": r["status"]} for r in rows]
    return json.dumps(summary, ensure_ascii=False)


def save_file(file_name: str, content: str) -> str:
    folder = OUTPUT_DIR / "files"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / _safe_name(file_name, ".md")
    path.write_text(content, encoding="utf-8")
    return f"הקובץ נשמר: {path.relative_to(BASE_DIR)}"


def read_business_profile() -> str:
    if not PROFILE_PATH.exists():
        return "אין עדיין פרופיל עסק. שאל את המשתמש מה הוא מוכר, למי, ובאיזה סגנון."
    return PROFILE_PATH.read_text(encoding="utf-8")


def update_business_profile(content: str) -> str:
    PROFILE_PATH.write_text(content, encoding="utf-8")
    return "פרופיל העסק עודכן."


def list_outputs() -> str:
    lines = []
    for root in (OUTPUT_DIR, BASE_DIR / "assets"):
        if root.exists():
            for p in sorted(root.rglob("*")):
                if p.is_file() and p.name != ".gitkeep":
                    lines.append(str(p.relative_to(BASE_DIR)))
    return "\n".join(lines) or "אין עדיין קבצים."


HANDLERS = {
    "create_video": create_video,
    "save_post": save_post,
    "save_leads": save_leads,
    "read_leads": read_leads,
    "save_file": save_file,
    "read_business_profile": read_business_profile,
    "update_business_profile": update_business_profile,
    "list_outputs": list_outputs,
}


def run_tool(name: str, tool_input: dict) -> tuple[str, bool]:
    """מריץ כלי ומחזיר (תוצאה, האם הייתה שגיאה)."""
    handler = HANDLERS.get(name)
    if handler is None:
        return f"כלי לא מוכר: {name}", True
    try:
        return handler(**tool_input), False
    except Exception as exc:  # מחזירים את השגיאה ל-Claude כדי שינסה לתקן
        return f"שגיאה: {type(exc).__name__}: {exc}", True
