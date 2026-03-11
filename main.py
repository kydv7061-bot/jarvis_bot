"""
╔══════════════════════════════════════════════════════╗
║  J.A.R.V.I.S v10.0 — WEB DASHBOARD + TELEGRAM BOT  ║
║  Flask server + Bot running in same process          ║
║  Deploy: Railway.app (one repo, one service)         ║
╚══════════════════════════════════════════════════════╝
"""

import os, re, json, time, datetime, threading, logging
import urllib.parse, random, secrets, string
from collections import deque
from typing import Tuple

import requests
from groq import Groq
from flask import Flask, request, jsonify, render_template
from telegram import Update, Bot
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes
)
from telegram.constants import ParseMode
import yt_dlp
import asyncio

# ══════════════════════════════════════════════════
# CONFIG — Railway Environment Variables
# ══════════════════════════════════════════════════
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "")
WEATHER_KEY    = os.getenv("WEATHER_KEY", "")
CRICKET_KEY    = os.getenv("CRICKET_KEY", "")
OWNER_ID       = int(os.getenv("OWNER_ID", "0"))
CHANNEL_ID     = os.getenv("CHANNEL_ID", "")
PORT           = int(os.getenv("PORT", "5000"))
DASHBOARD_PASS = os.getenv("DASHBOARD_PASS", "jarvis123")  # dashboard password

WHATSAPP_CONTACTS = {
    "ayesha": "+91XXXXXXXXXX",
    "mom":    "+91XXXXXXXXXX",
    "dad":    "+91XXXXXXXXXX",
}

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger("JARVIS")

# ══════════════════════════════════════════════════
# MEMORY
# ══════════════════════════════════════════════════
class Memory:
    def __init__(self):
        self.data = {
            "user_name": None, "user_city": None,
            "conversation_count": 0, "learned_facts": [],
            "notes": [], "reminders": [],
            "personality_mode": "casual", "total_tasks_done": 0,
            "habits": {},
        }

    def learn(self, key, value):
        for f in self.data.setdefault("learned_facts", []):
            if f.get("key") == key:
                f["value"] = value; return
        self.data["learned_facts"].append({"key": key, "value": value})

    def add_note(self, text):
        self.data.setdefault("notes", []).append({
            "text": text, "time": datetime.datetime.now().strftime("%d %b %H:%M")
        })

    def rich_context(self) -> str:
        d = self.data; lines = []
        if d.get("user_name"): lines.append(f"Name: {d['user_name']}")
        if d.get("user_city"): lines.append(f"City: {d['user_city']}")
        for f in d.get("learned_facts", [])[:4]:
            lines.append(f"{f['key']}={f['value']}")
        return "\n".join(lines) or "New user."

# ══════════════════════════════════════════════════
# HABITS
# ══════════════════════════════════════════════════
class HabitTracker:
    def __init__(self, memory: Memory):
        self.memory = memory

    @property
    def habits(self):
        return self.memory.data.setdefault("habits", {})

    def add(self, name) -> str:
        self.habits[name] = {"log": [], "streak": 0}
        return f"✅ Habit added: {name}"

    def done(self, name) -> str:
        today = datetime.date.today().isoformat()
        for hn, d in self.habits.items():
            if name.lower() in hn.lower():
                if today in d.get("log", []):
                    return f"✅ {hn} already done today! 🔥"
                d.setdefault("log", []).append(today)
                streak = 0; check = datetime.date.today()
                while check.isoformat() in d["log"]:
                    streak += 1; check -= datetime.timedelta(days=1)
                d["streak"] = streak
                return f"🎯 {hn} — DONE!\n🔥 Streak: {streak} days!"
        return f"❌ Habit '{name}' not found."

    def summary(self) -> list:
        today = datetime.date.today().isoformat()
        result = []
        for name, d in self.habits.items():
            done = today in d.get("log", [])
            result.append({"name": name, "done": done, "streak": d.get("streak", 0)})
        return result

