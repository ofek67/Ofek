"""סוכן השיווק של אופק - רץ בטרמינל.

הפעלה:  python agent.py
"""

from __future__ import annotations

import getpass
import hmac
import os
import sys
from pathlib import Path

import anthropic

from tools import SERVER_TOOLS, TOOL_DEFINITIONS, run_tool

BASE_DIR = Path(__file__).resolve().parent
MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """אתה סוכן השיווק האישי של אופק בשירי. אתה מדבר עברית, בגובה העיניים, קצר וברור.

התפקיד שלך:
1. ליצור תוכן שיווקי: פוסטים לאינסטגרם, פייסבוק, טיקטוק, לינקדאין ווטסאפ, וסרטונים קצרים.
2. למצוא לקוחות פוטנציאליים (לידים) ברשת ולשמור אותם בקובץ מסודר עם הודעת פנייה מוכנה.
3. לתכנן קמפיינים ולוח תוכן, ולכתוב תסריטים ופרומפטים לכלי וידאו AI.

איך לעבוד:
- לפני משימה שיווקית, קרא את פרופיל העסק (read_business_profile). אם חסר מידע חשוב (מה מוכרים, למי, איפה) - שאל, ואז עדכן את הפרופיל.
- סרטונים: create_video יוצר סרטון טקסט מונפש. edit_video עורך סרטון שהמשתמש צילם (שם בתיקייה assets/) ומוסיף לו כיתובים וכרטיס סיום. אם המשתמש רוצה סרטון "אמיתי" עם אנשים או סצנות מצולמות,
  כתוב גם פרומפטים מפורטים לכלי וידאו AI ושמור אותם עם save_file.
- פוסטים: תמיד שמור עם save_post, והצע 2-3 גרסאות כשזה מתאים.
- לידים: חפש עם web_search ו-web_fetch, בדוק קודם read_leads כדי לא לשמור כפילויות, ושמור עם save_leads.
- בסוף כל משימה, תגיד בקצרה מה יצרת ואיפה הקבצים.

כללי בטיחות - חובה:
- אסור לטפל בפרטי אשראי, תשלומים, סיסמאות או קודי אימות. אם מבקשים - סרב בנימוס והסבר שאת זה המשתמש עושה בעצמו.
- לידים: רק עסקים/אנשים שפרסמו בעצמם פרטי קשר עסקיים בפומבי. בלי מידע אישי פרטי, בלי ניחוש מיילים, בלי עקיפת הגבלות של אתרים.
- אתה לא שולח הודעות לאף אחד. אתה רק מכין טיוטות, ואופק מחליט אם ולמי לשלוח.
- הודעות פנייה: אישיות, מנומסות, עם אפשרות ברורה להסיר את עצמך. בלי ספאם ובלי הבטחות שקריות.
- תוכן שיווקי אמיתי בלבד: בלי ביקורות מזויפות, בלי התחזות למותג או לאדם אחר, בלי טענות שאי אפשר להוכיח.
"""

HELP = """
פקודות:
  /new    - שיחה חדשה (מנקה את הזיכרון של השיחה, הקבצים נשארים)
  /files  - הצגת כל הקבצים שנוצרו
  /exit   - יציאה

דוגמאות למה לבקש:
  • "תכין לי סרטון של 20 שניות לטיקטוק על המבצע"
  • "תכתוב 3 פוסטים לאינסטגרם לשבוע הקרוב"
  • "תמצא לי 10 לקוחות פוטנציאליים בתל אביב"
  • "תערוך את הסרטון clip-1.mov ותוסיף כיתובים והטלפון שלי בסוף"
  • "תכתוב לי פרומפטים ל-Runway לסרטון פרסומת"
"""


def load_env() -> None:
    """טוען משתנים מהקובץ .env (אם קיים) בלי חבילות נוספות."""
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def check_password() -> None:
    """אם הוגדרה סיסמה ב-.env, רק מי שיודע אותה יכול להשתמש בסוכן."""
    expected = os.environ.get("AGENT_PASSWORD", "")
    if not expected:
        return
    for _ in range(3):
        if hmac.compare_digest(getpass.getpass("סיסמה: "), expected):
            return
        print("סיסמה שגויה.")
    sys.exit(1)


