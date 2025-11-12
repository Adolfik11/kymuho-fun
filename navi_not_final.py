# navi_bot_final.py
# Finetuned final version for @kymuho_fun_bot
# Admin ID: 6957241635
# Uses MarkdownV2 safely (no BadRequest), no Pillow, full escape for dynamic text.

import os
import sys
import time
import asyncio
import threading
import logging
import re
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# === CONFIG ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = {6957241635}
HEALTH_PORT = int(os.environ.get("PORT", 10000))

# === LOGGER ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# === MARKDOWN ESCAPE ===
def escape_md(text: str) -> str:
    if text is None:
        return ""
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!])', r'\\\1', str(text))

# === IMPORT ORIGINAL BOT ===
try:
    import navi_bot
    logger.info("✅ Original navi_bot imported successfully.")
except Exception as e:
    navi_bot = None
    logger.warning("⚠️ Failed to import navi_bot: %s", e)

# === SIMPLE DB ACCESS FALLBACK ===
def get_db():
    try:
        if navi_bot and hasattr(navi_bot, "get_db_connection"):
            return navi_bot.get_db_connection()
        return sqlite3.connect("bot.db", check_same_thread=False)
    except Exception as e:
        logger.warning("DB connection failed: %s", e)
        return None

# === HEALTH CHECK SERVER ===
def start_health_server():
    import http.server, socketserver
    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/health":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")
            else:
                self.send_response(404)
                self.end_headers()
        def log_message(self, *a): pass
    def run():
        with socketserver.TCPServer(("", HEALTH_PORT), Handler) as srv:
            logger.info("🌐 Health server running on %s", HEALTH_PORT)
            srv.serve_forever()
    threading.Thread(target=run, daemon=True).start()

async def health_ping():
    import urllib.request
    while True:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{HEALTH_PORT}/health", timeout=5) as r:
                if r.status == 200:
                    logger.debug("Health ping ok")
        except Exception:
            pass
        await asyncio.sleep(300)

# === PROFILE COMMAND ===
async def profile_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args or []
    target_id = user.id
    target_name = user.username or user.first_name

    # Allow admin to view others
    if args:
        if user.id not in ADMIN_IDS:
            await update.message.reply_text("⚠️ Только админ может смотреть чужие профили.")
            return
        q = args[0]
        if q.isdigit():
            target_id = int(q)
        elif q.startswith("@"):
            uname = q[1:]
            if navi_bot and hasattr(navi_bot, "get_user_id_by_username"):
                tid = navi_bot.get_user_id_by_username(uname)
                if tid: target_id = tid
        else:
            await update.message.reply_text("❌ Формат: /profile @username или /profile <id>")
            return

    try:
        balance = navi_bot.get_user_balance_safe(target_id)
        pvp = navi_bot.get_pvp_stats(target_id)
        if isinstance(pvp, dict):
            wins = pvp.get("wins", 0)
            losses = pvp.get("losses", 0)
        else:
            wins, losses = pvp if isinstance(pvp, (tuple, list)) else (0, 0)
        refs = navi_bot.get_referral_stats(target_id)
        achs = navi_bot.get_user_achievements(target_id)
        col = navi_bot.get_user_characters(target_id)
    except Exception as e:
        logger.warning("Profile data error: %s", e)
        balance = 0; wins=losses=0; refs={"referrals_count":0}; achs=[]; col=[]

    def league(w): return "🏆 Платина" if w>=20 else "🥇 Золото" if w>=10 else "🥈 Серебро" if w>=5 else "🥉 Бронза"

    txt = f"*👤 Профиль игрока*\n\n"
    if user.id in ADMIN_IDS and target_id != user.id:
        txt += f"📜 ID: `{target_id}`\n\n"
    txt += (
        f"💬 Имя: {escape_md(target_name)}\n"
        f"💰 Баланс: `{balance}` монет\n"
        f"⚔️ Побед: `{wins}` / Поражений: `{losses}`\n"
        f"🏅 Лига: *{escape_md(league(wins))}*\n"
        f"📚 Персонажей: `{len(col)}`\n"
        f"🎯 Достижений: `{len(achs)}`\n"
        f"👥 Рефералов: `{refs.get('referrals_count', 0)}`"
    )
    await update.message.reply_text(txt, parse_mode="MarkdownV2")

