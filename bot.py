import asyncio
import os
import hashlib
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

def get_bot_id(token):
    return hashlib.sha256(token.encode()).hexdigest()[:12]

BOT_ID = get_bot_id(TOKEN)

WAITING_POST = 1
WAITING_TARGET = 2

def back_button_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Орқага", callback_data="back_to_menu")]])

async def get_pool():
    return await asyncpg.create_pool(dsn=DB_URL)

async def init_db(pool):
    await pool.execute("""
    CREATE TABLE IF NOT EXISTS posts (
        id SERIAL PRIMARY KEY,
        bot_id TEXT,
        type TEXT,
        content TEXT,
        file_id TEXT,
        caption TEXT,
        chat_id BIGINT,
        message_id BIGINT
    );
    CREATE TABLE IF NOT EXISTS targets (
        id SERIAL PRIMARY KEY,
        bot_id TEXT,
        target TEXT,
        UNIQUE(bot_id, target)
    );
    CREATE TABLE IF NOT EXISTS settings (
        bot_id TEXT PRIMARY KEY,
        repeat_interval INTEGER DEFAULT 0
    );
    """)

async def send_next_post(app, pool):
    posts = await pool.fetch("SELECT * FROM posts WHERE bot_id=$1 ORDER BY id", BOT_ID)
    targets = await pool.fetch("SELECT target FROM targets WHERE bot_id=$1", BOT_ID)

    if not posts or not targets:
        return

    for post in posts:
        for t in targets:
            chat_id = t["target"]
            try:
                if post["chat_id"] and post["message_id"]:
                    await app.bot.copy_message(chat_id, post["chat_id"], post["message_id"])
                else:
                    if post["type"] == "text":
                        await app.bot.send_message(chat_id, post["content"])
                    elif post["type"] == "photo":
                        await app.bot.send_photo(chat_id, post["file_id"], caption=post["caption"])
                    elif post["type"] == "video":
                        await app.bot.send_video(chat_id, post["file_id"], caption=post["caption"])
                    elif post["type"] == "document":
                        await app.bot.send_document(chat_id, post["file_id"], caption=post["caption"])
            except Exception as e:
                print(f"[ХАТО] {chat_id} га юбориб бўлмади: {e}")

async def scheduler(app, pool):
    while True:
        row = await pool.fetchrow("SELECT repeat_interval FROM settings WHERE bot_id=$1", BOT_ID)
        interval = row["repeat_interval"] if row else 0
        if interval > 0:
            await send_next_post(app, pool)
            await asyncio.sleep(interval * 60)
        else:
            await asyncio.sleep(5)

async def show_main_menu(message):
    keyboard = [
        [InlineKeyboardButton("➕ Пост қўшиш", callback_data="add_post")],
        [InlineKeyboardButton("📋 Навбатни кўриш", callback_data="show_queue")],
        [InlineKeyboardButton("🗑 Навбатни тозалаш", callback_data="clear_queue")],
        [InlineKeyboardButton("➕ Канал/группа қўшиш", callback_data="add_target")],
        [InlineKeyboardButton("📋 Каналлар/группалар рўйхати", callback_data="show_targets")],
        [
            InlineKeyboardButton("⏱ 1 дақиқа", callback_data="interval_1"),
            InlineKeyboardButton("⏱ 5 дақиқа", callback_data="interval_5")
        ],
        [
            InlineKeyboardButton("⏱ 10 дақиқа", callback_data="interval_10"),
            InlineKeyboardButton("🚫 Қайтаришни тўхтатиш", callback_data="interval_0")
        ]
    ]
    await message.reply_text("Салом! Автопостингни бошқаринг:", reply_markup=InlineKeyboardMarkup(keyboard))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("🔒 Рухсат йўқ. Админ билан боғланинг: @postadminn1")
        return ConversationHandler.END

    await show_main_menu(update.message)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data["pool"]
    query = update.callback_query
    await query.answer()

    if update.effective_user.id != ADMIN_ID:
        await query.answer("🔒 Рухсат йўқ.", show_alert=True)
        return ConversationHandler.END

    if query.data == "add_post":
        await query.message.edit_text("Постни юборинг (матн/расм/видео/ҳужжат):", reply_markup=back_button_keyboard())
        return WAITING_POST

    elif query.data == "show_queue":
        posts = await pool.fetch("SELECT * FROM posts WHERE bot_id=$1 ORDER BY id", BOT_ID)
        if not posts:
            await query.message.edit_text("Навбат бўш.", reply_markup=back_button_keyboard())
            return ConversationHandler.END

        text = "Постлар навбати:\n\n"
        for idx, post in enumerate(posts):
            text += f"{idx+1}. {post['type'].capitalize()}"
            if post["type"] == "text":
                text += f": {post['content'][:30]}"
            if post["caption"]:
                text += f" ({post['caption'][:30]})"
            text += "\n"

        await query.message.edit_text(text, reply_markup=back_button_keyboard())
        return ConversationHandler.END

    elif query.data == "clear_queue":
        await pool.execute("DELETE FROM posts WHERE bot_id=$1", BOT_ID)
        await query.message.edit_text("Навбат тозаланди.", reply_markup=back_button_keyboard())
        return ConversationHandler.END

    elif query.data == "add_target":
        await query.message.edit_text("Канал ёки гуруҳ ID си ёки @username ни юборинг:", reply_markup=back_button_keyboard())
        return WAITING_TARGET

    elif query.data == "show_targets":
        targets = await pool.fetch("SELECT target FROM targets WHERE bot_id=$1", BOT_ID)
        if not targets:
            await query.message.edit_text("Каналлар/группалар рўйхати бўш.", reply_markup=back_button_keyboard())
            return ConversationHandler.END

        text = "Каналлар/группалар:\n\n"
        keyboard = []
        for t in targets:
            text += f"• {t['target']}\n"
            keyboard.append([InlineKeyboardButton(f"❌ Ўчириш {t['target']}", callback_data=f"del_target|{t['target']}")])

        keyboard.append([InlineKeyboardButton("⬅️ Орқага", callback_data="back_to_menu")])
        await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return ConversationHandler.END

    elif query.data.startswith("del_target|"):
        target_to_delete = query.data.split("|")[1]
        await pool.execute("DELETE FROM targets WHERE bot_id=$1 AND target=$2", BOT_ID, target_to_delete)
        await query.message.edit_text(f"{target_to_delete} ўчирилди.", reply_markup=back_button_keyboard())
        return ConversationHandler.END

    elif query.data.startswith("interval_"):
        interval = int(query.data.split("_")[1])
        await pool.execute("""
            INSERT INTO settings (bot_id, repeat_interval)
            VALUES ($1, $2)
            ON CONFLICT (bot_id) DO UPDATE SET repeat_interval=$2
        """, BOT_ID, interval)

        text = "Қайтариш тўхтатилди." if interval == 0 else f"Автопостинг интервали: {interval} дақиқа."
        await query.message.edit_text(text, reply_markup=back_button_keyboard())
        return ConversationHandler.END

    elif query.data == "back_to_menu":
        await show_main_menu(query.message)
        return ConversationHandler.END

    return ConversationHandler.END

