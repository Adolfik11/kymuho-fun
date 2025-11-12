# navi_bot_final.py
# Final launcher + extensions for the user's bot.
# - Requires original navi_bot.py to be in the same directory (preferred).
# - BOT_TOKEN is taken from environment variable BOT_TOKEN (Render-friendly).
# - Health server (uses original if present, else fallback), autoping every 5 minutes.
# - Admin ID (errors/messages): 6957241635
# - Adds: /profile (text), /trade, /market, /admin, /give, /broadcast, /clear_pvp, /myid (admin-only)
# - Global error handler sends traceback to admin via Telegram.

import os
import sys
import time
import threading
import asyncio
import logging
import urllib.request
from io import BytesIO

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ------ CONFIG ------
ADMIN_ID = 6957241635
ADMIN_IDS = {ADMIN_ID}

# Try to import original module (must be in same folder)
navi_bot = None
try:
    import importlib
    navi_bot = importlib.import_module("navi_bot")
    logging.getLogger(__name__).info("Imported existing navi_bot module.")
except Exception as e:
    logging.getLogger(__name__).warning("Could not import navi_bot.py: %s", e)
    navi_bot = None

# BOT TOKEN: prefer environment variable (Render)
BOT_TOKEN = os.getenv("BOT_TOKEN") or (getattr(navi_bot, "BOT_TOKEN", None) if navi_bot else None)
if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN not set in environment and not found in navi_bot.py. Exiting.")
    sys.exit(1)

# Health port
HEALTH_PORT = int(os.environ.get("PORT", 10000))

# Logging
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# In-memory market offers (simple)
MARKET = {}
_MARKET_COUNTER = 0
_MARKET_LOCK = threading.Lock()

# ---------- Health server ----------
def start_original_health_thread():
    """If original module provides start_health_check_server, use it in a thread. Else start fallback server."""
    if navi_bot and hasattr(navi_bot, "start_health_check_server"):
        try:
            t = threading.Thread(target=navi_bot.start_health_check_server, daemon=True)
            t.start()
            logger.info("Started original health check server in background thread.")
            return
        except Exception as e:
            logger.exception("Failed to start original health server: %s", e)

    # Fallback minimal HTTP server
    import http.server, socketserver

    class _Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/health":
                self.send_response(200)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                self.wfile.write(b"ok")
                logger.debug("Responded to health check")
            else:
                self.send_response(404)
                self.end_headers()
        def log_message(self, format, *args):
            return

    def _serve():
        try:
            with socketserver.TCPServer(("", HEALTH_PORT), _Handler) as httpd:
                logger.info("Fallback health server running on port %s", HEALTH_PORT)
                httpd.serve_forever()
        except Exception as e:
            logger.exception("Fallback health server error: %s", e)

    t = threading.Thread(target=_serve, daemon=True)
    t.start()
    logger.info("Started fallback health server thread.")

async def health_autoping_task(application: "Application", interval_sec: int = 300):
    """Ping local /health to keep platform instance warm."""
    url = f"http://127.0.0.1:{HEALTH_PORT}/health"
    logger.info("Autoping %s every %s sec", url, interval_sec)
    while True:
        try:
            def _ping():
                try:
                    with urllib.request.urlopen(url, timeout=10) as resp:
                        return resp.status
                except Exception as e:
                    return e
            res = await asyncio.to_thread(_ping)
            if isinstance(res, Exception):
                logger.debug("Health ping failed: %s", res)
            else:
                logger.debug("Health ping status: %s", res)
        except Exception as e:
            logger.exception("Autoping unexpected error: %s", e)
        await asyncio.sleep(interval_sec)

# ---------- Utilities ----------
async def send_admin_text(application, text: str):
    """Send text to admin(s) best-effort."""
    for aid in ADMIN_IDS:
        try:
            await application.bot.send_message(chat_id=aid, text=text)
        except Exception as e:
            logger.warning("Failed to send admin message to %s: %s", aid, e)

# ---------- New commands / handlers ----------