# === TRADE SYSTEM (SAFE MARKDOWN) ===
MARKET = {}
async def trade_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user = update.effective_user
    args = context.args or []
    if len(args) < 2:
        await msg.reply_text("Использование: /trade @username <ИмяПерсонажа>")
        return
    target = args[0]
    char = " ".join(args[1:])
    try:
        chat = await context.bot.get_chat(target)
        tid = chat.id
    except Exception:
        await msg.reply_text("❌ Пользователь не найден.")
        return

    # Проверка наличия персонажа
    try:
        coll = navi_bot.get_user_characters(user.id)
        if char not in coll:
            await msg.reply_text("❌ У тебя нет такого персонажа.")
            return
    except Exception:
        pass

    offer_id = len(MARKET)+1
    MARKET[offer_id] = {"from": user.id, "char": char}
    kb = [[InlineKeyboardButton(f"Принять {char}", callback_data=f"accept_{offer_id}")]]
    txt = f"Игрок {escape_md(user.first_name)} предлагает тебе *{escape_md(char)}*."
    await context.bot.send_message(tid, txt, parse_mode="MarkdownV2", reply_markup=InlineKeyboardMarkup(kb))
    await msg.reply_text("✅ Предложение отправлено.")

async def accept_trade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    try:
        offer_id = int(q.data.split("_")[1])
    except:
        await q.message.reply_text("Ошибка оффера.")
        return
    if offer_id not in MARKET:
        await q.message.reply_text("❌ Предложение устарело.")
        return
    offer = MARKET.pop(offer_id)
    char = offer["char"]
    frm = offer["from"]
    uid = q.from_user.id
    try:
        navi_bot.add_character_to_collection(uid, char)
        navi_bot.remove_character_from_collection(frm, char)
        await q.message.reply_text(f"Ты получил *{escape_md(char)}*.", parse_mode="MarkdownV2")
        await context.bot.send_message(frm, f"🎁 Твой персонаж *{escape_md(char)}* передан другому игроку.", parse_mode="MarkdownV2")
    except Exception as e:
        logger.warning("Trade error: %s", e)
        await q.message.reply_text("⚠️ Ошибка при обмене.")

# === ADMIN COMMANDS ===
def is_admin(uid): return uid in ADMIN_IDS

async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Нет доступа.")
        return
    txt = (
        "🛠 *Админ команды:*\n"
        "/give @username <сумма>\n"
        "/broadcast <текст>\n"
        "/clear_pvp\n"
        "/market\n"
        "/trade @username <персонаж>\n"
        "/profile <id>"
    )
    await update.message.reply_text(txt, parse_mode="MarkdownV2")

async def give_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return await update.message.reply_text("Нет доступа.")
    args = context.args or []
    if len(args) < 2: return await update.message.reply_text("Использование: /give @username <сумма>")
    target, amount = args[0], int(args[1])
    chat = await context.bot.get_chat(target)
    ok = navi_bot.update_user_balance_safe(chat.id, amount)
    if ok:
        await update.message.reply_text("✅ Выдано.")
        await context.bot.send_message(chat.id, f"🎁 Тебе выдали `{amount}` монет.", parse_mode="MarkdownV2")
    else:
        await update.message.reply_text("Ошибка.")

# === MAIN ===
async def main():
    app = Application.builder().token(BOT_TOKEN).build()
    # Original handlers
    if navi_bot:
        try:
            app.add_handler(CommandHandler("start", navi_bot.start))
            app.add_handler(CallbackQueryHandler(navi_bot.menu_handler, pattern="^menu_"))
        except Exception as e: logger.warning(e)

    # New
    app.add_handler(CommandHandler("profile", profile_cmd))
    app.add_handler(CommandHandler("trade", trade_cmd))
    app.add_handler(CallbackQueryHandler(accept_trade, pattern="^accept_"))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("give", give_cmd))

    start_health_server()
    app.create_task(health_ping())
    await app.initialize()
    await app.start()
    await app.updater.start_polling(poll_interval=3, timeout=30)
    logger.info("🤖 Bot started as @kymuho_fun_bot")
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped.")
