"""
🤍🩵 Zamalek Ticket Watcher — tazkarti.com API
-----------------------------------------------
Modes:
  python zamalek_watcher.py          ← loop مستمر (محلي)
  python zamalek_watcher.py --once   ← مرة واحدة (GitHub Actions)
  python zamalek_watcher.py --test   ← تجربة Telegram + Voice

Secrets من environment variables:
  TELEGRAM_BOT_TOKEN
  TELEGRAM_CHAT_IDS   ← مفصولين بفاصلة: 936340456,987654321
"""

import json
import os
import sys
import time
import logging
import requests
from datetime import datetime

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# اتنين chat_id مفصولين بفاصلة في الـ env
# مثال: "936340456,987654321"
TELEGRAM_CHAT_IDS  = [
    cid.strip()
    for cid in os.getenv("TELEGRAM_CHAT_IDS", "YOUR_CHAT_ID_HERE").split(",")
    if cid.strip()
]

API_URL                = "https://www.tazkarti.com/data/matches-list-json.json"
ZAMALEK_TEAM_ID        = 79
ZAMALEK_NAMES          = ["Zamalek", "الزمالك", "ZAMALEK"]
CHECK_INTERVAL_MINUTES = 5
SEEN_FILE              = "seen_zamalek_matches.json"
BOOK_BASE_URL          = "https://www.tazkarti.com/#/book-ticket"
ALERT_AUDIO_PATH       = "alert.mp3"   # ملف الصوت جنب السكريبت
# ─────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.tazkarti.com/",
}


# ── Telegram text ─────────────────────────────
def send_telegram(msg: str):
    """بيبعت رسالة نصية لكل الـ chat_ids"""
    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": msg,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": False,
                },
                timeout=10,
            )
            if r.status_code == 200:
                log.info(f"✅ Telegram message sent → {chat_id}")
            else:
                log.error(f"❌ Telegram message error ({chat_id}): {r.text}")
        except Exception as e:
            log.error(f"❌ Telegram message exception ({chat_id}): {e}")


# ── Telegram voice ────────────────────────────
def send_voice_alert():
    """بيبعت الـ voice note لكل الـ chat_ids — بترن بصوت مميز"""
    if not os.path.exists(ALERT_AUDIO_PATH):
        log.warning(f"⚠️ Audio file not found: {ALERT_AUDIO_PATH}")
        return

    for chat_id in TELEGRAM_CHAT_IDS:
        try:
            with open(ALERT_AUDIO_PATH, "rb") as f:
                r = requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendAudio",
                    data={
                        "chat_id": chat_id,
                        "caption": "🚨 تذاكر الزمالك نزلت!",
                    },
                    files={"audio": ("alert.mp3", f, "audio/mpeg")},
                    timeout=30,
                )
            if r.status_code == 200:
                log.info(f"✅ Voice alert sent → {chat_id}")
            else:
                log.error(f"❌ Voice alert error ({chat_id}): {r.text}")
        except Exception as e:
            log.error(f"❌ Voice alert exception ({chat_id}): {e}")


# ── Full alert (text + voice) ─────────────────
def alert(msg: str):
    send_telegram(msg)
    send_voice_alert()


# ── Seen matches ──────────────────────────────
def load_seen() -> set:
    try:
        return set(json.load(open(SEEN_FILE, encoding="utf-8")))
    except FileNotFoundError:
        return set()


