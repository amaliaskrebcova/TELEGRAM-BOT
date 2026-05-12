import logging
import json
from datetime import datetime, date, time
from pathlib import Path
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, ContextTypes, filters
from openai import OpenAI

TELEGRAM_BOT_TOKEN = "8670898275:AAG06HceWzHxJk2JYdS4WmsbydJ-m5ZtR6U"
OPENAI_API_KEY = "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"
REPORT_HOUR = 23
REPORT_MINUTE = 00
MAIN_CHAT_FILE = "main_chat.json"
MESSAGES_FILE = "daily_messages.json"

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

def save_main_chat(chat_id):
    with open(MAIN_CHAT_FILE, "w") as f:
        json.dump({"chat_id": chat_id}, f)

def load_main_chat():
    if Path(MAIN_CHAT_FILE).exists():
        with open(MAIN_CHAT_FILE) as f:
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

def add_message(username, text, source="основной чат", thread_name=None):
    data = load_messages()
    today = str(date.today())
    if today not in data:
        data[today] = []
    data[today].append({
        "time": datetime.now().strftime("%H:%M"),
        "user": username,
        "text": text,
        "source": source,
        "thread_name": thread_name or source
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

def group_messages_by_thread(messages):
    """Группируем сообщения по веткам"""
    grouped = {}
    for m in messages:
        thread = m.get("thread_name", "Основной чат")
        if thread not in grouped:
            grouped[thread] = []
        grouped[thread].append(m)
    return grouped

def analyze_with_openai(messages):
    if not messages:
        return "Сегодня сообщений не было."

    grouped = group_messages_by_thread(messages)

    # Формируем промпт с разбивкой по веткам
    sections = []
    for thread_name, msgs in grouped.items():
        chat_log = "\n".join(f"[{m['time']}] {m['user']}: {m['text']}" for m in msgs)
        sections.append(f"=== {thread_name} ===\n{chat_log}")

    full_log = "\n\n".join(sections)

    prompt = f"""Ты помощник который пишет короткие итоги рабочего чата.

ПЕРЕПИСКА (разбита по веткам):
{full_log}

Напиши итог ДЛЯ КАЖДОЙ ВЕТКИ ОТДЕЛЬНО. Формат:

📌 [название ветки]
— что обсудили, к чему пришли, что надо сделать
— упоминай людей по нику: "@username предложил..."

Правила:
- Каждую ветку разбирай отдельно
- Коротко и по делу, никакой воды
- Пиши как живой человек, не как робот
- В конце общий вывод по всему дню если есть что добавить

Отвечай на русском."""

    client = OpenAI(api_key=OPENAI_API_KEY)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=1500,
        messages=[
            {"role": "system", "content": "Ты аналитик переговоров."},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return

    username = msg.from_user.username or msg.from_user.first_name or "Неизвестный"
    thread_id = msg.message_thread_id

    if thread_id:
        # Пытаемся получить название ветки
        thread_name = context.chat_data.get(f"thread_{thread_id}", f"Ветка #{thread_id}")
        source = f"ветка #{thread_id}"
    else:
        thread_name = "Основной чат"
        source = "основной чат"

    add_message(username, msg.text, source=source, thread_name=thread_name)
    logger.info(f"Сообщение от {username} из [{thread_name}]: {msg.text[:50]}")

async def cmd_namethred(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Дать название текущей ветке: /namethread Название"""
    msg = update.message
    thread_id = msg.message_thread_id
    if not thread_id:
        await msg.reply_text("Эта команда только для веток, не для основного чата.")
        return
    if not context.args:
        await msg.reply_text("Укажи название: /namethread Название ветки")
        return
    name = " ".join(context.args)
    context.chat_data[f"thread_{thread_id}"] = name
    await msg.reply_text(f"✅ Ветка теперь называется: *{name}*", parse_mode="Markdown")

async def cmd_setmain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat.id
    save_main_chat(chat_id)
    logger.info(f"Основной чат установлен: {chat_id}")
    await update.message.reply_text(
        f"✅ Этот чат установлен как основной для отчётов.\n"
        f"ID: `{chat_id}`",
        parse_mode="Markdown"
    )

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Собираю сообщения из всех веток и присылаю отчёт по каждой.\n\n"
        "/setmain — сделать этот чат главным для отчётов\n"
        "/namethread Название — дать имя текущей ветке\n"
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
    await update.message.reply_text("Анализирую все ветки...")
    messages = get_today_messages()
    report = analyze_with_openai(messages)
    today = date.today().strftime("%d.%m.%Y")
    target = main_chat if main_chat else update.message.chat.id
    await context.bot.send_message(
        chat_id=target,
        text=f"📊 Отчёт за {today}\n\n{report}"
    )

async def cmd_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    messages = get_today_messages()
    grouped = group_messages_by_thread(messages)
    main_chat = load_main_chat()
    status = "✅ Основной чат установлен" if main_chat else "⚠️ Основной чат не установлен — используй /setmain"

    lines = [f"📨 Сообщений за сегодня: {len(messages)}\n{status}\n"]
    for thread, msgs in grouped.items():
        lines.append(f"• {thread}: {len(msgs)} сообщ.")

    await update.message.reply_text("\n".join(lines))

async def scheduled_report(context: ContextTypes.DEFAULT_TYPE):
    chat_id = load_main_chat()
    if not chat_id:
        logger.warning("Основной чат не установлен!")
        return
    messages = get_today_messages()
    report = analyze_with_openai(messages)
    today = date.today().strftime("%d.%m.%Y")
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"📊 Ежедневный отчёт — {today}\n\n{report}"
    )
    clear_today_messages()

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("setmain", cmd_setmain))
    app.add_handler(CommandHandler("getid", cmd_getid))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("count", cmd_count))
    app.add_handler(CommandHandler("namethread", cmd_namethred))
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
