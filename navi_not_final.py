# navi_bot_final.py
# Final launcher + extensions for the user's bot.
# - Works together with original navi_bot.py if present (preferred).
# - If original module present, uses its DB, functions and tables.
# - Adds: async health-check, autoping, MarkdownV2-safe messages,
#   trade that really moves characters (deletes from owner's collection),
#   admin tools, daily season notify, profile (text), and error reports to admin.
#
# Usage:
#  - Put this file in the same directory as navi_bot.py (recommended).
#  - Set environment variable BOT_TOKEN (Render Dashboard -> Environment).
#  - Start: python navi_bot_final.py
#
# Admin (owner) id:
ADMIN_ID = 6957241635
ADMIN_IDS = {ADMIN_ID}

import os
import sys
import time
import threading
import asyncio
import logging
import re
import sqlite3
import urllib.request
from io import BytesIO
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# Logging setup
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Try to import original bot module if present
navi_bot = None
try:
    import importlib
    navi_bot = importlib.import_module("navi_bot")
    logger.info("Imported navi_bot module.")
except Exception as e:
    logger.warning("Could not import navi_bot.py: %s", e)
    navi_bot = None

# BOT token (prefer env)
BOT_TOKEN = os.getenv("BOT_TOKEN") or (getattr(navi_bot, "BOT_TOKEN", None) if navi_bot else None)
if not BOT_TOKEN:
    logger.error("BOT_TOKEN not set (env or in navi_bot.py). Exiting.")
    sys.exit(1)

# Health port (Render often provides PORT)
HEALTH_PORT = int(os.environ.get("PORT", 10000))

# ----------------- Utilities -----------------

def escape_md(text: str) -> str:
    """
    Escape text for MarkdownV2.
    Telegram MarkdownV2 special characters: _ * [ ] ( ) ~ ` > # + - = | { } . !
    """
    if text is None:
        return ""
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!])', r'\\\1', str(text))

async def send_admin_text(application: Application, text: str):
    """Send text to admin(s). Best-effort."""
    for aid in ADMIN_IDS:
        try:
            await application.bot.send_message(chat_id=aid, text=text)
        except Exception as e:
            logger.warning("Failed to send admin message to %s: %s", aid, e)

def get_db_conn_from_original() -> Optional[sqlite3.Connection]:
    """
    Try to obtain DB connection using original module helper.
    Return sqlite3.Connection or None.
    """
    if navi_bot and hasattr(navi_bot, "get_db_connection"):
        try:
            return navi_bot.get_db_connection()
        except Exception as e:
            logger.warning("Original get_db_connection failed: %s", e)
            return None
    # if original module not present, try default 'bot.db'
    try:
        conn = sqlite3.connect("bot.db", check_same_thread=False)
        return conn
    except Exception as e:
        logger.error("Failed to open fallback DB: %s", e)
        return None

def remove_character_in_db(user_id: int, character_name: str) -> bool:
    """
    Remove a character row from collections table for user_id.
    Returns True if deletion attempted (and committed).
    This function is safe even if original module has its own implementation.
    """
    # Prefer original's helper if exists
    if navi_bot and hasattr(navi_bot, "remove_character_from_collection"):
        try:
            return navi_bot.remove_character_from_collection(user_id, character_name)
        except Exception as e:
            logger.warning("navi_bot.remove_character_from_collection raised: %s", e)
            # fallback to DB operation below

    conn = get_db_conn_from_original()
    if not conn:
        return False
    try:
        c = conn.cursor()
        c.execute("DELETE FROM collections WHERE user_id=? AND character_name=? LIMIT 1", (user_id, character_name))
        conn.commit()
        # Note: SQLite doesn't support LIMIT in DELETE before v3.25; if error, do without LIMIT
    except sqlite3.OperationalError:
        try:
            c.execute("DELETE FROM collections WHERE user_id=? AND character_name=?", (user_id, character_name))
            conn.commit()
        except Exception as e:
            logger.exception("Failed to delete character (fallback): %s", e)
            try:
                conn.close()
            except:
                pass
            return False
    except Exception as e:
        logger.exception("Failed to delete character: %s", e)
        try:
            conn.close()
        except:
            pass
        return False
    try:
        conn.close()
    except:
        pass
    return True

# ----------------- Health server & autoping -----------------