# ══════════════════════════════════════════════════
# BRAIN
# ══════════════════════════════════════════════════
PERSONALITIES = {
    "casual":  "You are JARVIS, Tony Stark's witty AI. Friendly, smart, use emojis naturally. Address user as 'Sir'.",
    "pro":     "You are JARVIS in professional mode. Sharp, concise, data-driven. No fluff. Address user as 'Sir'.",
    "coach":   "You are JARVIS as a life coach. High energy, motivational. Address user as 'Sir'.",
    "savage":  "You are JARVIS in brutal honesty mode. Direct, zero BS. Address user as 'Sir'.",
    "calm":    "You are JARVIS in zen mode. Calm, grounded, wise. Address user as 'Sir'.",
    "genius":  "You are JARVIS in genius mode. Think first principles, connect dots. Address user as 'Sir'.",
}

class Brain:
    def __init__(self, memory: Memory):
        self.memory = memory
        self.groq = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
        self.histories: dict = {}

    def set_mode(self, mode: str) -> str:
        mode = mode.lower().strip()
        if mode in PERSONALITIES:
            self.memory.data["personality_mode"] = mode
            return f"🎭 {mode.upper()} mode activated."
        return f"❌ Available: {', '.join(PERSONALITIES.keys())}"

    def ask(self, session_id: str, user_input: str) -> str:
        if not self.groq:
            return "❌ GROQ_API_KEY not set in Railway variables."
        history = self.histories.setdefault(session_id, deque(maxlen=12))
        mode = self.memory.data.get("personality_mode", "casual")
        system = f"{PERSONALITIES.get(mode, PERSONALITIES['casual'])}\n\nContext:\n{self.memory.rich_context()}\n\nNEVER say 'As an AI'. Be direct."
        history.append({"role": "user", "content": user_input})
        try:
            r = self.groq.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "system", "content": system}, *list(history)],
                temperature=0.72, max_tokens=900,
            )
            reply = r.choices[0].message.content
            history.append({"role": "assistant", "content": reply})
            self._extract_facts(user_input)
            self.memory.data["total_tasks_done"] = self.memory.data.get("total_tasks_done", 0) + 1
            return reply
        except Exception as e:
            log.error(f"Groq: {e}")
            return f"⚠️ AI error: {str(e)[:100]}"

    def generate(self, prompt: str, max_tokens=900) -> str:
        if not self.groq:
            return "❌ GROQ_API_KEY not set."
        try:
            r = self.groq.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
            )
            return r.choices[0].message.content
        except Exception as e:
            return f"❌ {str(e)[:100]}"

    def clear(self, session_id: str) -> str:
        self.histories[session_id] = deque(maxlen=12)
        return "🔄 Memory cleared."

    def _extract_facts(self, text):
        t = text.lower()
        m = re.search(r"my name is (\w+)", t)
        if m: self.memory.data["user_name"] = m.group(1).title(); self.memory.learn("name", m.group(1).title())
        m = re.search(r"i(?:'m| am) from ([a-zA-Z ]+)", t)
        if m: self.memory.data["user_city"] = m.group(1).strip().title(); self.memory.learn("city", m.group(1).strip().title())

# ══════════════════════════════════════════════════
# TOOLS
# ══════════════════════════════════════════════════
def get_weather(city: str) -> dict:
    if not city:
        return {"error": "City name required"}
    if WEATHER_KEY:
        try:
            r = requests.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={"q": city, "appid": WEATHER_KEY, "units": "metric"}, timeout=8,
            )
            d = r.json()
            if d.get("cod") == 200:
                return {
                    "city": d["name"], "country": d["sys"]["country"],
                    "temp": round(d["main"]["temp"]),
                    "feels": round(d["main"]["feels_like"]),
                    "humidity": d["main"]["humidity"],
                    "wind": d["wind"]["speed"],
                    "desc": d["weather"][0]["description"].title(),
                    "icon": d["weather"][0]["icon"],
                }
        except Exception as e:
            log.error(f"Weather: {e}")
    return {"url": f"https://wttr.in/{urllib.parse.quote(city)}"}

