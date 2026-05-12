import logging
import json
from datetime import datetime, date, time
from pathlib import Path
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, ContextTypes, filters
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from openai import OpenAI

TELEGRAM_BOT_TOKEN = "8670898275:AAG06HceWzHxJk2JYdS4WmsbydJ-m5ZtR6U"
OPENAI_API_KEY = "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"
REPORT_HOUR = 23
REPORT_MINUTE = 00
MAIN_CHAT_FILE = "main_chat.json"
MESSAGES_FILE = "daily_messages.json"

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Основной чат ---
def save_main_chat(chat_id):
    with open(MAIN_CHAT_FILE, "w") as f:
        json.dump({"chat_id": chat_id}, f)

def load_main_chat():
    if Path(MAIN_CHAT_FILE).exists():
        with open(MAIN_CHAT_FILE) as f:
            return json.load(f).get("chat_id")
    return None

# --- Сообщения ---
def load_messages():
    if Path(MESSAGES_FILE).exists():
        with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_messages(data):
    with open(MESSAGES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def add_message(username, text, source=""):
    data = load_messages()
    today = str(date.today())
    if today not in data:
        data[today] = []
    data[today].append({
        "time": datetime.now().strftime("%H:%M"),
        "user": username,
        "text": text,
        "source": source  # откуда пришло сообщение
    })
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

# --- OpenAI ---
def analyze_with_openai(messages):
    if not messages:
        return "Сегодня сообщений не было."
    chat_log = "\n".join(
        f"[{m['time']}] {m['user']}: {m['text']}" for m in messages
    )
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
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=1000,
        messages=[
            {"role": "system", "content": "Ты аналитик переговоров."},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content

# --- Хендлеры ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return
    
    username = msg.from_user.username or msg.from_user.first_name or "Неизвестный"
    
    # Определяем откуда пришло (основной чат или ветка)
    thread_id = msg.message_thread_id
    source = f"тема #{thread_id}" if thread_id else "основной чат"
    
    # Собираем сообщения из ЛЮБОЙ ветки
    add_message(username, msg.text, source=source)
    logger.info(f"Сообщение от {username} из [{source}]: {msg.text[:50]}")

async def cmd_setmain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Установить этот чат как основной для отчётов"""
    chat_id = update.message.chat.id
    save_main_chat(chat_id)
    logger.info(f"Основной чат установлен: {chat_id}")
    await update.message.reply_text(
        f"✅ Готово! Этот чат установлен как основной.\n"
        f"ID чата: `{chat_id}`\n\n"
        f"Теперь все отчёты будут приходить сюда.",
        parse_mode="Markdown"
    )

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я собираю сообщения из всех веток и присылаю отчёт.\n\n"
        "/setmain — сделать этот чат главным для отчётов\n"
        "/report — отчёт прямо сейчас\n"
        "/count — сколько сообщений собрано\n"
        "/getid — узнать ID этого чата"
    )

async def cmd_getid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat.id
    thread_id = update.message.message_thread_id
    await update.message.reply_text(
        f"Chat ID: `{chat_id}`\n"
        f"Thread ID: `{thread_id or 'основной чат'}`",
        parse_mode="Markdown"
    )

async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    main_chat = load_main_chat()
    await update.message.reply_text("Анализирую...")
    messages = get_today_messages()
    report = analyze_with_openai(messages)
    today = date.today().strftime("%d.%m.%Y")
    # Отправляем в основной чат если он установлен, иначе туда откуда пришла команда
    target = main_chat if main_chat else update.message.chat.id
    await context.bot.send_message(chat_id=target, text=f"Отчёт за {today}\n\n{report}")

async def cmd_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    n = len(get_today_messages())
    main_chat = load_main_chat()
    status = f"✅ Основной чат установлен" if main_chat else "⚠️ Основной чат не установлен — используй /setmain"
    await update.message.reply_text(f"Сообщений за сегодня: {n}\n{status}")

async def scheduled_report(context: ContextTypes.DEFAULT_TYPE):
    chat_id = load_main_chat()
    if not chat_id:
        logger.warning("Основной чат не установлен! Используй /setmain")
        return
    messages = get_today_messages()
    report = analyze_with_openai(messages)
    today = date.today().strftime("%d.%m.%Y")
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"Ежедневный отчёт — {today}\n\n{report}"
    )
    clear_today_messages()

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("setmain", cmd_setmain))
    app.add_handler(CommandHandler("getid", cmd_getid))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("count", cmd_count))
    
    # Ловим сообщения из ВСЕХ чатов и веток
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    job_queue = app.job_queue
    job_queue.run_daily(
        scheduled_report,
        time=time(hour=REPORT_HOUR, minute=REPORT_MINUTE, second=0),
    )

    logger.info("Бот запущен! Слушаю все ветки.")
    app.run_polling(allowed_updates=["message"])

if __name__ == "__main__":
    main()