def start_original_health_thread():
    """
    Start original health-check server (if function exists) or fallback simple HTTP server.
    """
    if navi_bot and hasattr(navi_bot, "start_health_check_server"):
        try:
            t = threading.Thread(target=navi_bot.start_health_check_server, daemon=True)
            t.start()
            logger.info("Started original health_check_server in background thread.")
            return
        except Exception as e:
            logger.warning("Failed starting original health server: %s", e)

    # Fallback server
    import http.server, socketserver

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/health":
                self.send_response(200)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                self.wfile.write(b"ok")
            else:
                self.send_response(404)
                self.end_headers()
        def log_message(self, format, *args):
            return

    def serve():
        try:
            with socketserver.TCPServer(("", HEALTH_PORT), Handler) as httpd:
                logger.info("Fallback health server running on port %s", HEALTH_PORT)
                httpd.serve_forever()
        except Exception as e:
            logger.exception("Fallback health server error: %s", e)

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    logger.info("Started fallback health server thread.")

async def health_autoping_task(application: Application, interval_sec: int = 300):
    """Ping local /health periodically to keep process warm on Render."""
    url = f"http://127.0.0.1:{HEALTH_PORT}/health"
    logger.info("Autoping %s every %s seconds", url, interval_sec)
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

# ----------------- In-memory market -----------------

MARKET = {}
_MARKET_COUNTER = 0
_MARKET_LOCK = threading.Lock()

# ----------------- Handlers: profile, trade, market, admin -----------------

def _get_league_by_wins(wins: int) -> str:
    if wins >= 20:
        return "Платина"
    if wins >= 10:
        return "Золото"
    if wins >= 5:
        return "Серебро"
    return "Бронза"

