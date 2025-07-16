import asyncio
import datetime
import json
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    CallbackQueryHandler, ConversationHandler, MessageHandler, filters
)
import aioschedule
import pytz

TOKEN = os.getenv("TELEGRAM_TOKEN")
PORT = int(os.getenv("PORT", "8443"))
RENDER_HOST = os.getenv("RENDER_EXTERNAL_HOSTNAME")
CHAT_ID = int(os.getenv("CHAT_ID"))

if not TOKEN or not RENDER_HOST or not CHAT_ID:
    raise ValueError("Нужно указать TELEGRAM_TOKEN, CHAT_ID и RENDER_EXTERNAL_HOSTNAME!")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCHEDULE_FILE = os.path.join(BASE_DIR, "schedule.json")
print(f"Файл расписания будет использоваться по пути: {SCHEDULE_FILE}")

MoscowTZ = pytz.timezone("Europe/Moscow")
WAITING_TIME = 1

def load_schedule():
    if not os.path.exists(SCHEDULE_FILE):
        return []
    try:
        with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            print(f"[INFO] Загружено расписание: {data}")
            return data
    except Exception as e:
        print(f"[ERROR] Не удалось загрузить расписание: {e}")
        return []

def save_schedule(times):
    try:
        with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
            json.dump(times, f, ensure_ascii=False, indent=2)
        print(f"[INFO] Расписание сохранено: {times}")
    except Exception as e:
        print(f"[ERROR] Не удалось сохранить расписание: {e}")

LOCAL_TZ = datetime.datetime.now().astimezone().tzinfo

def schedule_time_msk_to_local(time_str):
    now = datetime.datetime.now(tz=MoscowTZ)
    hh, mm = map(int, time_str.split(":"))
    dt_msk = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    dt_local = dt_msk.astimezone(LOCAL_TZ)
    return dt_local.strftime("%H:%M")

async def send_post(app):
    now_msk = datetime.datetime.now(MoscowTZ).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[LOG] Отправляю автопост по МСК: {now_msk}")
    await app.bot.send_message(CHAT_ID, f"🚀 Автопост по МСК: {now_msk}")

async def scheduler(app):
    while True:
        await aioschedule.run_pending()
        await asyncio.sleep(1)

def setup_schedule(app):
    aioschedule.clear()
    times = load_schedule()
    print(f"[DEBUG] Настраиваю расписание с временами: {times}")
    for t in times:
        local_time = schedule_time_msk_to_local(t)
        print(f"[LOG] Запланирован автопост в локальное время сервера: {local_time} (МСК: {t})")
        aioschedule.every().day.at(local_time).do(send_post, app)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Добавить время", callback_data="add_time")],
        [InlineKeyboardButton("Показать расписание", callback_data="show_times")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Привет! Управляй автопостингом через кнопки:", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "add_time":
        await query.message.reply_text("Введите время в формате ЧЧ:ММ (МСК):")
        return WAITING_TIME

    elif query.data == "show_times":
        times = load_schedule()
        if not times:
            await query.message.edit_text("Расписание пустое.")
            return ConversationHandler.END
        buttons = []
        for t in times:
            buttons.append([InlineKeyboardButton(f"Удалить {t}", callback_data=f"del_{t}")])
        buttons.append([InlineKeyboardButton("Назад", callback_data="back")])
        await query.message.edit_text("Текущее расписание:", reply_markup=InlineKeyboardMarkup(buttons))
        return ConversationHandler.END

    elif query.data.startswith("del_"):
        t = query.data[4:]
        times = load_schedule()
        if t in times:
            times.remove(t)
            save_schedule(times)
            setup_schedule(context.application)
            await query.message.edit_text(f"Время {t} удалено.")
        else:
            await query.message.edit_text("Такого времени нет.")
        return ConversationHandler.END

    elif query.data == "back":
        keyboard = [
            [InlineKeyboardButton("Добавить время", callback_data="add_time")],
            [InlineKeyboardButton("Показать расписание", callback_data="show_times")]
        ]
        await query.message.edit_text("Управляй автопостингом через кнопки:", reply_markup=InlineKeyboardMarkup(keyboard))
        return ConversationHandler.END

async def time_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        datetime.datetime.strptime(text, "%H:%M")
    except ValueError:
        await update.message.reply_text("❗ Неверный формат! Введите время в формате ЧЧ:ММ")
        return WAITING_TIME

    times = load_schedule()

    if text in times:
        await update.message.reply_text("Это время уже есть в расписании.")
        return ConversationHandler.END

    times.append(text)
    times.sort()
    save_schedule(times)

    setup_schedule(context.application)

    await update.message.reply_text(f"Время {text} добавлено в расписание.")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Операция отменена.")
    return ConversationHandler.END

if __name__ == "__main__":
    from telegram.ext import ConversationHandler

    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern="^(add_time|show_times|del_|back)"),
                      CommandHandler("start", start)],
        states={
            WAITING_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, time_input)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(conv_handler)

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