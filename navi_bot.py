import logging
import random
import os
import sqlite3
import datetime
import time
import signal
import sys
import asyncio
import threading
import http.server
import socketserver
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# === КОНФИГУРАЦИЯ ===
BOT_TOKEN = "8578378221:AAHCZqygYGaDFqEbqSnVaORiHf2QF44RNWU"

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Глобальные словари для хранения активных PvP вызовов и битв
active_pvp_challenges = {}
active_pvp_battles = {}
pvp_team_selection = {}

# Блокировки для thread-safe операций с балансом
balance_locks = {}
lock = threading.Lock()

# === Health Check Server ===
class HealthCheckHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'Bot is alive')
            logger.info("Health check passed")
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        # Отключаем стандартное логирование HTTP запросов
        return

def start_health_check_server():
    """Запускает простой HTTP сервер для health checks"""
    PORT = int(os.environ.get('PORT', 10000))
    try:
        with socketserver.TCPServer(("", PORT), HealthCheckHandler) as httpd:
            logger.info(f"Health check server running on port {PORT}")
            httpd.serve_forever()
    except Exception as e:
        logger.error(f"Health check server error: {e}")

# === БАЗА ДАННЫХ ===
def get_db_connection():
    """Безопасное подключение к БД"""
    try:
        conn = sqlite3.connect('navi_bot.db', check_same_thread=False)
        return conn
    except sqlite3.Error as e:
        logger.error(f"Database connection error: {e}")
        raise