def get_cricket() -> str:
    if not CRICKET_KEY:
        return "❌ CRICKET_KEY not set."
    try:
        r = requests.get(
            f"https://api.cricketdata.org/api/v1/currentMatches?apikey={CRICKET_KEY}", timeout=10,
        )
        data = r.json()
        if data.get("status") != "success":
            return "❌ Cricket data unavailable."
        matches = data.get("data", [])
        if not matches:
            return "No live matches right now."
        lines = []
        for m in matches[:5]:
            lines.append(f"📍 {m.get('name','')}")
            lines.append(f"Status: {m.get('status','')}")
            for s in m.get("score", []):
                lines.append(f"  {s.get('inning','')}: {s.get('r',0)}/{s.get('w',0)} ({s.get('o',0)} ov)")
            lines.append("")
        return "\n".join(lines)
    except Exception as e:
        return f"⚠️ {e}"

def yt_search(query: str) -> dict:
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "extract_flat": True}) as ydl:
            info = ydl.extract_info(f"ytsearch3:{query}", download=False)
            if info and info.get("entries"):
                results = []
                for entry in info["entries"][:3]:
                    results.append({
                        "title": entry.get("title", ""),
                        "id": entry.get("id", ""),
                        "url": f"https://www.youtube.com/watch?v={entry.get('id','')}",
                        "duration": entry.get("duration_string", ""),
                        "channel": entry.get("channel", ""),
                    })
                return {"results": results}
    except Exception as e:
        log.error(f"YT: {e}")
    fallback_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"
    return {"fallback": fallback_url}

# ══════════════════════════════════════════════════
# JARVIS CORE
# ══════════════════════════════════════════════════
memory  = Memory()
habits  = HabitTracker(memory)
brain   = Brain(memory)

# ══════════════════════════════════════════════════
# FLASK APP
# ══════════════════════════════════════════════════
app = Flask(__name__)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.json or {}
    msg  = data.get("message", "").strip()
    sid  = data.get("session_id", "web")
    if not msg:
        return jsonify({"reply": "❌ Empty message"})

    # Special AI tasks
    t = msg.lower()
    if any(kw in t for kw in ["write", "blog", "essay", "script", "report"]):
        reply = brain.generate(f"Write a well-structured detailed response for:\n{msg}", 1200)
    elif t.startswith("brainstorm"):
        reply = brain.generate(f"Generate 8 creative ideas for: {msg}\nFor each: Name → What → Why.", 900)
    elif t.startswith("explain"):
        reply = brain.generate(f"Explain clearly: simple language → analogy → key points → example.\n{msg}", 800)
    elif t.startswith("translate"):
        reply = brain.generate(f"Translate. Reply ONLY with translation:\n{msg}", 400)
    elif t.startswith("debate"):
        reply = brain.generate(f"Balanced debate:\nFOR (pros): 3-4 points\nAGAINST: 3-4 points\nVERDICT:\n\n{msg}", 700)
    elif t.startswith("summarize"):
        reply = brain.generate(f"Summarize with 5 key bullet points:\n{msg}", 500)
    else:
        reply = brain.ask(sid, msg)

    return jsonify({"reply": reply})

@app.route("/api/weather", methods=["POST"])
def api_weather():
    city = (request.json or {}).get("city", "").strip()
    return jsonify(get_weather(city))

@app.route("/api/cricket", methods=["GET"])
def api_cricket():
    return jsonify({"scores": get_cricket()})

@app.route("/api/youtube", methods=["POST"])
def api_youtube():
    query = (request.json or {}).get("query", "").strip()
    if not query:
        return jsonify({"error": "Query required"})
    return jsonify(yt_search(query))

@app.route("/api/notes", methods=["GET", "POST"])
def api_notes():
    if request.method == "POST":
        text = (request.json or {}).get("text", "").strip()
        if text:
            memory.add_note(text)
            return jsonify({"ok": True})
        return jsonify({"error": "Empty note"})
    notes = memory.data.get("notes", [])[-20:]
    return jsonify({"notes": list(reversed(notes))})

