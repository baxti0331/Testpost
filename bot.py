import asyncio
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    CallbackQueryHandler, ConversationHandler, MessageHandler, filters
)
import asyncpg

TOKEN = os.getenv("TELEGRAM_TOKEN")
PORT = int(os.getenv("PORT", "8443"))
RENDER_HOST = os.getenv("RENDER_EXTERNAL_HOSTNAME")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DB_URL = os.getenv("DATABASE_URL")

WAITING_POST = 1
WAITING_TARGET = 2

# Работа с БД
async def get_pool():
    return await asyncpg.create_pool(dsn=DB_URL)

async def init_db(pool):
    await pool.execute("""
    CREATE TABLE IF NOT EXISTS posts (
        id SERIAL PRIMARY KEY,
        type TEXT,
        content TEXT,
        file_id TEXT,
        caption TEXT
    );
    CREATE TABLE IF NOT EXISTS targets (
        id SERIAL PRIMARY KEY,
        target TEXT UNIQUE
    );
    CREATE TABLE IF NOT EXISTS settings (
        id INTEGER PRIMARY KEY,
        repeat_interval INTEGER DEFAULT 0
    );
    INSERT INTO settings (id, repeat_interval)
    VALUES (1, 0)
    ON CONFLICT (id) DO NOTHING;
    """)

# Основной функционал

async def send_next_post(app, pool):
    posts = await pool.fetch("SELECT * FROM posts ORDER BY id")
    targets = await pool.fetch("SELECT target FROM targets")

    if not posts:
        print("[INFO] Очередь пустая.")
        return
    if not targets:
        print("[INFO] Нет каналов/групп для отправки.")
        return

    for post in posts:
        for t in targets:
            chat_id = t["target"]
            try:
                if post["type"] == "text":
                    await app.bot.send_message(chat_id, post["content"])
                elif post["type"] == "photo":
                    await app.bot.send_photo(chat_id, post["file_id"], caption=post["caption"])
                elif post["type"] == "video":
                    await app.bot.send_video(chat_id, post["file_id"], caption=post["caption"])
                elif post["type"] == "document":
                    await app.bot.send_document(chat_id, post["file_id"], caption=post["caption"])
            except Exception as e:
                print(f"[ERROR] Не удалось отправить в {chat_id}: {e}")

async def scheduler(app, pool):
    while True:
        row = await pool.fetchrow("SELECT repeat_interval FROM settings WHERE id=1")
        interval = row["repeat_interval"] if row else 0
        if interval > 0:
            await send_next_post(app, pool)
            await asyncio.sleep(interval * 60)
        else:
            await asyncio.sleep(5)

# Интерфейс

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_animation(
            animation="https://system365.pro/wp-content/uploads/2020/11/funkygoose-13.gif",
            caption=(
                "🔒 Упс! У тебя нет доступа к этому боту.\n\n"
                "Если нужен доступ — напиши @baxti_pm"
            )
        )
        return ConversationHandler.END

    await show_main_menu(update.message)

