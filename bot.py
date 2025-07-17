import asyncio
import json
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, ContextTypes,
    CallbackQueryHandler, ConversationHandler, MessageHandler, filters
)

TOKEN = os.getenv("TELEGRAM_TOKEN")
PORT = int(os.getenv("PORT", "8443"))
RENDER_HOST = os.getenv("RENDER_EXTERNAL_HOSTNAME")
CHAT_ID = int(os.getenv("CHAT_ID"))

if not TOKEN or not RENDER_HOST or not CHAT_ID:
    raise ValueError("Нужно указать TELEGRAM_TOKEN, CHAT_ID и RENDER_EXTERNAL_HOSTNAME!")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
POSTS_FILE = os.path.join(BASE_DIR, "posts.json")

WAITING_POST = 1

def load_posts():
    if not os.path.exists(POSTS_FILE):
        return {"posts": [], "repeat_interval": 0, "current_index": 0}
    with open(POSTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_posts(data):
    with open(POSTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

async def send_next_post(app):
    data = load_posts()
    posts = data.get("posts", [])
    if not posts:
        print("[INFO] Очередь пустая, ничего не отправляю.")
        return

    index = data.get("current_index", 0)
    post = posts[index]

    try:
        if post["type"] == "text":
            await app.bot.send_message(CHAT_ID, post["content"])
        elif post["type"] == "photo":
            await app.bot.send_photo(CHAT_ID, post["file_id"], caption=post.get("caption", ""))
        elif post["type"] == "video":
            await app.bot.send_video(CHAT_ID, post["file_id"], caption=post.get("caption", ""))
        elif post["type"] == "document":
            await app.bot.send_document(CHAT_ID, post["file_id"], caption=post.get("caption", ""))
    except Exception as e:
        print(f"[ERROR] Не удалось отправить пост: {e}")

    data["current_index"] = (index + 1) % len(posts)
    save_posts(data)

async def scheduler(app):
    while True:
        data = load_posts()
        interval = data.get("repeat_interval", 0)
        if interval > 0:
            await send_next_post(app)
            await asyncio.sleep(interval * 60)
        else:
            await asyncio.sleep(5)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("➕ Добавить пост", callback_data="add_post")],
        [InlineKeyboardButton("📋 Посмотреть очередь", callback_data="show_queue")],
        [InlineKeyboardButton("🗑 Очистить очередь", callback_data="clear_queue")],
        [InlineKeyboardButton("⏱ 1 мин", callback_data="interval_1"),
         InlineKeyboardButton("⏱ 2 мин", callback_data="interval_2")],
        [InlineKeyboardButton("⏱ 5 мин", callback_data="interval_5"),
         InlineKeyboardButton("⏱ 10 мин", callback_data="interval_10")],
        [InlineKeyboardButton("⏱ 15 мин", callback_data="interval_15"),
         InlineKeyboardButton("⏱ 20 мин", callback_data="interval_20")],
        [InlineKeyboardButton("🚫 Остановить повторы", callback_data="interval_0")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Привет! Управляй автопостингом через кнопки:", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = load_posts()

    if query.data == "add_post":
        await query.message.reply_text("Отправьте мне сообщение, фото, видео или документ для добавления в очередь:")
        return WAITING_POST

    elif query.data == "show_queue":
        posts = data.get("posts", [])
        if not posts:
            await query.message.edit_text("Очередь пуста.")
            return ConversationHandler.END
        text = "Очередь постов:\n"
        for idx, post in enumerate(posts):
            text += f"{idx+1}. {post['type'].capitalize()}"
            if post["type"] == "text":
                text += f": {post['content'][:30]}"
            if post.get("caption"):
                text += f" ({post['caption'][:30]})"
            text += "\n"
        await query.message.edit_text(text)
        return ConversationHandler.END

    elif query.data == "clear_queue":
        data["posts"] = []
        data["current_index"] = 0
        save_posts(data)
        await query.message.edit_text("Очередь очищена.")
        return ConversationHandler.END

    elif query.data.startswith("interval_"):
        interval = int(query.data.split("_")[1])
        data["repeat_interval"] = interval
        save_posts(data)
        if interval == 0:
            msg = "🚫 Автопостинг остановлен."
        else:
            msg = f"🔁 Автопостинг каждые {interval} минут."
        await query.message.edit_text(msg)
        return ConversationHandler.END

    return ConversationHandler.END

async def post_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_posts()
    posts = data.get("posts", [])

    if update.message.text:
        posts.append({"type": "text", "content": update.message.text})
    elif update.message.photo:
        file_id = update.message.photo[-1].file_id
        posts.append({"type": "photo", "file_id": file_id, "caption": update.message.caption or ""})
    elif update.message.video:
        file_id = update.message.video.file_id
        posts.append({"type": "video", "file_id": file_id, "caption": update.message.caption or ""})
    elif update.message.document:
        file_id = update.message.document.file_id
        posts.append({"type": "document", "file_id": file_id, "caption": update.message.caption or ""})
    else:
        await update.message.reply_text("❗ Неподдерживаемый тип сообщения.")
        return ConversationHandler.END

    data["posts"] = posts
    save_posts(data)

    await update.message.reply_text("Пост добавлен в очередь.")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Операция отменена.")
    return ConversationHandler.END

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler),
                      CommandHandler("start", start)],
        states={
            WAITING_POST: [MessageHandler(filters.ALL & ~filters.COMMAND, post_input)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(conv_handler)

    async def on_startup(app):
        print("[INFO] Бот запущен.")
        asyncio.create_task(scheduler(app))

    app.post_init = on_startup

    WEBHOOK_PATH = f"/{TOKEN}"
    WEBHOOK_URL = f"https://{RENDER_HOST}/{TOKEN}"

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=WEBHOOK_URL
    )