@app.route("/api/reminders", methods=["GET", "POST"])
def api_reminders():
    if request.method == "POST":
        data = request.json or {}
        text = data.get("text", "").strip()
        mins = int(data.get("minutes", 0))
        if text and mins > 0:
            fire = datetime.datetime.now() + datetime.timedelta(minutes=mins)
            memory.data.setdefault("reminders", []).append({
                "time": fire.strftime("%H:%M"),
                "message": text,
                "fire_ts": fire.timestamp(),
                "done": False,
                "created": datetime.datetime.now().strftime("%d %b %H:%M"),
            })
            return jsonify({"ok": True, "fire_at": fire.strftime("%H:%M")})
        return jsonify({"error": "text and minutes required"})
    active = [r for r in memory.data.get("reminders", []) if not r.get("done")]
    return jsonify({"reminders": active})

@app.route("/api/mode", methods=["POST"])
def api_mode():
    mode = (request.json or {}).get("mode", "").strip()
    result = brain.set_mode(mode)
    return jsonify({"result": result, "current": memory.data.get("personality_mode", "casual")})

@app.route("/api/status", methods=["GET"])
def api_status():
    return jsonify({
        "online": True,
        "mode": memory.data.get("personality_mode", "casual"),
        "tasks": memory.data.get("total_tasks_done", 0),
        "notes": len(memory.data.get("notes", [])),
        "reminders": len([r for r in memory.data.get("reminders", []) if not r.get("done")]),
        "name": memory.data.get("user_name", ""),
        "time": datetime.datetime.now().strftime("%H:%M:%S"),
        "date": datetime.datetime.now().strftime("%A, %d %b %Y"),
        "ai": "GROQ LLAMA3" if GROQ_API_KEY else "OFFLINE",
    })

@app.route("/api/clear", methods=["POST"])
def api_clear():
    sid = (request.json or {}).get("session_id", "web")
    return jsonify({"result": brain.clear(sid)})

# ══════════════════════════════════════════════════
# TELEGRAM BOT HANDLERS
# ══════════════════════════════════════════════════
async def tg_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *JARVIS v10.0 — ONLINE*\n\nAll systems operational, Sir.\n\n"
        "Just type naturally — I understand everything!\n"
        "*/help* — full command list",
        parse_mode=ParseMode.MARKDOWN,
    )