async def show_main_menu(message):
    keyboard = [
        [InlineKeyboardButton("➕ Добавить пост", callback_data="add_post")],
        [InlineKeyboardButton("📋 Посмотреть очередь", callback_data="show_queue")],
        [InlineKeyboardButton("🗑 Очистить очередь", callback_data="clear_queue")],
        [InlineKeyboardButton("➕ Добавить канал/группу", callback_data="add_target")],
        [InlineKeyboardButton("📋 Посмотреть каналы/группы", callback_data="show_targets")],
        [InlineKeyboardButton("⏱ Интервал 1 мин", callback_data="interval_1"),
         InlineKeyboardButton("⏱ Интервал 5 мин", callback_data="interval_5")],
        [InlineKeyboardButton("⏱ Интервал 10 мин", callback_data="interval_10"),
         InlineKeyboardButton("🚫 Остановить повторы", callback_data="interval_0")]
    ]
    await message.reply_text("Привет! Управляй автопостингом:", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data["pool"]
    query = update.callback_query
    await query.answer()

    if update.effective_user.id != ADMIN_ID:
        await query.answer("🔒 Нет доступа.", show_alert=True)
        return ConversationHandler.END

    if query.data == "add_post":
        await query.message.reply_text("Отправьте пост (текст/фото/видео/документ):")
        return WAITING_POST

    elif query.data == "show_queue":
        posts = await pool.fetch("SELECT * FROM posts ORDER BY id")
        if not posts:
            await query.message.edit_text("Очередь пуста.")
            return ConversationHandler.END

        text = "Очередь постов:\n"
        for idx, post in enumerate(posts):
            text += f"{idx+1}. {post['type'].capitalize()}"
            if post["type"] == "text":
                text += f": {post['content'][:30]}"
            if post["caption"]:
                text += f" ({post['caption'][:30]})"
            text += "\n"
        await query.message.edit_text(text)
        return ConversationHandler.END

    elif query.data == "clear_queue":
        await pool.execute("DELETE FROM posts")
        await query.message.edit_text("Очередь очищена.")
        return ConversationHandler.END

    elif query.data == "add_target":
        await query.message.reply_text("Отправь ID канала/группы или @username:")
        return WAITING_TARGET

    elif query.data == "show_targets":
        targets = await pool.fetch("SELECT target FROM targets")
        if not targets:
            await query.message.edit_text("Список каналов/групп пуст.")
            return ConversationHandler.END
        text = "Каналы/группы:\n\n"
        for idx, t in enumerate(targets):
            text += f"{idx+1}. {t['target']}\n"
        await query.message.edit_text(text)
        return ConversationHandler.END

    elif query.data.startswith("interval_"):
        interval = int(query.data.split("_")[1])
        await pool.execute("UPDATE settings SET repeat_interval=$1 WHERE id=1", interval)
        msg = "🚫 Автопостинг остановлен." if interval == 0 else f"🔁 Автопостинг каждые {interval} минут."
        await query.message.edit_text(msg)
        return ConversationHandler.END

    return ConversationHandler.END

async def post_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data["pool"]

    if update.message.text:
        await pool.execute("INSERT INTO posts (type, content) VALUES ('text', $1)", update.message.text)
    elif update.message.photo:
        file_id = update.message.photo[-1].file_id
        await pool.execute("INSERT INTO posts (type, file_id, caption) VALUES ('photo', $1, $2)",
                           file_id, update.message.caption or "")
    elif update.message.video:
        file_id = update.message.video.file_id
        await pool.execute("INSERT INTO posts (type, file_id, caption) VALUES ('video', $1, $2)",
                           file_id, update.message.caption or "")
    elif update.message.document:
        file_id = update.message.document.file_id
        await pool.execute("INSERT INTO posts (type, file_id, caption) VALUES ('document', $1, $2)",
                           file_id, update.message.caption or "")
    else:
        await update.message.reply_text("❗ Неподдерживаемый тип сообщения.")
        return ConversationHandler.END

    await update.message.reply_text("✅ Пост добавлен в очередь.")
    return ConversationHandler.END

async def target_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data["pool"]
    target = update.message.text.strip()
    await pool.execute("INSERT INTO targets (target) VALUES ($1) ON CONFLICT DO NOTHING", target)
    await update.message.reply_text(f"✅ {target} добавлен.")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Операция отменена.")
    return ConversationHandler.END

# Запуск
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler),
                      CommandHandler("start", start)],
        states={
            WAITING_POST: [MessageHandler(filters.ALL & ~filters.COMMAND, post_input)],
            WAITING_TARGET: [MessageHandler(filters.TEXT & ~filters.COMMAND, target_input)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(conv_handler)

    async def on_startup(app):
        pool = await get_pool()
        app.bot_data["pool"] = pool
        await init_db(pool)
        print("[INFO] Бот запущен.")
        asyncio.create_task(scheduler(app, pool))

    app.post_init = on_startup

    WEBHOOK_URL = f"https://{RENDER_HOST}/{TOKEN}"

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=WEBHOOK_URL
    )