async def post_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data["pool"]
    msg = update.message

    if msg.text:
        await pool.execute("""
            INSERT INTO posts (bot_id, type, content, chat_id, message_id)
            VALUES ($1, 'text', $2, $3, $4)
        """, BOT_ID, msg.text, msg.chat_id, msg.message_id)
    elif msg.photo:
        file_id = msg.photo[-1].file_id
        await pool.execute("""
            INSERT INTO posts (bot_id, type, file_id, caption, chat_id, message_id)
            VALUES ($1, 'photo', $2, $3, $4, $5)
        """, BOT_ID, file_id, msg.caption or "", msg.chat_id, msg.message_id)
    elif msg.video:
        file_id = msg.video.file_id
        await pool.execute("""
            INSERT INTO posts (bot_id, type, file_id, caption, chat_id, message_id)
            VALUES ($1, 'video', $2, $3, $4, $5)
        """, BOT_ID, file_id, msg.caption or "", msg.chat_id, msg.message_id)
    elif msg.document:
        file_id = msg.document.file_id
        await pool.execute("""
            INSERT INTO posts (bot_id, type, file_id, caption, chat_id, message_id)
            VALUES ($1, 'document', $2, $3, $4, $5)
        """, BOT_ID, file_id, msg.caption or "", msg.chat_id, msg.message_id)
    else:
        await msg.reply_text("❗ Қўллаб-қувватланмайдиган хабар тури.")
        return ConversationHandler.END

    await msg.reply_text("✅ Пост қўшилди.")
    await show_main_menu(msg)
    return ConversationHandler.END

async def target_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = context.bot_data["pool"]
    target = update.message.text.strip()
    await pool.execute("INSERT INTO targets (bot_id, target) VALUES ($1, $2) ON CONFLICT DO NOTHING", BOT_ID, target)
    await update.message.reply_text(f"✅ {target} қўшилди.")
    await show_main_menu(update.message)
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_main_menu(update.message)
    return ConversationHandler.END

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler), CommandHandler("start", start)],
        states={
            WAITING_POST: [
                MessageHandler(filters.ALL & ~filters.COMMAND, post_input),
                CallbackQueryHandler(button_handler)
            ],
            WAITING_TARGET: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, target_input),
                CallbackQueryHandler(button_handler)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(conv_handler)

    async def on_startup(app):
        pool = await get_pool()
        app.bot_data["pool"] = pool
        await init_db(pool)
        print("[МАЪЛУМОТ] Бот ишга тушди.")
        asyncio.create_task(scheduler(app, pool))

    app.post_init = on_startup

    WEBHOOK_URL = f"https://{RENDER_HOST}/{TOKEN}"

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=WEBHOOK_URL
    )