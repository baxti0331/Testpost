import asyncio
import datetime
import json
import os
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes
)
import aioschedule

# Переменные окружения
TOKEN = os.getenv("TELEGRAM_TOKEN")
PORT = int(os.getenv("PORT", "8443"))
RENDER_HOST = os.getenv('RENDER_EXTERNAL_HOSTNAME')
CHAT_ID = int(os.getenv("CHAT_ID"))

if not TOKEN or not RENDER_HOST or not CHAT_ID:
    raise ValueError("Нужно указать TELEGRAM_TOKEN, CHAT_ID и RENDER_EXTERNAL_HOSTNAME!")

SCHEDULE_FILE = "schedule.json"

# Работа с расписанием
def load_schedule():
    if not os.path.exists(SCHEDULE_FILE):
        return []
    with open(SCHEDULE_FILE, "r") as f:
        return json.load(f)

def save_schedule(times):
    with open(SCHEDULE_FILE, "w") as f:
        json.dump(times, f)

# Автопостинг
async def send_post(app):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    await app.bot.send_message(CHAT_ID, f"🚀 Автопост {now}")

async def scheduler(app):
    while True:
        await aioschedule.run_pending()
        await asyncio.sleep(1)

def setup_schedule(app):
    aioschedule.clear()
    times = load_schedule()
    for t in times:
        aioschedule.every().day.at(t).do(send_post, app)

# Команды
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Бот запущен!\n"
                                    "/addtime HH:MM - добавить время\n"
                                    "/showtimes - показать расписание\n"
                                    "/removetime HH:MM - удалить время")

async def addtime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❗ Используй формат: /addtime HH:MM")
        return

    time = context.args[0]
    try:
        datetime.datetime.strptime(time, "%H:%M")
        times = load_schedule()
        if time not in times:
            times.append(time)
            times.sort()
            save_schedule(times)
            setup_schedule(context.application)
            await update.message.reply_text(f"Время {time} добавлено.")
        else:
            await update.message.reply_text("Это время уже есть.")
    except:
        await update.message.reply_text("❗ Неверный формат времени. Пример: /addtime 12:30")

async def showtimes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    times = load_schedule()
    if times:
        await update.message.reply_text("📅 Расписание:\n" + "\n".join(times))
    else:
        await update.message.reply_text("Расписание пустое.")

async def removetime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❗ Используй формат: /removetime HH:MM")
        return

    time = context.args[0]
    times = load_schedule()
    if time in times:
        times.remove(time)
        save_schedule(times)
        setup_schedule(context.application)
        await update.message.reply_text(f"Время {time} удалено.")
    else:
        await update.message.reply_text("Такого времени нет.")

# Основной запуск
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("addtime", addtime))
    app.add_handler(CommandHandler("showtimes", showtimes))
    app.add_handler(CommandHandler("removetime", removetime))

    WEBHOOK_PATH = f"/{TOKEN}"
    WEBHOOK_URL = f"https://{RENDER_HOST}{WEBHOOK_PATH}"

    async def on_startup(app):
        print(f"Устанавливаю вебхук: {WEBHOOK_URL}")
        await app.bot.set_webhook(WEBHOOK_URL)
        setup_schedule(app)
        asyncio.create_task(scheduler(app))

    app.post_init = on_startup

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=WEBHOOK_URL
    )
