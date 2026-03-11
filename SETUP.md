# JARVIS v10.0 — Web Dashboard + Telegram Bot
# Railway Setup Guide
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## GitHub Repo Structure:
jarvis-bot/
├── main.py              ← Flask server + Telegram bot
├── requirements.txt     ← dependencies
├── templates/
│   └── index.html       ← Iron Man HUD dashboard
└── SETUP.md

## Railway Variables (Dashboard → Variables):
TELEGRAM_TOKEN   = your_bot_token
GROQ_API_KEY     = gsk_xxxx  (console.groq.com — FREE)
WEATHER_KEY      = openweather key (optional)
CRICKET_KEY      = cricketdata.org key (optional)
OWNER_ID         = your telegram user ID (@userinfobot)
CHANNEL_ID       = @yourchannel (optional)
DASHBOARD_PASS   = jarvis123 (change this!)
PORT             = 5000 (Railway sets this auto)

## After Deploy:
- Web Dashboard: https://your-app.railway.app
- Telegram Bot: just open @yourbotname in Telegram

## WhatsApp Contacts:
Edit in main.py:
WHATSAPP_CONTACTS = {
    "ayesha": "+91XXXXXXXXXX",
    "mom":    "+91XXXXXXXXXX",
}

## Free API Keys:
- Groq:        console.groq.com
- OpenWeather: openweathermap.org/api
- Cricket:     cricketdata.org
- Telegram:    @BotFather
- Your ID:     @userinfobot