async def profile_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /profile - shows own profile
    /profile @username OR /profile <id> - for admin only, shows other's profile
    """
    user = update.effective_user
    args = context.args or []

    # identify target
    target_id = user.id
    target_name = user.username or user.first_name

    if args:
        # admin-only usage
        if user.id not in ADMIN_IDS:
            await update.message.reply_text("⚠️ Только админ может смотреть чужие профили.")
            return
        q = args[0]
        if q.isdigit():
            target_id = int(q)
        elif q.startswith("@"):
            uname = q[1:]
            # try to resolve username to id via DB if original module has mapping
            if navi_bot and hasattr(navi_bot, "get_user_id_by_username"):
                target_id = navi_bot.get_user_id_by_username(uname) or target_id
            else:
                # best-effort: try Telegram get_chat
                try:
                    chat = await context.bot.get_chat(q)
                    target_id = chat.id
                except Exception:
                    # cannot resolve
                    await update.message.reply_text("❌ Не удалось найти пользователя по username.")
                    return
        else:
            await update.message.reply_text("Неверный формат. Используй /profile @username или /profile <id>.")
            return

    # gather stats (use original if available)
    try:
        if navi_bot:
            balance = navi_bot.get_user_balance_safe(target_id)
            pvp_wins, pvp_losses = (0, 0)
            try:
                pvp_wins, pvp_losses = navi_bot.get_pvp_stats(target_id)
            except Exception:
                # fallback if returns dict etc.
                try:
                    p = navi_bot.get_pvp_stats(target_id)
                    if isinstance(p, dict):
                        pvp_wins = p.get("wins", 0)
                        pvp_losses = p.get("losses", 0)
                except:
                    pass
            coll_stats = {}
            try:
                coll_stats = navi_bot.get_collection_stats(target_id)
            except Exception:
                collection = navi_bot.get_user_collection(target_id)
                coll_stats = {"total": len(collection) if collection else 0}
            achievements = []
            try:
                achievements = navi_bot.get_user_achievements(target_id)
            except Exception:
                achievements = []
            referral = {}
            try:
                referral = navi_bot.get_referral_stats(target_id)
            except Exception:
                referral = {"referrals_count": 0}
        else:
            balance = 0
            pvp_wins = pvp_losses = 0
            coll_stats = {"total": 0}
            achievements = []
            referral = {"referrals_count": 0}
    except Exception as e:
        logger.exception("Error collecting profile data: %s", e)
        balance = 0; pvp_wins = pvp_losses = 0; coll_stats = {"total": 0}; achievements = []; referral = {"referrals_count": 0}

    league = _get_league_by_wins(pvp_wins)

    text = f"*👤 ПРОФИЛЬ {escape_md(str(target_name))}*\n\n"
    if target_id != user.id and user.id in ADMIN_IDS:
        text = f"*👤 ПРОФИЛЬ игрока (ID `{target_id}`)*\n\n"
    text += (
        f"💰 *Баланс:* `{balance}` монет\n"
        f"⚔️ *PvP:* `{pvp_wins}` побед / `{pvp_losses}` поражений\n"
        f"🏅 *Лига:* *{escape_md(league)}*\n"
        f"📚 *Коллекция:* `{coll_stats.get('total', 0)}` персонажей\n"
        f"🎯 *Достижения:* `{len(achievements)}`\n"
        f"👥 *Рефералы:* `{referral.get('referrals_count', 0)}`\n"
    )
    await update.message.reply_text(text, parse_mode='MarkdownV2')

async def market_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not MARKET:
        await update.message.reply_text("Рынок пуст.")
        return
    text = "*Текущие предложения:*\n"
    for oid, o in MARKET.items():
        text += f"• `{oid}`: {escape_md(o['character'])} (от `{o['owner']}`)\n"
    await update.message.reply_text(text, parse_mode='MarkdownV2')

async def trade_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /trade @username CharacterName
    Creates an offer and sends button to target to accept.
    """
    msg = update.message
    user = update.effective_user
    args = context.args or []
    if not args or len(args) < 2:
        await msg.reply_text("Использование: /trade @username <ИмяПерсонажа>")
        return
    target = args[0]
    char_name = " ".join(args[1:]).strip()
    # resolve target id
    try:
        chat = await context.bot.get_chat(target)
        target_id = chat.id
    except Exception:
        await msg.reply_text("Не могу найти пользователя. Укажи через @username.")
        return

    # check owner has character
    if navi_bot:
        try:
            coll = navi_bot.get_user_collection(user.id)
            if not any(c.get("name", c) == char_name or c == char_name for c in coll):
                await msg.reply_text("У тебя нет такого персонажа.")
                return
        except Exception:
            # If get_user_collection has different format, try best-effort via DB
            conn = get_db_conn_from_original()
            if conn:
                try:
                    c = conn.cursor()
                    c.execute("SELECT 1 FROM collections WHERE user_id=? AND character_name=? LIMIT 1", (user.id, char_name))
                    row = c.fetchone()
                    conn.close()
                    if not row:
                        await msg.reply_text("У тебя нет такого персонажа.")
                        return
                except Exception:
                    pass
            else:
                await msg.reply_text("Не могу проверить коллекцию (DB не доступна).")
                return
    else:
        await msg.reply_text("Трейд недоступен — модуль navi_bot отсутствует.")
        return

    # create market offer
    global _MARKET_COUNTER
    with _MARKET_LOCK:
        _MARKET_COUNTER += 1
        offer_id = _MARKET_COUNTER
        MARKET[offer_id] = {"owner": user.id, "character": char_name, "created": time.time()}

    # send accept button to target
    keyboard = [[InlineKeyboardButton(f"Принять {char_name}", callback_data=f"accept_trade_{offer_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    try:
        text = f"Пользователь {escape_md(user.first_name)} предлагает тебе персонажа *{escape_md(char_name)}*."
        await context.bot.send_message(chat_id=target_id, text=text, parse_mode='MarkdownV2', reply_markup=reply_markup)
        await msg.reply_text("Предложение отправлено.")
    except Exception as e:
        logger.warning("Cannot send trade offer: %s", e)
        await msg.reply_text("Не удалось отправить предложение (возможно, пользователь запретил сообщения от бота).")

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

    # Add character to accepter
    added = False
    try:
        if navi_bot:
            added = navi_bot.add_character_to_collection(accepter_id, char_name)
        else:
            # fallback: insert into collections table
            conn = get_db_conn_from_original()
            if conn:
                try:
                    c = conn.cursor()
                    c.execute("INSERT OR IGNORE INTO collections (user_id, character_name) VALUES (?, ?)", (accepter_id, char_name))
                    conn.commit()
                    conn.close()
                    added = True
                except Exception as e:
                    logger.exception("Fallback add character failed: %s", e)
    except Exception as e:
        logger.exception("Error adding character to accepter: %s", e)

    if not added:
        await query.message.reply_text("Не удалось добавить персонажа (возможно, он у тебя уже есть).")
        return

    # Remove from owner
    removed = remove_character_in_db(owner_id, char_name)

    # notify owner
    try:
        await context.bot.send_message(chat_id=owner_id,
                                       text=f"Твой персонаж *{escape_md(char_name)}* был передан пользователю {escape_md(query.from_user.first_name)}.",
                                       parse_mode='MarkdownV2')
    except Exception:
        pass

    # clean offer
    try:
        del MARKET[offer_id]
    except KeyError:
        pass

    await query.message.reply_text(f"Ты получил персонажа *{escape_md(char_name)}*.", parse_mode='MarkdownV2')

# ----------------- Admin commands -----------------

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
        "/market — список рыночных предложений\n"
        "/trade @username <name> — предложить персонажа\n"
        "/profile <@username|id> — посмотреть профиль другого игрока\n"
    )
    await update.message.reply_text(text)

async def give_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not _is_admin(user.id):
        await update.message.reply_text("Доступ запрещён.")
        return
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text("Использование: /give @username <amount>")
        return
    target = args[0]
    try:
        amount = int(args[1])
    except Exception:
        await update.message.reply_text("Неверная сумма.")
        return
    # resolve user
    try:
        member = await context.bot.get_chat(target)
        target_id = member.id
    except Exception:
        await update.message.reply_text("Не могу найти пользователя.")
        return
    if navi_bot:
        ok = navi_bot.update_user_balance_safe(target_id, amount)
        if ok:
            await update.message.reply_text(f"Выдал {amount} монет пользователю {target}.")
            try:
                await context.bot.send_message(chat_id=target_id, text=f"Админ выдал тебе {amount} монет.")
            except Exception:
                pass
        else:
            await update.message.reply_text("Ошибка при выдаче.")
    else:
        await update.message.reply_text("Функция недоступна — модуль navi_bot отсутствует.")

async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not _is_admin(user.id):
        await update.message.reply_text("Доступ запрещён.")
        return
    message = " ".join(context.args or [])
    if not message:
        await update.message.reply_text("Укажи сообщение для рассылки.")
        return
    if not navi_bot:
        await update.message.reply_text("Функция недоступна — модуль navi_bot отсутствует.")
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
            logger.exception("Error clearing PvP: %s", e)
            await update.message.reply_text("Ошибка при очистке PvP.")
    else:
        await update.message.reply_text("Функция недоступна — модуль navi_bot отсутствует.")

async def myid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin-only: show your id (and useful for admin checks)"""
    user = update.effective_user
    if not _is_admin(user.id):
        await update.message.reply_text("⛔ Команда недоступна.")
        return
    text = f"Ваш ID: `{user.id}`"
    await update.message.reply_text(text, parse_mode='MarkdownV2')

# ----------------- Global error handler -----------------

async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Unhandled exception: %s", context.error)
    msg = f"⚠️ *Ошибка бота*\n`{escape_md(str(context.error))}`"
    try:
        if isinstance(update, Update) and update.effective_user:
            msg += f"\nUser: `{update.effective_user.id}`"
    except Exception:
        pass
    try:
        await send_admin_text(context.application, msg)
    except Exception:
        logger.exception("Failed to send error to admin")

# ----------------- Register & start -----------------

async def async_main():
    application = Application.builder().token(BOT_TOKEN).build()

    # Try register original handlers (safe attempts)
    if navi_bot:
        try:
            application.add_handler(CommandHandler("start", navi_bot.start))
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
            logger.info("Registered original handlers.")
        except Exception as e:
            logger.exception("Error registering original handlers: %s", e)

    # Register new/extended handlers
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

    # start health server thread
    start_original_health_thread()

    # start autoping background task
    application.create_task(health_autoping_task(application, interval_sec=300))

    # init DB if original provides init_db
    if navi_bot and hasattr(navi_bot, "init_db"):
        try:
            navi_bot.init_db()
        except Exception as e:
            logger.warning("navi_bot.init_db() raised: %s", e)

    logger.info("Starting bot...")
    await application.initialize()
    await application.start()
    await application.updater.start_polling(poll_interval=3, timeout=30)

    # daily season notify (best-effort)
    async def daily_notify():
        while True:
            try:
                if navi_bot and hasattr(navi_bot, "get_db_connection"):
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
                    # no original module -> skip sending
                    pass
            except Exception as e:
                logger.exception("daily_notify unexpected: %s", e)
            await asyncio.sleep(24 * 3600)

    application.create_task(daily_notify())

    # keep running
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        logger.info("Shutting down...")
        await application.updater.stop()
        await application.stop()
        await application.shutdown()

if __name__ == "__main__":
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        logger.info("Stopped by user")
    except Exception as e:
        logger.exception("Fatal launcher exception: %s", e)