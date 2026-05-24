import os
import logging
import json
import pytz
from datetime import datetime, date, time, timedelta
from pathlib import Path
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, ContextTypes, filters
from openai import OpenAI

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8670898275:AAHfyaQ2ifFQlmaen7SNHhuI1IqKEf8WM5I")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
REPORT_HOUR = 21
REPORT_MINUTE =15
MAIN_CHAT_FILE = "main_chat.json"
MESSAGES_FILE = "daily_messages.json"
MOSCOW_TZ = pytz.timezone("Europe/Moscow")

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
    moscow_now = datetime.now(MOSCOW_TZ)
    today = str(moscow_now.date())
    if today not in data:
        data[today] = []
    data[today].append({
        "time": moscow_now.strftime("%H:%M"),
        "user": username,
        "text": text,
        "source": source,
        "thread_name": thread_name or source
    })
    save_messages(data)

def get_messages_for_date(target_date):
    data = load_messages()
    return data.get(str(target_date), [])

def get_today_messages():
    return get_messages_for_date(datetime.now(MOSCOW_TZ).date())

def get_yesterday_messages():
    return get_messages_for_date((datetime.now(MOSCOW_TZ) - timedelta(days=1)).date())

def clear_today_messages():
    data = load_messages()
    moscow_today = str(datetime.now(MOSCOW_TZ).date())
    if moscow_today in data:
        del data[moscow_today]
    save_messages(data)

def group_messages_by_thread(messages):
    grouped = {}
    for m in messages:
        thread = m.get("thread_name", "Основной чат")
        if thread not in grouped:
            grouped[thread] = []
        grouped[thread].append(m)
    return grouped

def analyze_with_openai(messages, label="сегодня"):
    if not messages:
        return f"За {label} сообщений не было."
    grouped = group_messages_by_thread(messages)
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

async def handle_forum_topic_created(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg and msg.forum_topic_created and msg.message_thread_id:
        thread_id = msg.message_thread_id
        thread_name = msg.forum_topic_created.name
        context.chat_data[f"thread_{thread_id}"] = thread_name

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return
    username = msg.from_user.username or msg.from_user.first_name or "Неизвестный"
    thread_id = msg.message_thread_id
    if thread_id:
        thread_name = context.chat_data.get(f"thread_{thread_id}")
        if not thread_name:
            try:
                if msg.forum_topic_created:
                    thread_name = msg.forum_topic_created.name
                    context.chat_data[f"thread_{thread_id}"] = thread_name
            except Exception:
                pass
        if not thread_name:
            try:
                if msg.reply_to_message and msg.reply_to_message.forum_topic_created:
                    thread_name = msg.reply_to_message.forum_topic_created.name
                    context.chat_data[f"thread_{thread_id}"] = thread_name
            except Exception:
                pass
        if not thread_name:
            thread_name = f"Ветка #{thread_id}"
        source = f"ветка #{thread_id}"
    else:
        thread_name = "Основной чат"
        source = "основной чат"
    add_message(username, msg.text, source=source, thread_name=thread_name)

async def cmd_namethred(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    await update.message.reply_text(
        f"✅ Этот чат установлен как основной для отчётов.\nID: `{chat_id}`",
        parse_mode="Markdown"
    )

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Собираю сообщения из всех веток и присылаю отчёт по каждой.\n\n"
        "/setmain — сделать этот чат главным для отчётов\n"
        "/namethread Название — дать имя текущей ветке\n"
        "/report — отчёт за сегодня\n"
        "/yesterday — отчёт за вчерашний день\n"
        "/count — сколько сообщений собрано\n"
        "/getid — узнать ID этого чата"
    )

async def cmd_getid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat.id
    thread_id = update.message.message_thread_id
    await update.message.reply_text(
        f"Chat ID: `{chat_id}`\nThread ID: `{thread_id or 'основной чат'}`",
        parse_mode="Markdown"
    )

async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    main_chat = load_main_chat()
    await update.message.reply_text("Анализирую все ветки за сегодня...")
    messages = get_today_messages()
    report = analyze_with_openai(messages)
    today = datetime.now(MOSCOW_TZ).date().strftime("%d.%m.%Y")
    target = main_chat if main_chat else update.message.chat.id
    await context.bot.send_message(chat_id=target, text=f"📊 Отчёт за {today}\n\n{report}")

async def cmd_yesterday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    main_chat = load_main_chat()
    await update.message.reply_text("Анализирую все ветки за вчера...")
    messages = get_yesterday_messages()
    report = analyze_with_openai(messages, label="вчера")
    yesterday = (datetime.now(MOSCOW_TZ) - timedelta(days=1)).date().strftime("%d.%m.%Y")
    target = main_chat if main_chat else update.message.chat.id
    await context.bot.send_message(chat_id=target, text=f"📊 Отчёт за {yesterday} (вчера)\n\n{report}")

async def cmd_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    messages = get_today_messages()
    grouped = group_messages_by_thread(messages)
    main_chat = load_main_chat()
    moscow_now = datetime.now(MOSCOW_TZ)
    status = "✅ Основной чат установлен" if main_chat else "⚠️ Основной чат не установлен — используй /setmain"
    lines = [f"📨 Сообщений за сегодня ({moscow_now.strftime('%d.%m.%Y')}): {len(messages)}\n{status}\n"]
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
    today = datetime.now(MOSCOW_TZ).date().strftime("%d.%m.%Y")
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
    app.add_handler(CommandHandler("yesterday", cmd_yesterday))
    app.add_handler(CommandHandler("count", cmd_count))
    app.add_handler(CommandHandler("namethread", cmd_namethred))
    app.add_handler(MessageHandler(filters.StatusUpdate.FORUM_TOPIC_CREATED, handle_forum_topic_created))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    job_queue = app.job_queue
    job_queue.run_daily(
        scheduled_report,
        time=time(hour=REPORT_HOUR, minute=REPORT_MINUTE, second=0, tzinfo=MOSCOW_TZ),
    )

    logger.info("Бот запущен!")
    app.run_polling(allowed_updates=["message"], drop_pending_updates=True)

if __name__ == "__main__":
    main()
