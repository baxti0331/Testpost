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
ADMIN_ID = int(os.getenv("ADMIN_ID"))  # Админ ID

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
POSTS_FILE = os.path.join(BASE_DIR, "posts.json")
CHANNELS_FILE = os.path.join(BASE_DIR, "channels.json")

WAITING_POST = 1
WAITING_CHANNEL = 2

def is_admin(user_id):
    return user_id == ADMIN_ID

def load_posts():
    if not os.path.exists(POSTS_FILE):
        return {"posts": [], "repeat_interval": 0, "current_index": 0}
    with open(POSTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_posts(data):
    with open(POSTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_channels():
    if not os.path.exists(CHANNELS_FILE):
        return []
    with open(CHANNELS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_channels(channels):
    with open(CHANNELS_FILE, "w", encoding="utf-8") as f:
        json.dump(channels, f, ensure_ascii=False, indent=2)

async def send_next_post(app):
    data = load_posts()
    channels = load_channels()
    posts = data.get("posts", [])
    if not posts or not channels:
        print("[INFO] Очередь или список каналов пуст.")
        return

    index = data.get("current_index", 0)
    post = posts[index]

    for chat_id in channels:
        try:
            if post["type"] == "text":
                await app.bot.send_message(chat_id, post["content"])
            elif post["type"] == "photo":
                await app.bot.send_photo(chat_id, post["file_id"], caption=post.get("caption", ""))
            elif post["type"] == "video":
                await app.bot.send_video(chat_id, post["file_id"], caption=post.get("caption", ""))
            elif post["type"] == "document":
                await app.bot.send_document(chat_id, post["file_id"], caption=post.get("caption", ""))
        except Exception as e:
            print(f"[ERROR] Не удалось отправить в {chat_id}: {e}")

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
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Доступ запрещён.")
        return

    keyboard = [
        [InlineKeyboardButton("➕ Добавить пост", callback_data="add_post")],
        [InlineKeyboardButton("📋 Посмотреть очередь", callback_data="show_queue")],
        [InlineKeyboardButton("🗑 Очистить очередь", callback_data="clear_queue")],
        [InlineKeyboardButton("➕ Добавить канал/группу", callback_data="add_channel")],
        [InlineKeyboardButton("📺 Показать каналы", callback_data="show_channels")],
        [InlineKeyboardButton("⏱ Интервал 1 мин", callback_data="interval_1"),
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
    user_id = query.from_user.id

    if not is_admin(user_id):
        await query.answer("⛔ Доступ запрещён.", show_alert=True)
        return ConversationHandler.END

    await query.answer()
    data = load_posts()
    channels = load_channels()

    if query.data == "add_post":
        await query.message.edit_text("Отправьте мне сообщение, фото, видео или документ для добавления в очередь.\n\n🔙 /back — Назад")
        return WAITING_POST

    elif query.data == "show_queue":
        posts = data.get("posts", [])
        text = "Очередь постов:\n"
        if not posts:
            text += "Очередь пуста."
        else:
            for idx, post in enumerate(posts):
                text += f"{idx+1}. {post['type'].capitalize()}"
                if post["type"] == "text":
                    text += f": {post['content'][:30]}"
                if post.get("caption"):
                    text += f" ({post['caption'][:30]})"
                text += "\n"
        await query.message.edit_text(text + "\n\n🔙 /back — Назад")
        return ConversationHandler.END

    elif query.data == "clear_queue":
        data["posts"] = []
        data["current_index"] = 0
        save_posts(data)
        await query.message.edit_text("Очередь очищена.\n\n🔙 /back — Назад")
        return ConversationHandler.END

    elif query.data.startswith("interval_"):
        interval = int(query.data.split("_")[1])
        data["repeat_interval"] = interval
        save_posts(data)
        msg = "🚫 Автопостинг остановлен." if interval == 0 else f"🔁 Автопостинг каждые {interval} минут."
        await query.message.edit_text(msg + "\n\n🔙 /back — Назад")
        return ConversationHandler.END

    elif query.data == "add_channel":
        await query.message.edit_text("Отправь ID канала/группы (например: -1001234567890)\n\n🔙 /back — Назад")
        return WAITING_CHANNEL

    elif query.data == "show_channels":
        if not channels:
            text = "Список каналов пуст."
        else:
            text = "Каналы/группы для постинга:\n" + "\n".join(str(c) for c in channels)
        await query.message.edit_text(text + "\n\n🔙 /back — Назад")
        return ConversationHandler.END

    return ConversationHandler.END

async def post_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Доступ запрещён.")
        return ConversationHandler.END

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

    await update.message.reply_text("✅ Пост добавлен в очередь.\n\n🔙 /back — Назад")
    return ConversationHandler.END

async def channel_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Доступ запрещён.")
        return ConversationHandler.END

    text = update.message.text.strip()
    channels = load_channels()

    try:
        channel_id = int(text)
        if channel_id not in channels:
            channels.append(channel_id)
            save_channels(channels)
            await update.message.reply_text(f"✅ Канал {channel_id} добавлен.\n\n🔙 /back — Назад")
        else:
            await update.message.reply_text("⚠️ Канал уже в списке.\n\n🔙 /back — Назад")
    except:
        await update.message.reply_text("❗ Неверный формат ID.\n\n🔙 /back — Назад")

    return ConversationHandler.END

async def back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await start(update, context)

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler),
                      CommandHandler("start", start)],
        states={
            WAITING_POST: [MessageHandler(filters.ALL & ~filters.COMMAND, post_input)],
            WAITING_CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, channel_input)],
        },
        fallbacks=[CommandHandler("back", back)],
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