def save_seen(seen: set):
    json.dump(list(seen), open(SEEN_FILE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)


# ── API ───────────────────────────────────────
def fetch_matches() -> list:
    ts = int(time.time() * 1000)
    r  = requests.get(API_URL, params={"_": ts}, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()


# ── Match helpers ─────────────────────────────
def is_zamalek_match(m: dict) -> bool:
    """بيتعرف على الزمالك بالـ ID أو بالاسم كـ fallback"""
    by_id = (
        m.get("teamId1") == ZAMALEK_TEAM_ID
        or m.get("teamId2") == ZAMALEK_TEAM_ID
    )
    all_names = " ".join([
        str(m.get("teamName1",   "")),
        str(m.get("teamNameAr1", "")),
        str(m.get("teamName2",   "")),
        str(m.get("teamNameAr2", "")),
    ])
    by_name = any(n in all_names for n in ZAMALEK_NAMES)
    return by_id or by_name


def parse_status(m: dict) -> str:
    s = m.get("matchStatus", 0)
    return "🟢 متاح للحجز" if s == 1 else "🔴 نفدت التذاكر" if s == 2 else f"⚪ ({s})"


def build_message(m: dict, now: str) -> str:
    mid        = m["matchId"]
    team1      = m.get("teamName1",  "") or m.get("teamNameAr1", "")
    team2      = m.get("teamName2",  "") or m.get("teamNameAr2", "")
    stadium    = m.get("stadiumNameAr") or m.get("stadiumName",  "")
    city       = m.get("stadiumCityAr") or m.get("stadiumCityEn","")
    tournament = (m.get("tournament") or {}).get("nameAr", "")
    match_num  = m.get("matchNumber", "")
    status_txt = parse_status(m)

    try:
        dt      = datetime.fromisoformat(m.get("kickOffTime", ""))
        kickoff = dt.strftime("%Y-%m-%d الساعة %I:%M %p")
    except Exception:
        kickoff = m.get("kickOffTime", "")

    return (
        f"🎉🤍🩵 <b>مباراة زمالك جديدة!</b>\n\n"
        f"⚽ <b>{team1} vs {team2}</b>\n"
        f"🏆 {tournament}\n"
        f"🏟️ {stadium}، {city}\n"
        f"📅 {kickoff}\n"
        f"🔢 رقم المباراة: {match_num}\n"
        f"🎫 {status_txt}\n\n"
        f"🔗 <a href='{BOOK_BASE_URL}/{mid}'>احجز دلوقتي!</a>\n"
        f"⏰ {now}"
    )


# ── Core check ────────────────────────────────
def check_once():
    now  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    seen = load_seen()

    log.info(f"🔍 Fetching API... [{now}]")
    all_matches     = fetch_matches()
    zamalek_matches = [m for m in all_matches if is_zamalek_match(m)]
    new_matches     = [m for m in zamalek_matches if str(m["matchId"]) not in seen]

    log.info(f"📦 Total: {len(all_matches)} | 🤍 Zamalek: {len(zamalek_matches)} | 🆕 New: {len(new_matches)}")

    if new_matches:
        for m in new_matches:
            log.info(f"🆕 {m.get('teamName1')} vs {m.get('teamName2')} | matchId={m['matchId']} | {parse_status(m)}")
            alert(build_message(m, now))
            seen.add(str(m["matchId"]))
        save_seen(seen)
    else:
        log.info("😴 No new Zamalek matches")


# ── Test mode ─────────────────────────────────
def test_mode():
    """بيجيب أول ماتش زمالك من الـ API ويبعته مع الصوت — زي الـ alert الحقيقي بالظبط"""
    log.info("🧪 Test mode — fetching real Zamalek match...")
    now         = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    all_matches = fetch_matches()
    zamalek     = [m for m in all_matches if is_zamalek_match(m)]

    if zamalek:
        m = zamalek[0]
        log.info(f"📬 Sending to chat_ids: {TELEGRAM_CHAT_IDS}")
        alert(build_message(m, now))
    else:
        log.warning("⚠️ No Zamalek match found on API right now")
        send_telegram("⚠️ مفيش ماتش زمالك موجود دلوقتي على الـ API")


# ── Loop ──────────────────────────────────────
def run_loop():
    send_telegram(
        f"🤍🩵 <b>Zamalek Watcher شغال!</b>\n"
        f"بيراقب الـ API كل {CHECK_INTERVAL_MINUTES} دقايق 🎫"
    )
    while True:
        try:
            check_once()
        except Exception as e:
            log.error(f"❌ {e}")
            send_telegram(f"⚠️ <b>خطأ:</b>\n<code>{e}</code>")
        log.info(f"⏳ Next check in {CHECK_INTERVAL_MINUTES} min...\n")
        time.sleep(CHECK_INTERVAL_MINUTES * 60)


# ── Entry point ───────────────────────────────
if __name__ == "__main__":
    if "--test" in sys.argv:
        test_mode()
    elif "--once" in sys.argv:
        check_once()
    else:
        run_loop()