async def profile_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Text-only profile (Pillow not required)."""
    user = update.effective_user
    user_id = user.id
    # Try to use original module functions if present
    try:
        if navi_bot:
            balance = navi_bot.get_user_balance_safe(user_id)
            pvp_wins, pvp_losses = navi_bot.get_pvp_stats(user_id)
            coll_stats = navi_bot.get_collection_stats(user_id)
            league = "Бронза"
            if pvp_wins >= 20:
                league = "Платина"
            elif pvp_wins >= 10:
                league = "Золото"
            elif pvp_wins >= 5:
                league = "Серебро"
            text = (
                f"*Профиль — {user.first_name}*\n\n"
                f"• ID: `{user_id}`\n"
                f"• Баланс: `{balance}` монет\n"
                f"• PvP: `{pvp_wins}` побед / `{pvp_losses}` поражений\n"
                f"• Лига: *{league}*\n"
                f"• Всего персонажей: `{coll_stats.get('total', 0)}`\n"
            )
        else:
            text = (
                f"*Профиль — {user.first_name}*\n\n"
                f"• ID: `{user_id}`\n"
                f"• Модуль navi_bot отсутствует — данные недоступны.\n"
            )
    except Exception as e:
        logger.exception("Error building profile: %s", e)
        text = "Ошибка при получении профиля."
    await update.message.reply_text(text, parse_mode='Markdown')

async def market_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not MARKET:
        await update.message.reply_text("Рынок пуст.")
        return
    text = "*Текущие предложения:*\n"
    for oid, o in MARKET.items():
        text += f"• {oid}: {o['character']} (от {o['owner']})\n"
    await update.message.reply_text(text, parse_mode='Markdown')

async def trade_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /trade @username CharacterName"""
    msg = update.message
    user = update.effective_user
    args = context.args
    if not args or len(args) < 2:
        await msg.reply_text("Использование: /trade @username <ИмяПерсонажа>")
        return
    target = args[0]
    char_name = " ".join(args[1:])
    # resolve target id
    try:
        chat = await context.bot.get_chat(target)
        target_id = chat.id
    except Exception:
        await msg.reply_text("Не могу найти пользователя. Укажи через @username.")
        return
    # check owner has character
    if navi_bot:
        coll = navi_bot.get_user_collection(user.id)
        if not any(c["name"] == char_name for c in coll):
            await msg.reply_text("У тебя нет такого персонажа.")
            return
    else:
        await msg.reply_text("Функция трейда недоступна — отсутствует модуль navi_bot.")
        return

    global _MARKET_COUNTER
    with _MARKET_LOCK:
        _MARKET_COUNTER += 1
        offer_id = _MARKET_COUNTER
        MARKET[offer_id] = {"owner": user.id, "character": char_name, "created": time.time()}

    # send accept button to target
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    keyboard = [[InlineKeyboardButton(f"Принять {char_name}", callback_data=f"accept_trade_{offer_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        await context.bot.send_message(chat_id=target_id,
                                       text=f"Пользователь {user.first_name} предлагает тебе персонажа *{char_name}*.",
                                       parse_mode='Markdown',
                                       reply_markup=reply_markup)
        await msg.reply_text("Предложение отправлено.")
    except Exception as e:
        logger.warning("Cannot send trade offer: %s", e)
        await msg.reply_text("Не удалось отправить предложение (возможно, пользователь закрыл личку).")

async def accept_trade_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    try:
        offer_id = int(parts[2])
    except Exception:
        await query.message.reply_text("Неверный оффер.")
        return
    if offer_id not in MARKET:
        await query.message.reply_text("Оффер недоступен.")
        return
    offer = MARKET[offer_id]
    owner_id = offer["owner"]
    char_name = offer["character"]
    accepter_id = query.from_user.id
    if navi_bot:
        added = navi_bot.add_character_to_collection(accepter_id, char_name)
        if added:
            # try remove from owner if function exists
            removed = False
            if hasattr(navi_bot, "remove_character_from_collection"):
                try:
                    removed = navi_bot.remove_character_from_collection(owner_id, char_name)
                except Exception:
                    removed = False
            # notify owner
            try:
                await context.bot.send_message(chat_id=owner_id,
                                               text=f"Твой персонаж *{char_name}* был принят пользователем {query.from_user.first_name}.",
                                               parse_mode='Markdown')
            except Exception:
                pass
            del MARKET[offer_id]
            await query.message.reply_text(f"Ты получил персонажа *{char_name}*.", parse_mode='Markdown')
        else:
            await query.message.reply_text("Не удалось добавить персонажа (возможно, он у тебя уже есть).")
    else:
        await query.message.reply_text("Функция недоступна — отсутствует модуль navi_bot.")

# ---------- Admin commands ----------
def _is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS

async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not _is_admin(user.id):
        await update.message.reply_text("Доступ запрещён.")
        return
    text = (
        "Админ-панель:\n"
        "/give @username <amount> — выдать монеты\n"
        "/broadcast <message> — рассылка всем пользователям\n"
        "/clear_pvp — очистить PvP вызовы\n"
    )
    await update.message.reply_text(text)

async def give_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not _is_admin(user.id):
        await update.message.reply_text("Доступ запрещён.")
        return
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Использование: /give @username <amount>")
        return
    target = context.args[0]
    try:
        amount = int(context.args[1])
    except:
        await update.message.reply_text("Неверная сумма.")
        return
    try:
        member = await context.bot.get_chat(target)
        target_id = member.id
    except Exception:
        await update.message.reply_text("Не могу найти пользователя.")
        return
    if navi_bot:
        ok = navi_bot.update_user_balance_safe(target_id, amount)
        if ok:
            await update.message.reply_text(f"Выдано {amount} пользователю {target}.")
            try:
                await context.bot.send_message(chat_id=target_id, text=f"Админ выдал тебе {amount} монет.")
            except Exception:
                pass
        else:
            await update.message.reply_text("Ошибка при выдаче.")
    else:
        await update.message.reply_text("Функция недоступна — отсутствует модуль navi_bot.")

async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not _is_admin(user.id):
        await update.message.reply_text("Доступ запрещён.")
        return
    message = " ".join(context.args)
    if not message:
        await update.message.reply_text("Укажи сообщение для рассылки.")
        return
    if not navi_bot:
        await update.message.reply_text("Функция недоступна — отсутствует модуль navi_bot.")
        return
    try:
        conn = navi_bot.get_db_connection()
        c = conn.cursor()
        c.execute("SELECT user_id FROM users")
        rows = c.fetchall()
        conn.close()
        sent = 0
        for (uid,) in rows:
            try:
                await context.bot.send_message(chat_id=uid, text=message)
                sent += 1
            except Exception:
                continue
        await update.message.reply_text(f"Рассылка отправлена (~{sent}).")
    except Exception as e:
        logger.exception("Broadcast failed: %s", e)
        await update.message.reply_text("Ошибка при рассылке.")

async def clear_pvp_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not _is_admin(user.id):
        await update.message.reply_text("Доступ запрещён.")
        return
    if navi_bot:
        try:
            navi_bot.active_pvp_challenges.clear()
            navi_bot.pvp_team_selection.clear()
            await update.message.reply_text("PvP вызовы очищены.")
        except Exception as e:
            logger.exception("Error clearing pvp: %s", e)
            await update.message.reply_text("Ошибка при очистке PvP.")
    else:
        await update.message.reply_text("Функция недоступна — отсутствует модуль navi_bot.")

# ---------- myid (admin only) ----------
async def myid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not _is_admin(user.id):
        await update.message.reply_text("⛔ Команда недоступна.")
        return
    # show admin their id and also the message author's id if used in reply
    text = f"Ваш ID: `{user.id}`"
    await update.message.reply_text(text, parse_mode='Markdown')

# ---------- Global error handler ----------
async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Unhandled exception: %s", context.error)
    tb_text = f"⚠️ *Ошибка бота*\n`{context.error}`"
    try:
        if isinstance(update, Update) and update.effective_user:
            tb_text += f"\nUser: `{update.effective_user.id}`"
    except Exception:
        pass
    try:
        await send_admin_text(context.application, tb_text)
    except Exception:
        logger.exception("Failed to send error to admin")

# ---------- Register & start ----------
async def async_main():
    application = Application.builder().token(BOT_TOKEN).build()

    # Register original handlers (safe attempts)
    if navi_bot:
        try:
            application.add_handler(CommandHandler("start", navi_bot.start))
            # register known callback handlers similarly to original main
            application.add_handler(CallbackQueryHandler(navi_bot.check_subscription_handler, pattern="^check_subscription$"))
            application.add_handler(CallbackQueryHandler(navi_bot.menu_handler, pattern="^menu_(bet|balance|daily|leaderboard|stats|pvp|collection|shop|detailed_stats|season_leaderboard|achievements|referral)$"))
            application.add_handler(CallbackQueryHandler(navi_bot.menu_back_handler, pattern="^menu_back$"))
            application.add_handler(CallbackQueryHandler(navi_bot.bet_selection_handler, pattern="^bet_"))
            application.add_handler(CallbackQueryHandler(navi_bot.choose_fighter_handler, pattern="^(choose_1|choose_2)$"))
            application.add_handler(CallbackQueryHandler(navi_bot.cancel_bet_handler, pattern="^cancel_bet$"))
            application.add_handler(CallbackQueryHandler(navi_bot.buy_item_handler, pattern="^buy_"))
            application.add_handler(CallbackQueryHandler(navi_bot.pvp_create_handler, pattern="^pvp_create$"))
            application.add_handler(CallbackQueryHandler(navi_bot.pvp_accept_handler, pattern="^pvp_accept_"))
            application.add_handler(CallbackQueryHandler(navi_bot.pvp_decline_handler, pattern="^pvp_decline_"))
            application.add_handler(CallbackQueryHandler(navi_bot.pvp_cancel_handler, pattern="^pvp_cancel$"))
            application.add_handler(CallbackQueryHandler(navi_bot.pvp_select_character_handler, pattern="^pvp_select_"))
            application.add_handler(CallbackQueryHandler(navi_bot.pvp_confirm_team_handler, pattern="^pvp_confirm_"))
            application.add_handler(CallbackQueryHandler(navi_bot.pvp_cancel_battle_handler, pattern="^pvp_cancel_battle_"))
            logger.info("Registered original handlers where possible.")
        except Exception as e:
            logger.exception("Failed to register some original handlers: %s", e)

    # Register added handlers
    application.add_handler(CommandHandler("profile", profile_cmd))
    application.add_handler(CommandHandler("trade", trade_cmd))
    application.add_handler(CallbackQueryHandler(accept_trade_cb, pattern="^accept_trade_"))
    application.add_handler(CommandHandler("market", market_cmd))
    application.add_handler(CommandHandler("admin", admin_cmd))
    application.add_handler(CommandHandler("give", give_cmd))
    application.add_handler(CommandHandler("broadcast", broadcast_cmd))
    application.add_handler(CommandHandler("clear_pvp", clear_pvp_cmd))
    application.add_handler(CommandHandler("myid", myid_cmd))

    application.add_error_handler(global_error_handler)

    # Start health server thread (original or fallback)
    start_original_health_thread()

    # Start autoping task
    application.create_task(health_autoping_task(application, interval_sec=300))

    # init db if original provides
    if navi_bot and hasattr(navi_bot, "init_db"):
        try:
            navi_bot.init_db()
        except Exception as e:
            logger.warning("navi_bot.init_db() raised: %s", e)

    logger.info("Starting bot...")
    await application.initialize()
    await application.start()
    await application.updater.start_polling(poll_interval=3, timeout=30)

    # Daily season notify (best-effort) - optional background task
    async def daily_notify():
        while True:
            try:
                if navi_bot:
                    try:
                        conn = navi_bot.get_db_connection()
                        c = conn.cursor()
                        c.execute("SELECT user_id FROM users")
                        rows = c.fetchall()
                        conn.close()
                        for (uid,) in rows:
                            try:
                                await application.bot.send_message(chat_id=uid, text=f"🔔 Сегодня в сезоне {getattr(navi_bot, 'SEASON_NAME', '')} — сыграй и получи бонус!")
                            except Exception:
                                continue
                    except Exception as e:
                        logger.exception("daily_notify DB error: %s", e)
                else:
                    # no navi_bot -> skip
                    pass
            except Exception as e:
                logger.exception("daily_notify unexpected: %s", e)
            await asyncio.sleep(24 * 3600)

    application.create_task(daily_notify())

    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        logger.info("Shutting down")
        await application.updater.stop()
        await application.stop()
        await application.shutdown()

if __name__ == "__main__":
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.exception("Fatal launcher exception: %s", e)