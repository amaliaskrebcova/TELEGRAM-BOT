import logging
import json
from datetime import datetime, date
from pathlib import Path
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, ContextTypes, filters
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from openai import OpenAI

TELEGRAM_BOT_TOKEN = "8670898275:AAG06HceWzHxJk2JYdS4WmsbydJ-m5ZtR6U"
OPENAI_API_KEY = "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"
REPORT_HOUR = 23
REPORT_MINUTE = 0
CHAT_ID_FILE = "chat_id.json"
MESSAGES_FILE = "daily_messages.json"

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

def save_chat_id(chat_id):
    with open(CHAT_ID_FILE, "w") as f:
        json.dump({"chat_id": chat_id}, f)

def load_chat_id():
    if Path(CHAT_ID_FILE).exists():
        with open(CHAT_ID_FILE) as f:
            return json.load(f).get("chat_id")
    return None

def load_messages():
    if Path(MESSAGES_FILE).exists():
        with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_messages(data):
    with open(MESSAGES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def add_message(username, text):
    data = load_messages()
    today = str(date.today())
    if today not in data:
        data[today] = []
    data[today].append({"time": datetime.now().strftime("%H:%M"), "user": username, "text": text})
    save_messages(data)

def get_today_messages():
    data = load_messages()
    return data.get(str(date.today()), [])

def clear_today_messages():
    data = load_messages()
    today = str(date.today())
    if today in data:
        del data[today]
    save_messages(data)

def analyze_with_openai(messages):
    if not messages:
        return "Сегодня сообщений не было."
    chat_log = "\n".join(f"[{m['time']}] {m['user']}: {m['text']}" for m in messages)
    prompt = f"""Ты помощник который пишет короткие итоги рабочего чата.

ПЕРЕПИСКА:
{chat_log}

Напиши короткий неформальный итог. Правила:
- Упоминай людей по их нику: "@username предложил...", "@username сказал..."
- Никакой воды и формальных оборотов
- Коротко и по делу  
- Что обсудили, к чему пришли, что надо сделать
- Пиши как живой человек, не как робот

Отвечай на русском."""
    client = OpenAI(api_key=OPENAI_API_KEY)
    response = client.chat.completions.create(model="gpt-4o-mini", max_tokens=1000, messages=[{"role": "system", "content": "Ты аналитик переговоров."}, {"role": "user", "content": prompt}])
    return response.choices[0].message.content

async def handle_message(update, context):
    msg = update.message
    if not msg or not msg.text:
        return
    if load_chat_id() != msg.chat.id:
        save_chat_id(msg.chat.id)
    username = msg.from_user.username or msg.from_user.first_name or "Неизвестный"
    add_message(username, msg.text)

async def cmd_start(update, context):
    save_chat_id(update.message.chat.id)
    await update.message.reply_text("Привет! Каждую ночь в 02:00 по Москве присылаю отчёт.\n\n/report — отчёт сейчас\n/count — сколько сообщений собрано")

async def cmd_report(update, context):
    await update.message.reply_text("Анализирую...")
    messages = get_today_messages()
    report = analyze_with_openai(messages)
    today = date.today().strftime("%d.%m.%Y")
    await update.message.reply_text(f"Отчёт за {today}\n\n{report}")

async def cmd_count(update, context):
    n = len(get_today_messages())
    await update.message.reply_text(f"Сообщений за сегодня: {n}")

async def scheduled_report(app):
    chat_id = load_chat_id()
    if not chat_id:
        return
    messages = get_today_messages()
    report = analyze_with_openai(messages)
    today = date.today().strftime("%d.%m.%Y")
    await app.bot.send_message(chat_id=chat_id, text=f"Ежедневный отчёт — {today}\n\n{report}")
    clear_today_messages()

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("count", cmd_count))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    scheduler = AsyncIOScheduler()
    scheduler.add_job(scheduled_report, trigger="cron", hour=REPORT_HOUR, minute=REPORT_MINUTE, args=[app])
    logger.info("Бот запущен!")
    app.run_polling(allowed_updates=["message"])

if __name__ == "__main__":
    main()