def print_text(content) -> None:
    for block in content:
        if block.type == "text" and block.text.strip():
            print(f"\n🤖 {block.text}\n")
        elif block.type == "server_tool_use":
            query = (block.input or {}).get("query") or (block.input or {}).get("url") or ""
            label = "מחפש ברשת" if block.name == "web_search" else "קורא דף"
            print(f"   🔎 {label}: {query}")


def run_turn(client: anthropic.Anthropic, messages: list) -> None:
    """שולח את השיחה ל-Claude ומריץ כלים עד שהוא מסיים."""
    for _ in range(40):  # הגנה מלולאה אינסופית
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            tools=[*TOOL_DEFINITIONS, *SERVER_TOOLS],
            messages=messages,
            output_config={"effort": "medium"},
            cache_control={"type": "ephemeral"},
            # אם בקשה נחסמת בטעות, השרת מנסה אוטומטית עם מודל אחר
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        messages.append({"role": "assistant", "content": response.content})
        print_text(response.content)

        if response.stop_reason == "tool_use":
            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                print(f"   🛠️  {block.name}")
                output, is_error = run_tool(block.name, dict(block.input or {}))
                if is_error:
                    print(f"   ⚠️  {output}")
                results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": output, "is_error": is_error}
                )
            messages.append({"role": "user", "content": results})
            continue
        if response.stop_reason == "pause_turn":
            continue  # חיפוש ארוך ברשת - ממשיכים מאיפה שעצר
        if response.stop_reason == "refusal":
            print("\n⚠️  הבקשה הזאת נחסמה. נסה לנסח אותה אחרת.\n")
        elif response.stop_reason == "max_tokens":
            print("\n⚠️  התשובה נקטעה כי הייתה ארוכה מדי. כתוב 'תמשיך'.\n")
        return
    print("\n⚠️  המשימה ארוכה מדי - עצרתי. נסה לחלק אותה לחלקים קטנים יותר.\n")


def main() -> None:
    load_env()
    check_password()
    try:
        client = anthropic.Anthropic()
    except anthropic.AnthropicError:
        print("❌ לא נמצא מפתח API. העתק את .env.example ל-.env והכנס את המפתח שלך (ראה README).")
        sys.exit(1)

    print("=" * 50)
    print("  סוכן השיווק של אופק 🚀")
    print("=" * 50)
    print(HELP)

    messages: list = []
    while True:
        try:
            user_input = input("אתה: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nלהתראות! 👋")
            return
        if not user_input:
            continue
        if user_input in ("/exit", "/quit", "יציאה"):
            print("להתראות! 👋")
            return
        if user_input == "/new":
            messages = []
            print("✨ התחלנו שיחה חדשה.\n")
            continue
        if user_input == "/files":
            print(run_tool("list_outputs", {})[0], "\n")
            continue

        start = len(messages)
        messages.append({"role": "user", "content": user_input})
        try:
            run_turn(client, messages)
        except anthropic.AuthenticationError:
            print("❌ מפתח ה-API לא תקין. בדוק את הקובץ .env.")
            del messages[start:]
        except anthropic.RateLimitError:
            print("⏳ יותר מדי בקשות. חכה דקה ונסה שוב.")
            del messages[start:]
        except anthropic.APIStatusError as exc:
            print(f"❌ שגיאה מהשרת ({exc.status_code}): {exc.message}")
            del messages[start:]
        except anthropic.APIConnectionError:
            print("❌ אין חיבור לאינטרנט. בדוק את החיבור ונסה שוב.")
            del messages[start:]
        except anthropic.AnthropicError as exc:
            print(f"❌ שגיאה: {exc}")
            del messages[start:]


if __name__ == "__main__":
    main()