async def tg_cricket(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("🏏 _Fetching..._", parse_mode=ParseMode.MARKDOWN)
    await msg.edit_text(get_cricket() or "No data", parse_mode=ParseMode.MARKDOWN)

async def tg_clear(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    result = brain.clear(str(update.effective_chat.id))
    await update.message.reply_text(result, parse_mode=ParseMode.MARKDOWN)

async def tg_mode(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: `/mode casual|pro|coach|savage|calm|genius`", parse_mode=ParseMode.MARKDOWN)
        return
    await update.message.reply_text(brain.set_mode(ctx.args[0]), parse_mode=ParseMode.MARKDOWN)

async def tg_post(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Unauthorized."); return
    if not ctx.args or not CHANNEL_ID:
        await update.message.reply_text("Usage: `/post message` (set CHANNEL_ID in Railway vars)"); return
    text = " ".join(ctx.args)
    await ctx.bot.send_message(chat_id=CHANNEL_ID, text=text, parse_mode=ParseMode.MARKDOWN)
    await update.message.reply_text("✅ Posted!", parse_mode=ParseMode.MARKDOWN)

async def reminder_fire(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    await context.bot.send_message(chat_id=job.chat_id,
        text=f"⏰ *JARVIS Reminder*\n\n{job.data}", parse_mode=ParseMode.MARKDOWN)

async def tg_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    chat_id = update.effective_chat.id
    t = text.lower()

    # WhatsApp
    wa = re.match(r"^text (\w+)\s+(.+)$", text, re.IGNORECASE)
    if wa:
        contact = wa.group(1).lower(); msg = wa.group(2)
        phone = WHATSAPP_CONTACTS.get(contact)
        if phone:
            url = f"https://web.whatsapp.com/send?phone={phone}&text={urllib.parse.quote(msg)}"
            await update.message.reply_text(f"💬 [WhatsApp → {contact.title()}]({url})", parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=False)
        else:
            await update.message.reply_text(f"❌ Contact '{contact}' not found.", parse_mode=ParseMode.MARKDOWN)
        return

    # Reminder
    m = re.match(r"^remind(?:er)?\s+(?:me\s+)?in\s+(\d+)\s*(min(?:ute)?s?|hours?)\s+(?:to\s+)?(.+)$", text, re.IGNORECASE)
    if m:
        amount = int(m.group(1)); unit = m.group(2); rmsg = m.group(3)
        secs = amount * 3600 if "hour" in unit.lower() else amount * 60
        ctx.job_queue.run_once(reminder_fire, when=secs, chat_id=chat_id, data=rmsg)
        await update.message.reply_text(f"⏰ Reminder set!\n*In {amount} {unit}:* _{rmsg}_", parse_mode=ParseMode.MARKDOWN)
        return

    # YouTube
    if re.match(r"^(?:play|search yt)\s+.+", t):
        query = re.sub(r"^(?:play|search yt)\s+", "", t)
        data = yt_search(query)
        if data.get("results"):
            r = data["results"][0]
            await update.message.reply_text(f"▶️ *{r['title']}*\n[Watch]({r['url']})", parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(f"▶️ [Search YouTube]({data.get('fallback','')})", parse_mode=ParseMode.MARKDOWN)
        return

    # Cricket
    if any(kw in t for kw in ["cricket", "ipl", "live score"]):
        await update.message.reply_text(get_cricket(), parse_mode=ParseMode.MARKDOWN)
        return

    # AI
    thinking = await update.message.reply_text("🤖 _Processing..._", parse_mode=ParseMode.MARKDOWN)
    if any(kw in t for kw in ["write", "blog", "essay"]):
        reply = brain.generate(f"Write a well-structured response for:\n{text}", 1200)
    elif t.startswith("brainstorm"):
        reply = brain.generate(f"8 creative ideas for: {text}\nFor each: Name → What → Why.", 900)
    else:
        reply = brain.ask(str(chat_id), text)
    try:
        await thinking.edit_text(reply[:4000], parse_mode=ParseMode.MARKDOWN)
    except:
        await thinking.edit_text(reply[:4000])

# ══════════════════════════════════════════════════
# REMINDER CHECKER THREAD (for web reminders)
# ══════════════════════════════════════════════════
def reminder_checker():
    while True:
        now = datetime.datetime.now().timestamp()
        for r in memory.data.get("reminders", []):
            if not r.get("done") and r.get("fire_ts", 0) <= now:
                r["done"] = True
                log.info(f"[REMINDER FIRED] {r['message']}")
        time.sleep(30)

# ══════════════════════════════════════════════════
# RUN BOTH FLASK + TELEGRAM
# ══════════════════════════════════════════════════
def run_flask():
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)

def run_telegram():
    if not TELEGRAM_TOKEN:
        log.warning("TELEGRAM_TOKEN not set — Telegram bot disabled.")
        return
    tg_app = Application.builder().token(TELEGRAM_TOKEN).build()
    tg_app.add_handler(CommandHandler("start",   tg_start))
    tg_app.add_handler(CommandHandler("cricket", tg_cricket))
    tg_app.add_handler(CommandHandler("clear",   tg_clear))
    tg_app.add_handler(CommandHandler("mode",    tg_mode))
    tg_app.add_handler(CommandHandler("post",    tg_post))
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, tg_message))
    log.info("✅ Telegram bot starting...")
    tg_app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    log.info("🤖 JARVIS v10.0 — WEB + TELEGRAM — Starting...")

    # Start reminder checker
    threading.Thread(target=reminder_checker, daemon=True).start()

    # Start Flask in background thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    log.info(f"✅ Flask dashboard running on port {PORT}")

    # Run Telegram in main thread
    run_telegram()