def init_db():
    """Инициализация базы данных"""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users
                     (user_id INTEGER PRIMARY KEY, 
                      username TEXT, 
                      score INTEGER DEFAULT 0, 
                      last_activity TEXT,
                      games_played INTEGER DEFAULT 0, 
                      balance INTEGER DEFAULT 100,
                      pvp_wins INTEGER DEFAULT 0, 
                      pvp_losses INTEGER DEFAULT 0)''')
        conn.commit()
        logger.info("Database initialized successfully")
    except sqlite3.Error as e:
        logger.error(f"Database initialization error: {e}")
        raise
    finally:
        conn.close()

def get_user_lock(user_id):
    """Получаем или создаем блокировку для пользователя"""
    with lock:
        if user_id not in balance_locks:
            balance_locks[user_id] = threading.Lock()
        return balance_locks[user_id]

def update_user_score(user_id, username, points):
    """Обновление счета пользователя"""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        today = datetime.datetime.now().isoformat()
        
        # ПРОВЕРЯЕМ СУЩЕСТВОВАНИЕ ПОЛЬЗОВАТЕЛЯ
        c.execute('SELECT 1 FROM users WHERE user_id = ?', (user_id,))
        if not c.fetchone():
            # СОЗДАЕМ НОВОГО ПОЛЬЗОВАТЕЛЯ
            c.execute('''INSERT INTO users 
                         (user_id, username, score, last_activity, balance) 
                         VALUES (?, ?, ?, ?, 100)''',
                      (user_id, username, points, today))
        else:
            # ОБНОВЛЯЕМ СУЩЕСТВУЮЩЕГО
            c.execute('''UPDATE users SET 
                         score = score + ?,
                         games_played = games_played + 1,
                         last_activity = ?,
                         username = ?
                         WHERE user_id = ?''',
                      (points, today, username, user_id))
        
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Error updating user score: {e}")
    finally:
        conn.close()

def update_user_balance(user_id, amount):
    """Обновление баланса пользователя с проверкой"""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        
        # ГАРАНТИРУЕМ СУЩЕСТВОВАНИЕ ПОЛЬЗОВАТЕЛЯ
        c.execute('INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 100)', (user_id,))
        conn.commit()
        
        # Проверяем, не уйдет ли баланс в минус
        if amount < 0:
            c.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
            result = c.fetchone()
            if result and result[0] < abs(amount):
                return False  # Недостаточно средств
        
        c.execute('''UPDATE users SET balance = balance + ? 
                     WHERE user_id = ?''', (amount, user_id))
        conn.commit()
        return True
    except sqlite3.Error as e:
        logger.error(f"Error updating balance: {e}")
        return False
    finally:
        conn.close()

def update_user_balance_safe(user_id, amount):
    """Безопасное обновление баланса с блокировкой"""
    user_lock = get_user_lock(user_id)
    with user_lock:
        return update_user_balance(user_id, amount)

def get_user_balance(user_id):
    """Получение баланса пользователя"""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
        result = c.fetchone()
        return result[0] if result else 100
    except sqlite3.Error as e:
        logger.error(f"Error getting user balance: {e}")
        return 100
    finally:
        conn.close()

def get_user_balance_safe(user_id):
    """Безопасное получение баланса с блокировкой"""
    user_lock = get_user_lock(user_id)
    with user_lock:
        return get_user_balance(user_id)

def update_pvp_stats(winner_id, loser_id):
    """Обновление PvP статистики"""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        
        # ГАРАНТИРУЕМ СУЩЕСТВОВАНИЕ ПОЛЬЗОВАТЕЛЕЙ
        c.execute('INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 100)', (winner_id,))
        c.execute('INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 100)', (loser_id,))
        conn.commit()
        
        # ОБНОВЛЯЕМ СТАТИСТИКУ
        c.execute('UPDATE users SET pvp_wins = pvp_wins + 1 WHERE user_id = ?', (winner_id,))
        c.execute('UPDATE users SET pvp_losses = pvp_losses + 1 WHERE user_id = ?', (loser_id,))
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Error updating PvP stats: {e}")
    finally:
        conn.close()

def get_pvp_stats(user_id):
    """Получение PvP статистики"""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        
        # ГАРАНТИРУЕМ СУЩЕСТВОВАНИЕ ПОЛЬЗОВАТЕЛЯ
        c.execute('INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 100)', (user_id,))
        conn.commit()
        
        c.execute('SELECT pvp_wins, pvp_losses FROM users WHERE user_id = ?', (user_id,))
        result = c.fetchone()
        return (result[0], result[1]) if result else (0, 0)
    except sqlite3.Error as e:
        logger.error(f"Error getting PvP stats: {e}")
        return (0, 0)
    finally:
        conn.close()

def get_leaderboard():
    """Получение таблицы лидеров"""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute('''SELECT username, balance, score 
                     FROM users 
                     ORDER BY balance DESC 
                     LIMIT 10''')
        return [tuple(row) for row in c.fetchall()]
    except sqlite3.Error as e:
        logger.error(f"Error getting leaderboard: {e}")
        return []
    finally:
        conn.close()

def get_user_rank(user_id):
    """Получение позиции пользователя в рейтинге"""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        
        # ПРОВЕРЯЕМ, СУЩЕСТВУЕТ ЛИ ПОЛЬЗОВАТЕЛЬ
        c.execute('SELECT 1 FROM users WHERE user_id = ?', (user_id,))
        if not c.fetchone():
            return 1  # Если пользователя нет, считаем его первым
        
        c.execute('''SELECT COUNT(*) + 1 FROM users WHERE balance > 
                     (SELECT balance FROM users WHERE user_id = ?)''', 
                  (user_id,))
        result = c.fetchone()
        return result[0] if result else 1
    except sqlite3.Error as e:
        logger.error(f"Error getting user rank: {e}")
        return 1
    finally:
        conn.close()

def can_get_daily_reward(user_id):
    """Проверяет, может ли пользователь получить ежедневную награду"""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute('SELECT last_activity FROM users WHERE user_id = ?', (user_id,))
        result = c.fetchone()
        
        if not result or not result[0]:
            return True  # Если нет данных о последней активности, можно получить награду
        
        last_activity = datetime.datetime.fromisoformat(result[0])
        now = datetime.datetime.now()
        
        # Проверяем, прошло ли более 24 часов
        return (now - last_activity).total_seconds() >= 24 * 3600
    except Exception as e:
        logger.error(f"Error checking daily reward: {e}")
        return True
    finally:
        conn.close()

async def safe_edit_message(query, text, reply_markup=None, parse_mode='Markdown'):
    """Безопасное обновление сообщения с обработкой ошибок"""
    try:
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
        return True
    except Exception as e:
        logger.error(f"Error editing message: {e}")
        # Пытаемся отправить новое сообщение как fallback
        try:
            await query.message.reply_text(
                text=text,
                parse_mode=parse_mode
            )
            return True
        except Exception as e2:
            logger.error(f"Error sending fallback message: {e2}")
            return False

# === ДАННЫЕ ПЕРСОНАЖЕЙ ===
CHARACTERS = {
    "Кафка": {"universe": "Honkai: Star Rail", "power": 85},
    "Блейд": {"universe": "Honkai: Star Rail", "power": 82},
    "Дан Хэн": {"universe": "Honkai: Star Rail", "power": 78},
    "Серебряный Волк": {"universe": "Honkai: Star Rail", "power": 80},
    "Клара": {"universe": "Honkai: Star Rail", "power": 75},
    "Зеле": {"universe": "Honkai: Star Rail", "power": 77},
    "Вельт": {"universe": "Honkai: Star Rail", "power": 88},
    "Гепард": {"universe": "Honkai: Star Rail", "power": 84},
    "Янцин": {"universe": "Honkai: Star Rail", "power": 79},
    "Силвер": {"universe": "Honkai: Star Rail", "power": 81},
    "Химеко": {"universe": "Honkai: Star Rail", "power": 83},
    "Херта": {"universe": "Honkai: Star Rail", "power": 76},
    "Лоча": {"universe": "Honkai: Star Rail", "power": 82},
    "Тиньюнь": {"universe": "Honkai: Star Rail", "power": 78},
    "Сушан": {"universe": "Honkai: Star Rail", "power": 77},
    
    "Райдэн": {"universe": "Genshin Impact", "power": 90},
    "Чжун Ли": {"universe": "Genshin Impact", "power": 89},
    "Дилюк": {"universe": "Genshin Impact", "power": 82},
    "Гань Юй": {"universe": "Genshin Impact", "power": 85},
    "Нахида": {"universe": "Genshin Impact", "power": 87},
    "Венти": {"universe": "Genshin Impact", "power": 83},
    "Эола": {"universe": "Genshin Impact", "power": 81},
    "Кэ Цин": {"universe": "Genshin Impact", "power": 79},
    "Ху Тао": {"universe": "Genshin Impact", "power": 86},
    "Аяка": {"universe": "Genshin Impact", "power": 84},
    "Кокоми": {"universe": "Genshin Impact", "power": 82},
    "Альбедо": {"universe": "Genshin Impact", "power": 80},
    "Кли": {"universe": "Genshin Impact", "power": 78},
    "Мона": {"universe": "Genshin Impact", "power": 81},
    "Тарталья": {"universe": "Genshin Impact", "power": 85},
    
    "Киана": {"universe": "Honkai Impact 3rd", "power": 95},
    "Мэй": {"universe": "Honkai Impact 3rd", "power": 88},
    "Броня": {"universe": "Honkai Impact 3rd", "power": 86},
    "Тереза": {"universe": "Honkai Impact 3rd", "power": 84},
    "Фу Хуа": {"universe": "Honkai Impact 3rd", "power": 89},
    "Сирин": {"universe": "Honkai Impact 3rd", "power": 92},
    "Дуриан": {"universe": "Honkai Impact 3rd", "power": 83},
    "Рита": {"universe": "Honkai Impact 3rd", "power": 85},
    "Лилли": {"universe": "Honkai Impact 3rd", "power": 82},
    "Зория": {"universe": "Honkai Impact 3rd", "power": 80},
    "Ай-Чан": {"universe": "Honkai Impact 3rd", "power": 87},
    "Равен": {"universe": "Honkai Impact 3rd", "power": 81},
    "Гризео": {"universe": "Honkai Impact 3rd", "power": 79},
    "Пардо": {"universe": "Honkai Impact 3rd", "power": 78},
    "Вилли": {"universe": "Honkai Impact 3rd", "power": 84},
    
    "Билли": {"universe": "Zenless Zone Zero", "power": 78},
    "Никки": {"universe": "Zenless Zone Zero", "power": 76},
    "Соломон": {"universe": "Zenless Zone Zero", "power": 82},
    "Алекс": {"universe": "Zenless Zone Zero", "power": 79},
    "Бен": {"universe": "Zenless Zone Zero", "power": 77},
    "Короленок": {"universe": "Zenless Zone Zero", "power": 75},
    "Эллен": {"universe": "Zenless Zone Zero", "power": 80},
    "Люси": {"universe": "Zenless Zone Zero", "power": 78},
    "Пипер": {"universe": "Zenless Zone Zero", "power": 76},
    "Коллат": {"universe": "Zenless Zone Zero", "power": 81},
    "Антонио": {"universe": "Zenless Zone Zero", "power": 77},
    "Савада": {"universe": "Zenless Zone Zero", "power": 79},
    "Миюки": {"universe": "Zenless Zone Zero", "power": 75},
    "Хосокава": {"universe": "Zenless Zone Zero", "power": 80},
    "Джейн": {"universe": "Zenless Zone Zero", "power": 78}
}

UNIVERSE_EMOJIS = {
    "Honkai: Star Rail": "🎮",
    "Genshin Impact": "🌍",
    "Honkai Impact 3rd": "⚡",
    "Zenless Zone Zero": "🏙️"
}

# === ОСНОВНЫЕ КОМАНДЫ ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user = update.effective_user
    balance = get_user_balance_safe(user.id)
    
    keyboard = [
        [InlineKeyboardButton("🎰 Сделать ставку", callback_data="menu_bet")],
        [InlineKeyboardButton("⚔️ PvP с другом", callback_data="menu_pvp")],
        [InlineKeyboardButton("💰 Мой баланс", callback_data="menu_balance")],
        [InlineKeyboardButton("📅 Ежедневная награда", callback_data="menu_daily")],
        [InlineKeyboardButton("🏆 Таблица лидеров", callback_data="menu_leaderboard")],
        [InlineKeyboardButton("📊 Моя статистика", callback_data="menu_stats")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"""*Привет, {user.first_name}!* 👋

🎰 *Добро пожаловать в систему ставок на битвы персонажей!*

*Твой баланс:* `{balance}` монет 💰

*Выбери действие:*""",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик меню"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "menu_bet":
        await bet_command_from_menu(query, context)
    elif query.data == "menu_balance":
        await balance_command_from_menu(query, context)
    elif query.data == "menu_daily":
        await daily_command_from_menu(query, context)
    elif query.data == "menu_leaderboard":
        await leaderboard_command_from_menu(query, context)
    elif query.data == "menu_stats":
        await stats_command(query, context)
    elif query.data == "menu_pvp":
        await pvp_command_from_menu(query, context)

async def balance_command_from_menu(query, context):
    """Проверить баланс"""
    user = query.from_user
    balance = get_user_balance_safe(user.id)
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="menu_back")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await safe_edit_message(query,
        f"*💰 ТВОЙ БАЛАНС:* `{balance}` монет\n\n"
        f"*Используй кнопки ниже для ставок!*",
        reply_markup=reply_markup
    )

async def daily_command_from_menu(query, context):
    """Ежедневная награда"""
    user = query.from_user
    
    # ПРОВЕРЯЕМ, МОЖНО ЛИ ПОЛУЧИТЬ НАГРАДУ
    if not can_get_daily_reward(user.id):
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="menu_back")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await safe_edit_message(query,
            "*⏰ ЕЖЕДНЕВНАЯ НАГРАДА* ⏰\n\n"
            "*Уже получена!* ❌\n\n"
            "Приходи за новой наградой через 24 часа! ⏳\n\n"
            f"*Текущий баланс:* `{get_user_balance_safe(user.id)}` монет 💰",
            reply_markup=reply_markup
        )
        return
    
    daily_reward = random.randint(50, 150)
    
    # ГАРАНТИРУЕМ, ЧТО ПОЛЬЗОВАТЕЛЬ СУЩЕСТВУЕТ В БАЗЕ
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute('INSERT OR IGNORE INTO users (user_id, username, balance) VALUES (?, ?, 100)', 
                  (user.id, user.username))
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Error ensuring user exists for daily reward: {e}")
    finally:
        conn.close()
    
    # ОБНОВЛЯЕМ БАЛАНС И СЧЕТ
    success = update_user_balance_safe(user.id, daily_reward)
    if success:
        update_user_score(user.id, user.username, 3)
        
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="menu_back")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await safe_edit_message(query,
            f"*📅 ЕЖЕДНЕВНАЯ НАГРАДА* 📅\n\n"
            f"*Игрок:* {user.first_name}\n"
            f"*Награда:* +{daily_reward} монет 💰\n\n"
            f"*Новый баланс:* `{get_user_balance_safe(user.id)}` монет\n\n"
            f"*Следующая награда через 24 часа!* ⏰",
            reply_markup=reply_markup
        )
    else:
        await safe_edit_message(query, "*❌ Ошибка при получении награды!*")

async def leaderboard_command_from_menu(query, context):
    """Таблица лидеров по балансу"""
    top_users = get_leaderboard()
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="menu_back")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if not top_users:
        await safe_edit_message(query,
            "*🏆 ТАБЛИЦА ЛИДЕРОВ* 🏆\n\n"
            "*Пока здесь пусто!*\n\n"
            "Стань первым в рейтинге! 🎯\n"
            "• Делай ставки через 🎰\n" 
            "• Получай ежедневные награды 📅\n"
            "• Выигрывай и поднимайся в топ! 💰\n\n"
            "*Твой баланс:* `{}` монет".format(get_user_balance_safe(query.from_user.id)),
            reply_markup=reply_markup
        )
        return
    
    leaderboard_text = "*🏆 ТОП-10 БОГАЧЕЙ* 🏆\n\n"
    
    for i, (username, balance, score) in enumerate(top_users, 1):
        medal = ""
        if i == 1: medal = "🥇"
        elif i == 2: medal = "🥈" 
        elif i == 3: medal = "🥉"
        else: medal = "💰"
        
        display_name = username if username else f"Игрок {i}"
        leaderboard_text += f"{medal} *{i}. {display_name}*\n"
        leaderboard_text += f"   Баланс: `{balance}` монет | Очки: `{score}`\n\n"
    
    # Получаем текущую позицию пользователя
    user_rank = get_user_rank(query.from_user.id)
    user_balance = get_user_balance_safe(query.from_user.id)
    
    leaderboard_text += f"*Твоя позиция:* #{user_rank} (Баланс: `{user_balance}` монет)"
    
    await safe_edit_message(query, leaderboard_text, reply_markup)

async def stats_command(query, context):
    """Статистика пользователя"""
    user = query.from_user
    balance = get_user_balance_safe(user.id)
    pvp_wins, pvp_losses = get_pvp_stats(user.id)
    total_pvp = pvp_wins + pvp_losses
    winrate = (pvp_wins / total_pvp * 100) if total_pvp > 0 else 0
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="menu_back")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await safe_edit_message(query,
        f"*📊 ТВОЯ СТАТИСТИКА* 📊\n\n"
        f"*Баланс:* `{balance}` монет 💰\n"
        f"*PvP побед:* `{pvp_wins}` 🏆\n"
        f"*PvP поражений:* `{pvp_losses}` 💀\n"
        f"*Винрейт:* `{winrate:.1f}%` 📈\n\n"
        f"*Всего PvP битв:* `{total_pvp}` ⚔️",
        reply_markup=reply_markup
    )

async def menu_back_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    balance = get_user_balance_safe(user.id)
    
    keyboard = [
        [InlineKeyboardButton("🎰 Сделать ставку", callback_data="menu_bet")],
        [InlineKeyboardButton("⚔️ PvP с другом", callback_data="menu_pvp")],
        [InlineKeyboardButton("💰 Мой баланс", callback_data="menu_balance")],
        [InlineKeyboardButton("📅 Ежедневная награда", callback_data="menu_daily")],
        [InlineKeyboardButton("🏆 Таблица лидеров", callback_data="menu_leaderboard")],
        [InlineKeyboardButton("📊 Моя статистика", callback_data="menu_stats")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = f"""*Главное меню* 🎮

*Твой баланс:* `{balance}` монет 💰

*Выбери действие:*"""
    
    await safe_edit_message(query, text, reply_markup)

# === СИСТЕМА СТАВОК ===
async def bet_command_from_menu(query, context):
    """Начало ставки из меню"""
    user = query.from_user
    balance = get_user_balance_safe(user.id)
    
    # ОЧИСТКА СТАРЫХ ДАННЫХ ПЕРЕД НОВОЙ СТАВКОЙ
    if 'current_bet' in context.user_data:
        del context.user_data['current_bet']
    if 'current_battle' in context.user_data:
        del context.user_data['current_battle']
    
    if balance < 10:
        await safe_edit_message(query,
            f"*❌ Недостаточно монет!*\n\n"
            f"Твой баланс: `{balance}` монет\n"
            f"Минимальная ставка: `10` монет\n\n"
            f"*Жди ежедневную награду или выигрывай в других ставках!*"
        )
        return
    
    # ГАРАНТИРУЕМ РАЗНЫХ ПЕРСОНАЖЕЙ ДЛЯ БИТВЫ
    characters_list = list(CHARACTERS.keys())
    if len(characters_list) < 2:
        await safe_edit_message(query, "*❌ Ошибка: недостаточно персонажей для битвы*")
        return
    
    char1_name, char2_name = random.sample(characters_list, 2)
    # ДОПОЛНИТЕЛЬНАЯ ПРОВЕРКА (на случай если sample вернет одинаковых)
    while char1_name == char2_name:
        char2_name = random.choice(characters_list)
    
    char1 = CHARACTERS[char1_name]
    char2 = CHARACTERS[char2_name]
    
    # Сохраняем данные о битве в context
    context.user_data['current_battle'] = {
        'char1': char1_name,
        'char2': char2_name,
        'char1_power': char1['power'],
        'char2_power': char2['power'],
        'char1_universe': char1['universe'],
        'char2_universe': char2['universe']
    }
    
    keyboard = [
        [InlineKeyboardButton(f"💰 Ставка 10 монет (x1.5)", callback_data="bet_10")],
        [InlineKeyboardButton(f"💰 Ставка 25 монет (x2.0)", callback_data="bet_25")],
        [InlineKeyboardButton(f"💰 Ставка 50 монет (x2.5)", callback_data="bet_50")],
        [InlineKeyboardButton(f"💰 Ставка 100 монет (x3.0)", callback_data="bet_100")],
        [InlineKeyboardButton("🔙 Назад", callback_data="menu_back")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await safe_edit_message(query,
        f"*🎰 СТАВКА НА БИТВУ* 🎰\n\n"
        f"{UNIVERSE_EMOJIS[char1['universe']]} *{char1_name}* ({char1['universe']})\n"
        f"⚡ **ПРОТИВ** ⚡\n"
        f"{UNIVERSE_EMOJIS[char2['universe']]} *{char2_name}* ({char2['universe']})\n\n"
        f"*Твой баланс:* `{balance}` монет\n"
        f"*Выбери сумму ставки:*",
        reply_markup=reply_markup
    )

async def bet_selection_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора суммы ставки"""
    query = update.callback_query
    await query.answer()
    
    # ВАЛИДАЦИЯ CALLBACK_DATA
    if not query.data or not query.data.startswith('bet_'):
        logger.warning(f"Invalid bet callback data: {query.data}")
        await safe_edit_message(query, "*❌ Ошибка: неверные данные*")
        return
    
    try:
        bet_amount = int(query.data.split('_')[1])
        valid_amounts = [10, 25, 50, 100]
        if bet_amount not in valid_amounts:
            raise ValueError("Invalid bet amount")
    except (ValueError, IndexError) as e:
        logger.warning(f"Invalid bet amount in callback: {query.data}, error: {e}")
        await safe_edit_message(query, "*❌ Ошибка: неверная сумма ставки*")
        return
    
    user = query.from_user
    
    # ПРОВЕРКА БАЛАНСА (БЕЗОПАСНАЯ)
    balance = get_user_balance_safe(user.id)
    if balance < bet_amount:
        await safe_edit_message(query,
            f"*❌ Недостаточно монет!*\n\n"
            f"Ты хотел поставить: `{bet_amount}` монет\n"
            f"Твой баланс: `{balance}` монет\n\n"
            f"*Используй* `/start` *для новой ставки*"
        )
        return
    
    # Сохраняем сумму ставки в context
    context.user_data['current_bet'] = {
        'amount': bet_amount,
        'multiplier': {10: 1.5, 25: 2.0, 50: 2.5, 100: 3.0}[bet_amount]
    }
    
    battle_data = context.user_data.get('current_battle')
    if not battle_data:
        await safe_edit_message(query, "*❌ Ошибка! Начни новую ставку через /start*")
        return
    
    keyboard = [
        [InlineKeyboardButton(f"🎯 Ставка на {battle_data['char1']}", callback_data="choose_1")],
        [InlineKeyboardButton(f"🎯 Ставка на {battle_data['char2']}", callback_data="choose_2")],
        [InlineKeyboardButton(f"❌ Отмена", callback_data="cancel_bet")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await safe_edit_message(query,
        f"*🎯 ВЫБОР ПОБЕДИТЕЛЯ* 🎯\n\n"
        f"*Ставка:* `{bet_amount}` монет\n"
        f"*Множитель:* x{context.user_data['current_bet']['multiplier']}\n"
        f"*Выигрыш:* `{int(bet_amount * context.user_data['current_bet']['multiplier'])}` монет\n\n"
        f"*На кого ставишь?*",
        reply_markup=reply_markup
    )

async def choose_fighter_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора бойца"""
    query = update.callback_query
    await query.answer()
    
    # ВАЛИДАЦИЯ CALLBACK_DATA
    if not query.data or not query.data.startswith('choose_'):
        logger.warning(f"Invalid fighter callback data: {query.data}")
        await safe_edit_message(query, "*❌ Ошибка: неверные данные*")
        return
    
    try:
        chosen_fighter = int(query.data.split('_')[1])
        if chosen_fighter not in [1, 2]:
            raise ValueError("Invalid fighter choice")
    except (ValueError, IndexError) as e:
        logger.warning(f"Invalid fighter choice in callback: {query.data}, error: {e}")
        await safe_edit_message(query, "*❌ Ошибка: неверный выбор бойца*")
        return
    
    user = query.from_user
    
    # ПРОВЕРКА СУЩЕСТВОВАНИЯ ДАННЫХ
    battle_data = context.user_data.get('current_battle')
    bet_data = context.user_data.get('current_bet')
    
    if not battle_data or not bet_data:
        await safe_edit_message(query, "*❌ Ошибка! Данные о ставке утеряны. Начни новую ставку через /start*")
        return
    
    # Рассчитываем шансы на победу based на силе персонажей
    total_power = battle_data['char1_power'] + battle_data['char2_power']
    char1_chance = battle_data['char1_power'] / total_power
    char2_chance = battle_data['char2_power'] / total_power
    
    # Определяем победителя based на шансах
    winner = 1 if random.random() < char1_chance else 2
    
    # Определяем выигрыш (БЕЗОПАСНАЯ ОПЕРАЦИЯ)
    if chosen_fighter == winner:
        win_amount = int(bet_data['amount'] * bet_data['multiplier'])
        success = update_user_balance_safe(user.id, win_amount)
        result_text = f"🎉 *ПОБЕДА!* +{win_amount} монет!" if success else "🎉 *ПОБЕДА!* (ошибка начисления)"
        result_emoji = "✅"
    else:
        success = update_user_balance_safe(user.id, -bet_data['amount'])
        result_text = f"💥 *ПРОИГРЫШ!* -{bet_data['amount']} монет" if success else "💥 *ПРОИГРЫШ!* (ошибка списания)"
        result_emoji = "❌"
    
    # Обновляем общий счет
    if success:
        update_user_score(user.id, user.username, 1)
    
    # Очищаем данные о текущей ставке
    if 'current_bet' in context.user_data:
        del context.user_data['current_bet']
    if 'current_battle' in context.user_data:
        del context.user_data['current_battle']
    
    # Показываем результат
    winner_name = battle_data['char1'] if winner == 1 else battle_data['char2']
    loser_name = battle_data['char2'] if winner == 1 else battle_data['char1']
    
    # БЕЗОПАСНОЕ ПОЛУЧЕНИЕ БАЛАНСА
    current_balance = get_user_balance_safe(user.id)
    
    await safe_edit_message(query,
        f"*⚔️ РЕЗУЛЬТАТ БИТВЫ* ⚔️\n\n"
        f"{UNIVERSE_EMOJIS[battle_data['char1_universe']]} *{battle_data['char1']}* 🆚 "
        f"{UNIVERSE_EMOJIS[battle_data['char2_universe']]} *{battle_data['char2']}*\n\n"
        f"🏆 *ПОБЕДИТЕЛЬ:* **{winner_name}**\n"
        f"💀 *ПРОИГРАВШИЙ:* {loser_name}\n\n"
        f"*ТВОЯ СТАВКА:* на {battle_data['char1'] if chosen_fighter == 1 else battle_data['char2']}\n"
        f"*СТАВКА:* {bet_data['amount']} монет\n"
        f"*МНОЖИТЕЛЬ:* x{bet_data['multiplier']}\n\n"
        f"{result_emoji} **{result_text}**\n\n"
        f"*Новый баланс:* `{current_balance}` монет\n\n"
        f"*Следующая ставка:* /start"
    )

async def cancel_bet_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка отмены ставки"""
    query = update.callback_query
    await query.answer()
    
    # Очищаем данные о ставке
    if 'current_bet' in context.user_data:
        del context.user_data['current_bet']
    if 'current_battle' in context.user_data:
        del context.user_data['current_battle']
    
    text = "*❌ Ставка отменена*\n\nВсе данные о текущей ставке очищены.\n\n*Используй* `/start` *для возврата в меню*"
    
    await safe_edit_message(query, text)

# === PvP СИСТЕМА (НОВАЯ ВЕРСИЯ С КОМАНДАМИ) ===
async def pvp_command_from_menu(query, context):
    """Меню PvP"""
    user = query.from_user
    
    keyboard = [
        [InlineKeyboardButton("🎯 Создать вызов", callback_data="pvp_create")],
        [InlineKeyboardButton("❌ Отменить вызов", callback_data="pvp_cancel")],
        [InlineKeyboardButton("🔙 Назад", callback_data="menu_back")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await safe_edit_message(query,
        f"*⚔️ PvP СИСТЕМА* ⚔️\n\n"
        f"*Привет, {user.first_name}!*\n\n"
        f"*Как работает PvP:*\n"
        f"• Создай вызов и отправь другу\n"
        f"• Друг принимает вызов\n"
        f"• Каждому выдаётся 5 случайных персонажей\n"
        f"• Выбери 3 персонажа в свою команду\n"
        f"• Побеждает команда с большей суммарной силой!\n\n"
        f"*Ставка:* 50 монет с каждого игрока\n"
        f"*Выигрыш:* 100 монет победителю!\n\n"
        f"*Твой баланс:* `{get_user_balance_safe(user.id)}` монет\n"
        f"*Выбери действие:*",
        reply_markup=reply_markup
    )

async def pvp_create_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создание PvP вызова"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    user_id = user.id
    
    # Проверяем баланс
    balance = get_user_balance_safe(user_id)
    if balance < 50:
        await safe_edit_message(query,
            f"*❌ Недостаточно монет для PvP!*\n\n"
            f"Требуется: `50` монет\n"
            f"Твой баланс: `{balance}` монет\n\n"
            f"*Получи ежедневную награду или выиграй в обычных ставках!*"
        )
        return
    
    # Проверяем, нет ли активного вызова
    if user_id in active_pvp_challenges:
        await safe_edit_message(query,
            "*⚠️ У тебя уже есть активный вызов!*\n\n"
            "Дождись ответа или отмени текущий вызов."
        )
        return
    
    # Создаем вызов
    challenge_id = f"pvp_{user_id}_{int(time.time())}"
    active_pvp_challenges[user_id] = {
        'challenge_id': challenge_id,
        'created_at': time.time(),
        'creator_name': user.first_name,
        'creator_username': user.username,
        'creator_id': user_id
    }
    
    keyboard = [
        [InlineKeyboardButton("✅ Принять вызов", callback_data=f"pvp_accept_{user_id}")],
        [InlineKeyboardButton("❌ Отклонить", callback_data=f"pvp_decline_{user_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Отправляем сообщение с вызовом
    try:
        challenge_message = await query.message.reply_text(
            f"*⚔️ PvP ВЫЗОВ!* ⚔️\n\n"
            f"*{user.first_name}* вызывает тебя на битву команд!\n\n"
            f"*Приз:* 100 монет 🪙\n"
            f"*Ставка:* 50 монет с игрока\n"
            f"*Правила:*\n"
            f"• Каждому выдаётся 5 случайных персонажей\n"
            f"• Выбери 3 в свою команду\n"
            f"• Побеждает команда с большей силой!\n\n"
            f"*Прими вызов и сразись!*",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
        await safe_edit_message(query,
            f"*🎯 ВЫЗОВ СОЗДАН!* 🎯\n\n"
            f"*Твой вызов отправлен!*\n\n"
            f"*Отправь другу это сообщение или ссылку:*\n"
            f"t.me/{context.bot.username}?start=pvp_{user_id}\n\n"
            f"*Вызов активен 5 минут.* ⏰"
        )
        
        # Запускаем таймер для автоматического удаления вызова
        asyncio.create_task(pvp_challenge_timeout(user_id, context))
        
    except Exception as e:
        logger.error(f"Error creating PvP challenge: {e}")
        await safe_edit_message(query, "*❌ Ошибка при создании вызова!*")

async def pvp_accept_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принятие PvP вызова"""
    query = update.callback_query
    await query.answer()
    
    try:
        creator_id = int(query.data.split('_')[-1])
    except (ValueError, IndexError):
        await safe_edit_message(query, "*❌ Ошибка: неверный вызов*")
        return
    
    user = query.from_user
    user_id = user.id
    
    # Проверяем, не принимаем ли мы свой же вызов
    if user_id == creator_id:
        await safe_edit_message(query, "*❌ Нельзя принять свой же вызов!*")
        return
    
    # Проверяем существование вызова
    if creator_id not in active_pvp_challenges:
        await safe_edit_message(query, "*❌ Вызов не найден или истек!*")
        return
    
    creator_name = active_pvp_challenges[creator_id]['creator_name']
    
    # Проверяем баланс обоих игроков
    creator_balance = get_user_balance_safe(creator_id)
    acceptor_balance = get_user_balance_safe(user_id)
    
    if creator_balance < 50 or acceptor_balance < 50:
        # Удаляем вызов
        if creator_id in active_pvp_challenges:
            del active_pvp_challenges[creator_id]
        await safe_edit_message(query, "*❌ У одного из игроков недостаточно монет!*")
        return
    
    # Списываем ставки
    success1 = update_user_balance_safe(creator_id, -50)
    success2 = update_user_balance_safe(user_id, -50)
    
    if not success1 or not success2:
        await safe_edit_message(query, "*❌ Ошибка при списании ставок!*")
        return
    
    # Генерируем случайные персонажи для обоих игроков
    characters_list = list(CHARACTERS.keys())
    
    if len(characters_list) < 10:
        await safe_edit_message(query, "*❌ Ошибка: недостаточно персонажей в базе*")
        # Возвращаем средства
        update_user_balance_safe(creator_id, 50)
        update_user_balance_safe(user_id, 50)
        return
    
    # Персонажи для создателя вызова
    creator_characters = random.sample(characters_list, 5)
    # Персонажи для принимающего (гарантируем разные наборы)
    remaining_chars = [c for c in characters_list if c not in creator_characters]
    if len(remaining_chars) < 5:
        # Если недостаточно уникальных персонажей, добавляем случайные
        acceptor_characters = random.sample(characters_list, 5)
    else:
        acceptor_characters = random.sample(remaining_chars, 5)
    
    # Сохраняем данные для выбора команд
    battle_id = f"battle_{creator_id}_{user_id}_{int(time.time())}"
    
    pvp_team_selection[creator_id] = {
        'battle_id': battle_id,
        'opponent_id': user_id,
        'characters': creator_characters,
        'selected_team': [],
        'player_name': creator_name,
        'ready': False
    }
    
    pvp_team_selection[user_id] = {
        'battle_id': battle_id,
        'opponent_id': creator_id,
        'characters': acceptor_characters,
        'selected_team': [],
        'player_name': user.first_name,
        'ready': False
    }
    
    # Удаляем вызов
    if creator_id in active_pvp_challenges:
        del active_pvp_challenges[creator_id]
    
    # Отправляем создателю вызова меню выбора команды
    await send_team_selection_menu(context, creator_id)
    
    # Отправляем принимающему меню выбора команды
    await send_team_selection_menu(context, user_id)
    
    await safe_edit_message(query,
        f"*✅ ВЫЗОВ ПРИНЯТ!* ✅\n\n"
        f"*Ты принял вызов от {creator_name}!*\n\n"
        f"*Теперь выбери 3 персонажа из 5 доступных для своей команды.*\n"
        f"*С твоего счета списано 50 монет.* 💰"
    )
    
    # Уведомляем создателя вызова
    try:
        await context.bot.send_message(
            chat_id=creator_id,
            text=f"*✅ ТВОЙ PvP ВЫЗОВ ПРИНЯТ!* ✅\n\n"
                 f"*{user.first_name}* принял твой вызов!\n\n"
                 f"*Теперь выбери 3 персонажа из 5 доступных для своей команды.*\n"
                 f"*С твоего счета списано 50 монет.* 💰",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error notifying challenge creator: {e}")

async def send_team_selection_menu(context, user_id):
    """Отправляет меню выбора команды"""
    if user_id not in pvp_team_selection:
        return
    
    team_data = pvp_team_selection[user_id]
    characters = team_data.get('characters', [])
    
    if not characters:
        logger.error(f"No characters found for user {user_id}")
        return
    
    # Создаем клавиатуру для выбора персонажей
    keyboard = []
    for i, char_name in enumerate(characters, 1):
        char_data = CHARACTERS.get(char_name, {})
        power = char_data.get('power', 0)
        emoji = "✅" if char_name in team_data.get('selected_team', []) else "⚪"
        button_text = f"{emoji} {char_name} ({power})"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"pvp_select_{user_id}_{i}")])
    
    # Кнопка подтверждения команды
    selected_team = team_data.get('selected_team', [])
    if len(selected_team) == 3:
        keyboard.append([InlineKeyboardButton("🚀 Подтвердить команду", callback_data=f"pvp_confirm_{user_id}")])
    
    keyboard.append([InlineKeyboardButton("❌ Отменить битву", callback_data=f"pvp_cancel_battle_{user_id}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    selected_count = len(selected_team)
    team_power = sum(CHARACTERS.get(char, {}).get('power', 0) for char in selected_team)
    
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"*⚔️ ВЫБОР КОМАНДЫ* ⚔️\n\n"
                 f"*Выбери 3 персонажа для своей команды:*\n\n"
                 f"*Доступные персонажи:*\n" +
                 "\n".join([f"{i}. {char} ({CHARACTERS.get(char, {}).get('power', 0)} силы)" 
                           for i, char in enumerate(characters, 1)]) +
                 f"\n\n*Выбрано:* {selected_count}/3 персонажей\n"
                 f"*Суммарная сила команды:* {team_power}\n\n"
                 f"*Нажми на персонажа чтобы добавить/убрать из команды.*",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error sending team selection menu to {user_id}: {e}")

async def pvp_select_character_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора персонажа в команду"""
    query = update.callback_query
    await query.answer()
    
    try:
        data_parts = query.data.split('_')
        target_user_id = int(data_parts[2])
        char_index = int(data_parts[3]) - 1
    except (ValueError, IndexError):
        await safe_edit_message(query, "*❌ Ошибка выбора персонажа*")
        return
    
    user_id = query.from_user.id
    
    # Проверяем, что пользователь выбирает своих персонажей
    if user_id != target_user_id or user_id not in pvp_team_selection:
        await safe_edit_message(query, "*❌ Ошибка доступа*")
        return
    
    team_data = pvp_team_selection[user_id]
    characters = team_data.get('characters', [])
    
    if char_index < 0 or char_index >= len(characters):
        await safe_edit_message(query, "*❌ Неверный индекс персонажа*")
        return
    
    selected_char = characters[char_index]
    selected_team = team_data.get('selected_team', [])
    
    # Добавляем или убираем персонажа из команды
    if selected_char in selected_team:
        selected_team.remove(selected_char)
    else:
        if len(selected_team) < 3:
            selected_team.append(selected_char)
        else:
            await query.answer("❌ Можно выбрать только 3 персонажа!", show_alert=True)
            return
    
    team_data['selected_team'] = selected_team
    
    # Обновляем меню выбора
    await send_team_selection_menu(context, user_id)
    
    # Удаляем старое сообщение
    try:
        await query.message.delete()
    except:
        pass

async def pvp_confirm_team_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение выбранной команды"""
    query = update.callback_query
    await query.answer()
    
    try:
        target_user_id = int(query.data.split('_')[2])
    except (ValueError, IndexError):
        await safe_edit_message(query, "*❌ Ошибка подтверждения*")
        return
    
    user_id = query.from_user.id
    
    if user_id != target_user_id or user_id not in pvp_team_selection:
        await safe_edit_message(query, "*❌ Ошибка доступа*")
        return
    
    team_data = pvp_team_selection[user_id]
    selected_team = team_data.get('selected_team', [])
    
    if len(selected_team) != 3:
        await query.answer("❌ Выбери ровно 3 персонажа!", show_alert=True)
        return
    
    # Помечаем, что игрок готов
    team_data['ready'] = True
    
    team_power = sum(CHARACTERS.get(char, {}).get('power', 0) for char in selected_team)
    
    await safe_edit_message(query,
        f"*✅ КОМАНДА ПОДТВЕРЖДЕНА!* ✅\n\n"
        f"*Твоя команда:*\n" +
        "\n".join([f"• {char} ({CHARACTERS.get(char, {}).get('power', 0)} силы)" 
                  for char in selected_team]) +
        f"\n\n*Суммарная сила:* {team_power}\n\n"
        f"*Ожидаем подтверждения противника...*"
    )
    
    # Проверяем, готовы ли оба игрока
    opponent_id = team_data['opponent_id']
    if opponent_id in pvp_team_selection and pvp_team_selection[opponent_id].get('ready'):
        # Оба игрока готовы - начинаем битву
        await start_pvp_battle(context, user_id, opponent_id)

async def start_pvp_battle(context, player1_id, player2_id):
    """Начинает PvP битву между двумя игроками"""
    if player1_id not in pvp_team_selection or player2_id not in pvp_team_selection:
        return
    
    player1_data = pvp_team_selection[player1_id]
    player2_data = pvp_team_selection[player2_id]
    
    # Проверяем что команды выбраны
    player1_team = player1_data.get('selected_team', [])
    player2_team = player2_data.get('selected_team', [])
    
    if len(player1_team) != 3 or len(player2_team) != 3:
        logger.error("Invalid team selection in PvP battle")
        return
    
    # Вычисляем суммарную силу команд
    team1_power = sum(CHARACTERS.get(char, {}).get('power', 0) for char in player1_team)
    team2_power = sum(CHARACTERS.get(char, {}).get('power', 0) for char in player2_team)
    
    # Определяем победителя
    if team1_power > team2_power:
        winner_id = player1_id
        loser_id = player2_id
        winner_name = player1_data['player_name']
        loser_name = player2_data['player_name']
    elif team2_power > team1_power:
        winner_id = player2_id
        loser_id = player1_id
        winner_name = player2_data['player_name']
        loser_name = player1_data['player_name']
    else:
        # Ничья - случайный победитель
        winner_id = random.choice([player1_id, player2_id])
        loser_id = player2_id if winner_id == player1_id else player1_id
        winner_name = player1_data['player_name'] if winner_id == player1_id else player2_data['player_name']
        loser_name = player2_data['player_name'] if winner_id == player1_id else player1_data['player_name']
    
    # Начисляем выигрыш
    update_user_balance_safe(winner_id, 100)
    update_pvp_stats(winner_id, loser_id)
    
    # Обновляем статистику
    update_user_score(winner_id, "", 5)
    update_user_score(loser_id, "", 2)
    
    # Формируем детали битвы
    battle_text = f"*⚔️ PvP БИТВА ЗАВЕРШЕНА!* ⚔️\n\n"
    battle_text += f"*{player1_data['player_name']}* 🆚 *{player2_data['player_name']}*\n\n"
    
    battle_text += f"*Команда {player1_data['player_name']}:*\n"
    for char in player1_team:
        power = CHARACTERS.get(char, {}).get('power', 0)
        battle_text += f"• {char} ({power} силы)\n"
    battle_text += f"*Суммарно:* {team1_power} силы\n\n"
    
    battle_text += f"*Команда {player2_data['player_name']}:*\n"
    for char in player2_team:
        power = CHARACTERS.get(char, {}).get('power', 0)
        battle_text += f"• {char} ({power} силы)\n"
    battle_text += f"*Суммарно:* {team2_power} силы\n\n"
    
    battle_text += f"🏆 *ПОБЕДИТЕЛЬ:* **{winner_name}**\n"
    battle_text += f"💰 *Выигрыш:* 100 монет!\n\n"
    battle_text += f"*Новые балансы:*\n"
    battle_text += f"• {winner_name}: `{get_user_balance_safe(winner_id)}` монет\n"
    battle_text += f"• {loser_name}: `{get_user_balance_safe(loser_id)}` монет"
    
    # Отправляем результаты обоим игрокам
    try:
        await context.bot.send_message(chat_id=player1_id, text=battle_text, parse_mode='Markdown')
        await context.bot.send_message(chat_id=player2_id, text=battle_text, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error sending battle results: {e}")
    
    # Очищаем данные о битве
    if player1_id in pvp_team_selection:
        del pvp_team_selection[player1_id]
    if player2_id in pvp_team_selection:
        del pvp_team_selection[player2_id]

async def pvp_cancel_battle_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена битвы во время выбора команды"""
    query = update.callback_query
    await query.answer()
    
    try:
        target_user_id = int(query.data.split('_')[3])
    except (ValueError, IndexError):
        await safe_edit_message(query, "*❌ Ошибка отмены*")
        return
    
    user_id = query.from_user.id
    
    if user_id != target_user_id or user_id not in pvp_team_selection:
        await safe_edit_message(query, "*❌ Ошибка доступа*")
        return
    
    team_data = pvp_team_selection[user_id]
    opponent_id = team_data.get('opponent_id')
    
    if opponent_id:
        # Возвращаем ставки
        update_user_balance_safe(user_id, 50)
        update_user_balance_safe(opponent_id, 50)
    
    # Очищаем данные
    if user_id in pvp_team_selection:
        del pvp_team_selection[user_id]
    if opponent_id and opponent_id in pvp_team_selection:
        del pvp_team_selection[opponent_id]
    
    await safe_edit_message(query, "*❌ Битва отменена. Ставки возвращены.*")
    
    # Уведомляем противника
    if opponent_id:
        try:
            await context.bot.send_message(
                chat_id=opponent_id,
                text="*❌ Противник отменил битву. Ставки возвращены.*",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Error notifying opponent about battle cancel: {e}")

async def pvp_decline_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отклонение PvP вызова"""
    query = update.callback_query
    await query.answer()
    
    try:
        creator_id = int(query.data.split('_')[-1])
    except (ValueError, IndexError):
        await safe_edit_message(query, "*❌ Ошибка: неверный вызов*")
        return
    
    # Удаляем вызов
    if creator_id in active_pvp_challenges:
        del active_pvp_challenges[creator_id]
    
    await safe_edit_message(query, "*❌ Вызов отклонен*")
    
    # Уведомляем создателя вызова
    try:
        await context.bot.send_message(
            chat_id=creator_id,
            text=f"*❌ Твой PvP вызов был отклонен*",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error notifying challenge creator about decline: {e}")

async def pvp_cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена PvP вызова"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    if user_id in active_pvp_challenges:
        del active_pvp_challenges[user_id]
        await safe_edit_message(query, "*✅ Вызов отменен*")
    else:
        await safe_edit_message(query, "*❌ У тебя нет активных вызовов*")

async def pvp_challenge_timeout(user_id, context):
    """Таймаут для PvP вызова"""
    await asyncio.sleep(300)  # 5 минут
    
    if user_id in active_pvp_challenges:
        del active_pvp_challenges[user_id]
        
        # Уведомляем пользователя
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="*⏰ Время твоего PvP вызова истекло*",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Error notifying about challenge timeout: {e}")

# === ЗАПУСК БОТА ===
def main():
    """Основная функция запуска бота"""
    try:
        # Инициализация базы данных
        init_db()
        
        # Создание приложения
        application = Application.builder().token(BOT_TOKEN).build()
        
        # ОСНОВНЫЕ ОБРАБОТЧИКИ
        application.add_handler(CommandHandler("start", start))
        
        # Обработчики меню
        application.add_handler(CallbackQueryHandler(menu_handler, pattern="^menu_(bet|balance|daily|leaderboard|stats|pvp)$"))
        application.add_handler(CallbackQueryHandler(menu_back_handler, pattern="^menu_back$"))
        
        # Обработчики ставок
        application.add_handler(CallbackQueryHandler(bet_selection_handler, pattern="^bet_"))
        application.add_handler(CallbackQueryHandler(choose_fighter_handler, pattern="^(choose_1|choose_2)$"))
        application.add_handler(CallbackQueryHandler(cancel_bet_handler, pattern="^cancel_bet$"))
        
        # Обработчики PvP
        application.add_handler(CallbackQueryHandler(pvp_create_handler, pattern="^pvp_create$"))
        application.add_handler(CallbackQueryHandler(pvp_accept_handler, pattern="^pvp_accept_"))
        application.add_handler(CallbackQueryHandler(pvp_decline_handler, pattern="^pvp_decline_"))
        application.add_handler(CallbackQueryHandler(pvp_cancel_handler, pattern="^pvp_cancel$"))
        application.add_handler(CallbackQueryHandler(pvp_select_character_handler, pattern="^pvp_select_"))
        application.add_handler(CallbackQueryHandler(pvp_confirm_team_handler, pattern="^pvp_confirm_"))
        application.add_handler(CallbackQueryHandler(pvp_cancel_battle_handler, pattern="^pvp_cancel_battle_"))
        
        print("🎰 Бот ставок успешно запущен!")
        print("⚔️ PvP система активирована")
        print("💰 База данных инициализирована")
        print("📊 Все обработчики настроены")
        print("🤖 Бот готов к работе!")
        print("\nДля остановки нажмите Ctrl+C")
        
        # Запуск бота
        application.run_polling(
            poll_interval=3,
            timeout=30,
            drop_pending_updates=True
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка при запуске бота: {e}")
        sys.exit(1)

if __name__ == '__main__':
    # Запускаем health check сервер в отдельном потоке
    health_thread = threading.Thread(target=start_health_check_server, daemon=True)
    health_thread.start()
    
    # Запускаем бота в основном потоке
    main()
