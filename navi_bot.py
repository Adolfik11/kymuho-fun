
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
import json
from collections import defaultdict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# === КОНФИГУРАЦИЯ ===
BOT_TOKEN = "8578378221:AAHCZqygYGaDFqEbqSnVaORiHf2QF44RNWU"

# Обязательные каналы для подписки
REQUIRED_CHANNELS = [
    "@KyMiHoYo",  # Новости от Кумихо
    "@KyMiHoYo_Q",  # Находки с вб, озона и алика  
    "@KyMiHoYo_Memo",  # мемасики
    "@Kymiho_meow"  # лайф канал
]

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

# === СИСТЕМА СЕЗОНОВ ===
SEASONS = {
    1: {"name": "Сезон Драконов", "theme": "dragons", "emoji": "🐉", "month": 1},
    2: {"name": "Сезон Цветения", "theme": "blossom", "emoji": "🌸", "month": 2},
    3: {"name": "Сезон Ветра", "theme": "wind", "emoji": "💨", "month": 3},
    4: {"name": "Сезон Огня", "theme": "fire", "emoji": "🔥", "month": 4},
    5: {"name": "Сезон Воды", "theme": "water", "emoji": "💧", "month": 5},
    6: {"name": "Сезон Света", "theme": "light", "emoji": "✨", "month": 6},
    7: {"name": "Сезон Теней", "theme": "shadows", "emoji": "🌑", "month": 7},
    8: {"name": "Сезон Грозы", "theme": "storm", "emoji": "⛈️", "month": 8},
    9: {"name": "Сезон Урожая", "theme": "harvest", "emoji": "🍂", "month": 9},
    10: {"name": "Сезон Призраков", "theme": "ghosts", "emoji": "👻", "month": 10},
    11: {"name": "Сезон Льда", "theme": "ice", "emoji": "❄️", "month": 11},
    12: {"name": "Сезон Звезд", "theme": "stars", "emoji": "⭐", "month": 12}
}

def get_current_season():
    """Определяет текущий сезон на основе месяца"""
    now = datetime.datetime.now()
    current_month = now.month
    return SEASONS[current_month]

CURRENT_SEASON = get_current_season()
SEASON_EMOJI = CURRENT_SEASON["emoji"]
SEASON_NAME = CURRENT_SEASON["name"]

# === СИСТЕМА КОЛЛЕКЦИОНИРОВАНИЯ ПЕРСОНАЖЕЙ ===
CHARACTER_RARITY = {
    "common": {"emoji": "⚪", "chance": 50, "multiplier": 1.0},
    "rare": {"emoji": "🔵", "chance": 30, "multiplier": 1.2},
    "epic": {"emoji": "🟣", "chance": 15, "multiplier": 1.5},
    "legendary": {"emoji": "🟡", "chance": 5, "multiplier": 2.0}
}

# === ОБНОВЛЕННЫЕ ДАННЫЕ ПЕРСОНАЖЕЙ (ОФИЦИАЛЬНЫЕ ИМЕНА) ===
CHARACTERS = {
    # Honkai: Star Rail
    "Кафка": {"universe": "Honkai: Star Rail", "power": 88, "rarity": "epic", "season_boost": []},
    "Блэйд": {"universe": "Honkai: Star Rail", "power": 87, "rarity": "epic", "season_boost": []},
    "Дань Хэн": {"universe": "Honkai: Star Rail", "power": 82, "rarity": "rare", "season_boost": ["dragons"]},
    "Серебряный Вольф": {"universe": "Honkai: Star Rail", "power": 85, "rarity": "epic", "season_boost": []},
    "Клара": {"universe": "Honkai: Star Rail", "power": 80, "rarity": "rare", "season_boost": []},
    "Зеле": {"universe": "Honkai: Star Rail", "power": 81, "rarity": "rare", "season_boost": []},
    "Вельт": {"universe": "Honkai: Star Rail", "power": 90, "rarity": "legendary", "season_boost": []},
    "Гепард": {"universe": "Honkai: Star Rail", "power": 84, "rarity": "epic", "season_boost": []},
    "Ян Цин": {"universe": "Honkai: Star Rail", "power": 79, "rarity": "common", "season_boost": []},
    "Сильвер Вольф": {"universe": "Honkai: Star Rail", "power": 83, "rarity": "epic", "season_boost": []},
    "Химеко": {"universe": "Honkai: Star Rail", "power": 86, "rarity": "epic", "season_boost": []},
    "Херта": {"universe": "Honkai: Star Rail", "power": 75, "rarity": "common", "season_boost": []},
    "Лоча": {"universe": "Honkai: Star Rail", "power": 82, "rarity": "rare", "season_boost": []},
    "Тиньюнь": {"universe": "Honkai: Star Rail", "power": 81, "rarity": "rare", "season_boost": []},
    "Сушан": {"universe": "Honkai: Star Rail", "power": 78, "rarity": "common", "season_boost": []},
    "Фу Сюань": {"universe": "Honkai: Star Rail", "power": 87, "rarity": "epic", "season_boost": []},
    "Цзин Юань": {"universe": "Honkai: Star Rail", "power": 89, "rarity": "epic", "season_boost": []},
    "Люча": {"universe": "Honkai: Star Rail", "power": 83, "rarity": "rare", "season_boost": []},
    "Аргенти": {"universe": "Honkai: Star Rail", "power": 91, "rarity": "legendary", "season_boost": []},
    "Доктор Рацио": {"universe": "Honkai: Star Rail", "power": 85, "rarity": "epic", "season_boost": []},
    
    # Genshin Impact
    "Райдэн": {"universe": "Genshin Impact", "power": 95, "rarity": "legendary", "season_boost": []},
    "Чжун Ли": {"universe": "Genshin Impact", "power": 94, "rarity": "legendary", "season_boost": []},
    "Дилюк": {"universe": "Genshin Impact", "power": 88, "rarity": "epic", "season_boost": []},
    "Гань Юй": {"universe": "Genshin Impact", "power": 90, "rarity": "epic", "season_boost": []},
    "Нахида": {"universe": "Genshin Impact", "power": 92, "rarity": "legendary", "season_boost": []},
    "Венти": {"universe": "Genshin Impact", "power": 89, "rarity": "epic", "season_boost": []},
    "Эола": {"universe": "Genshin Impact", "power": 86, "rarity": "epic", "season_boost": []},
    "Кэ Цин": {"universe": "Genshin Impact", "power": 83, "rarity": "rare", "season_boost": []},
    "Ху Тао": {"universe": "Genshin Impact", "power": 91, "rarity": "epic", "season_boost": []},
    "Аяка": {"universe": "Genshin Impact", "power": 89, "rarity": "epic", "season_boost": []},
    "Кокоми": {"universe": "Genshin Impact", "power": 87, "rarity": "epic", "season_boost": []},
    "Альбедо": {"universe": "Genshin Impact", "power": 84, "rarity": "rare", "season_boost": []},
    "Кли": {"universe": "Genshin Impact", "power": 82, "rarity": "rare", "season_boost": []},
    "Мона": {"universe": "Genshin Impact", "power": 85, "rarity": "epic", "season_boost": []},
    "Тарталья": {"universe": "Genshin Impact", "power": 90, "rarity": "epic", "season_boost": []},
    "Аято": {"universe": "Genshin Impact", "power": 88, "rarity": "epic", "season_boost": []},
    "Йоимия": {"universe": "Genshin Impact", "power": 86, "rarity": "epic", "season_boost": []},
    "Шэнь Хэ": {"universe": "Genshin Impact", "power": 87, "rarity": "epic", "season_boost": []},
    "Яэ Мико": {"universe": "Genshin Impact", "power": 89, "rarity": "epic", "season_boost": []},
    "Сайно": {"universe": "Genshin Impact", "power": 85, "rarity": "epic", "season_boost": []},
    
    # Honkai Impact 3rd
    "Киана": {"universe": "Honkai Impact 3rd", "power": 96, "rarity": "legendary", "season_boost": []},
    "Мэй": {"universe": "Honkai Impact 3rd", "power": 92, "rarity": "epic", "season_boost": []},
    "Броня": {"universe": "Honkai Impact 3rd", "power": 89, "rarity": "epic", "season_boost": []},
    "Тереза": {"universe": "Honkai Impact 3rd", "power": 87, "rarity": "epic", "season_boost": []},
    "Фу Хуа": {"universe": "Honkai Impact 3rd", "power": 91, "rarity": "epic", "season_boost": []},
    "Сирин": {"universe": "Honkai Impact 3rd", "power": 94, "rarity": "legendary", "season_boost": []},
    "Дуриан": {"universe": "Honkai Impact 3rd", "power": 84, "rarity": "rare", "season_boost": []},
    "Рита": {"universe": "Honkai Impact 3rd", "power": 88, "rarity": "epic", "season_boost": []},
    "Лилли": {"universe": "Honkai Impact 3rd", "power": 83, "rarity": "rare", "season_boost": []},
    "Зория": {"universe": "Honkai Impact 3rd", "power": 82, "rarity": "rare", "season_boost": []},
    "Ай-Чан": {"universe": "Honkai Impact 3rd", "power": 90, "rarity": "epic", "season_boost": []},
    "Равен": {"universe": "Honkai Impact 3rd", "power": 85, "rarity": "epic", "season_boost": []},
    "Гризео": {"universe": "Honkai Impact 3rd", "power": 81, "rarity": "rare", "season_boost": []},
    "Пардо": {"universe": "Honkai Impact 3rd", "power": 80, "rarity": "rare", "season_boost": []},
    "Вилли": {"universe": "Honkai Impact 3rd", "power": 86, "rarity": "epic", "season_boost": []},
    "Отто": {"universe": "Honkai Impact 3rd", "power": 93, "rarity": "legendary", "season_boost": []},
    "Кевин": {"universe": "Honkai Impact 3rd", "power": 95, "rarity": "legendary", "season_boost": []},
    "Су": {"universe": "Honkai Impact 3rd", "power": 88, "rarity": "epic", "season_boost": []},
    "Элисия": {"universe": "Honkai Impact 3rd", "power": 89, "rarity": "epic", "season_boost": []},
    "ХоО": {"universe": "Honkai Impact 3rd", "power": 92, "rarity": "epic", "season_boost": []},
    
    # Zenless Zone Zero
    "Билли": {"universe": "Zenless Zone Zero", "power": 79, "rarity": "common", "season_boost": []},
    "Никки": {"universe": "Zenless Zone Zero", "power": 78, "rarity": "common", "season_boost": []},
    "Соломон": {"universe": "Zenless Zone Zero", "power": 84, "rarity": "rare", "season_boost": []},
    "Алекс": {"universe": "Zenless Zone Zero", "power": 80, "rarity": "common", "season_boost": []},
    "Бен": {"universe": "Zenless Zone Zero", "power": 77, "rarity": "common", "season_boost": []},
    "Короленок": {"universe": "Zenless Zone Zero", "power": 76, "rarity": "common", "season_boost": []},
    "Эллен": {"universe": "Zenless Zone Zero", "power": 82, "rarity": "rare", "season_boost": []},
    "Люси": {"universe": "Zenless Zone Zero", "power": 79, "rarity": "common", "season_boost": []},
    "Пипер": {"universe": "Zenless Zone Zero", "power": 78, "rarity": "common", "season_boost": []},
    "Коллат": {"universe": "Zenless Zone Zero", "power": 83, "rarity": "rare", "season_boost": []},
    "Антонио": {"universe": "Zenless Zone Zero", "power": 77, "rarity": "common", "season_boost": []},
    "Савада": {"universe": "Zenless Zone Zero", "power": 81, "rarity": "rare", "season_boost": []},
    "Миюки": {"universe": "Zenless Zone Zero", "power": 76, "rarity": "common", "season_boost": []},
    "Хосокава": {"universe": "Zenless Zone Zero", "power": 82, "rarity": "rare", "season_boost": []},
    "Джейн": {"universe": "Zenless Zone Zero", "power": 79, "rarity": "common", "season_boost": []},
    "Анбе": {"universe": "Zenless Zone Zero", "power": 85, "rarity": "epic", "season_boost": []},
    "Грейс": {"universe": "Zenless Zone Zero", "power": 84, "rarity": "epic", "season_boost": []},
    "Корви": {"universe": "Zenless Zone Zero", "power": 86, "rarity": "epic", "season_boost": []},
    "Некро": {"universe": "Zenless Zone Zero", "power": 87, "rarity": "epic", "season_boost": []},
    "Сова": {"universe": "Zenless Zone Zero", "power": 83, "rarity": "rare", "season_boost": []},
}

# === СЕЗОННЫЕ ПЕРСОНАЖИ ДЛЯ СЕЗОНА ДРАКОНОВ ===
SEASONAL_CHARACTERS = {
    "dragons": {
        "Дань Хэн: Пожиратель Луны": {
            "universe": "Honkai: Star Rail", 
            "power": 94, 
            "rarity": "legendary", 
            "season_boost": ["dragons"],
            "is_seasonal": True
        },
        "Дань Хэн: Освободитель Пустоши": {
            "universe": "Honkai: Star Rail", 
            "power": 96, 
            "rarity": "legendary", 
            "season_boost": ["dragons"],
            "is_seasonal": True
        },
        "Драконий Властитель": {
            "universe": "Сезон Драконов", 
            "power": 98, 
            "rarity": "legendary", 
            "season_boost": ["dragons"],
            "is_seasonal": True
        },
        "Древний Дракон": {
            "universe": "Сезон Драконов", 
            "power": 92, 
            "rarity": "epic", 
            "season_boost": ["dragons"],
            "is_seasonal": True
        }
    }
}

# Добавляем сезонных персонажей если текущий сезон - драконы
if CURRENT_SEASON["theme"] in SEASONAL_CHARACTERS:
    CHARACTERS.update(SEASONAL_CHARACTERS[CURRENT_SEASON["theme"]])

UNIVERSE_EMOJIS = {
    "Honkai: Star Rail": "🎮",
    "Genshin Impact": "🌍",
    "Honkai Impact 3rd": "⚡",
    "Zenless Zone Zero": "🏙️",
    "Сезон Драконов": "🐉"
}

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

# === ФУНКЦИИ ПРОВЕРКИ ПОДПИСКИ ===
async def check_subscription(user_id, context):
    """Проверяет подписку пользователя на все обязательные каналы"""
    try:
        for channel in REQUIRED_CHANNELS:
            member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status not in ['member', 'administrator', 'creator']:
                return False
        return True
    except Exception as e:
        logger.error(f"Error checking subscription for {user_id}: {e}")
        return False

async def show_subscription_required(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает сообщение о необходимости подписки"""
    user = update.effective_user
    
    text = "🌸 ДОСТУП К БОТУ ОГРАНИЧЕН! 🌸\n\n"
    text += "Для использования бота необходимо подписаться на наши каналы:\n\n"
    
    for channel in REQUIRED_CHANNELS:
        text += f"• {channel}\n"
    
    text += "\nПосле подписки нажмите кнопку ниже для проверки:"
    
    keyboard = [
        [InlineKeyboardButton("✅ Я ПОДПИСАЛСЯ", callback_data="check_subscription")],
        [InlineKeyboardButton("📢 Наши каналы", url="https://t.me/KyMiHoYo")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup)
    else:
        query = update.callback_query
        await query.message.reply_text(text, reply_markup=reply_markup)

# === ОБНОВЛЕННАЯ БАЗА ДАННЫХ ===
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
                      pvp_losses INTEGER DEFAULT 0,
                      referral_code TEXT,
                      referred_by INTEGER,
                      referrals_count INTEGER DEFAULT 0,
                      total_wins INTEGER DEFAULT 0,
                      total_bets INTEGER DEFAULT 0,
                      join_date TEXT)''')
        
        # Новые таблицы для коллекций и достижений
        c.execute('''CREATE TABLE IF NOT EXISTS user_collections
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER,
                      character_name TEXT,
                      obtained_date TEXT,
                      times_used INTEGER DEFAULT 0,
                      wins_with INTEGER DEFAULT 0,
                      FOREIGN KEY (user_id) REFERENCES users (user_id))''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS user_achievements
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER,
                      achievement_id TEXT,
                      unlocked_date TEXT,
                      reward_claimed BOOLEAN DEFAULT FALSE,
                      FOREIGN KEY (user_id) REFERENCES users (user_id))''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS seasonal_progress
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER,
                      season TEXT,
                      wins INTEGER DEFAULT 0,
                      bets INTEGER DEFAULT 0,
                      characters_collected INTEGER DEFAULT 0,
                      FOREIGN KEY (user_id) REFERENCES users (user_id))''')
        
        conn.commit()
        logger.info("Database initialized successfully with new tables")
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
        
        c.execute('SELECT 1 FROM users WHERE user_id = ?', (user_id,))
        if not c.fetchone():
            c.execute('''INSERT INTO users 
                         (user_id, username, score, last_activity, balance, join_date) 
                         VALUES (?, ?, ?, ?, 100, ?)''',
                      (user_id, username, points, today, today))
        else:
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
        
        c.execute('INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 100)', (user_id,))
        conn.commit()
        
        if amount < 0:
            c.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
            result = c.fetchone()
            if result and result[0] < abs(amount):
                return False
        
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
        
        c.execute('INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 100)', (winner_id,))
        c.execute('INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 100)', (loser_id,))
        conn.commit()
        
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
        
        c.execute('SELECT 1 FROM users WHERE user_id = ?', (user_id,))
        if not c.fetchone():
            return 1
        
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
            return True
        
        last_activity = datetime.datetime.fromisoformat(result[0])
        now = datetime.datetime.now()
        
        return (now - last_activity).total_seconds() >= 24 * 3600
    except Exception as e:
        logger.error(f"Error checking daily reward: {e}")
        return True
    finally:
        conn.close()

async def safe_edit_message(query, text, reply_markup=None):
    """Безопасное обновление сообщения с обработкой ошибок"""
    try:
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup
        )
        return True
    except Exception as e:
        logger.error(f"Error editing message: {e}")
        try:
            await query.message.reply_text(
                text=text,
                reply_markup=reply_markup
            )
            return True
        except Exception as e2:
            logger.error(f"Error sending fallback message: {e2}")
            return False

# === ФУНКЦИИ КОЛЛЕКЦИОНИРОВАНИЯ ===
def add_character_to_collection(user_id, character_name):
    """Добавляет персонажа в коллекцию пользователя"""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        
        c.execute('''SELECT 1 FROM user_collections 
                     WHERE user_id = ? AND character_name = ?''', (user_id, character_name))
        if c.fetchone():
            return False
        
        today = datetime.datetime.now().isoformat()
        c.execute('''INSERT INTO user_collections 
                     (user_id, character_name, obtained_date) 
                     VALUES (?, ?, ?)''', (user_id, character_name, today))
        
        conn.commit()
        return True
    except sqlite3.Error as e:
        logger.error(f"Error adding character to collection: {e}")
        return False
    finally:
        conn.close()

def get_user_collection(user_id):
    """Получает коллекцию персонажей пользователя"""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute('''SELECT character_name, times_used, wins_with 
                     FROM user_collections 
                     WHERE user_id = ? 
                     ORDER BY character_name''', (user_id,))
        return [{"name": row[0], "times_used": row[1], "wins_with": row[2]} for row in c.fetchall()]
    except sqlite3.Error as e:
        logger.error(f"Error getting user collection: {e}")
        return []
    finally:
        conn.close()

def get_collection_stats(user_id):
    """Получает статистику коллекции"""
    collection = get_user_collection(user_id)
    if not collection:
        return {"total": 0, "by_rarity": {}, "unique_universes": set()}
    
    stats = {
        "total": len(collection),
        "by_rarity": defaultdict(int),
        "unique_universes": set(),
        "most_used": max(collection, key=lambda x: x["times_used"]) if collection else None
    }
    
    for char_data in collection:
        char_name = char_data["name"]
        if char_name in CHARACTERS:
            rarity = CHARACTERS[char_name]["rarity"]
            universe = CHARACTERS[char_name]["universe"]
            stats["by_rarity"][rarity] += 1
            stats["unique_universes"].add(universe)
    
    return stats

# === СИСТЕМА ДОСТИЖЕНИЙ ===
ACHIEVEMENTS = {
    "first_blood": {
        "name": "🩸 Первая кровь",
        "description": "Выиграть первую ставку",
        "reward": 100,
        "condition": "wins >= 1"
    },
    "pvp_master": {
        "name": "⚔️ Мастер PvP", 
        "description": "Выиграть 10 PvP битв",
        "reward": 500,
        "condition": "pvp_wins >= 10"
    },
    "rich_man": {
        "name": "💰 Криптомагнат",
        "description": "Накопить 5,000 монет", 
        "reward": 1000,
        "condition": "balance >= 5000"
    },
    "collector": {
        "name": "🎴 Коллекционер",
        "description": "Собрать 20 разных персонажей",
        "reward": 300,
        "condition": "unique_characters >= 20"
    },
    "seasonal_champion": {
        "name": f"{SEASON_EMOJI} Чемпион {SEASON_NAME}",
        "description": f"Выиграть 30 ставок в {SEASON_NAME.lower()}",
        "reward": 1000,
        "condition": f"season_wins >= 30"
    },
    "legendary_hunter": {
        "name": "⭐ Охотник за легендами",
        "description": "Получить 5 легендарных персонажей",
        "reward": 2000,
        "condition": "legendary_chars >= 5"
    }
}

def get_current_season_progress(user_id):
    """Получает прогресс текущего сезона для пользователя"""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        
        c.execute('''SELECT wins, bets, characters_collected 
                     FROM seasonal_progress 
                     WHERE user_id = ? AND season = ?''', (user_id, CURRENT_SEASON["theme"]))
        result = c.fetchone()
        
        if result:
            return {
                "wins": result[0],
                "bets": result[1],
                "characters_collected": result[2]
            }
        else:
            return {"wins": 0, "bets": 0, "characters_collected": 0}
            
    except sqlite3.Error as e:
        logger.error(f"Error getting season progress: {e}")
        return {"wins": 0, "bets": 0, "characters_collected": 0}
    finally:
        conn.close()

def check_achievements(user_id):
    """Проверяет и разблокирует достижения"""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        
        c.execute('''SELECT total_wins, pvp_wins, balance FROM users WHERE user_id = ?''', (user_id,))
        user_stats = c.fetchone()
        if not user_stats:
            return []
        
        wins, pvp_wins, balance = user_stats
        collection_stats = get_collection_stats(user_id)
        unique_chars = collection_stats["total"]
        legendary_chars = collection_stats["by_rarity"].get("legendary", 0)
        season_progress = get_current_season_progress(user_id)
        season_wins = season_progress["wins"]
        
        unlocked_achievements = []
        
        for achievement_id, achievement in ACHIEVEMENTS.items():
            c.execute('SELECT 1 FROM user_achievements WHERE user_id = ? AND achievement_id = ?', (user_id, achievement_id))
            if c.fetchone():
                continue
            
            condition_met = False
            condition = achievement["condition"]
            
            if "wins >= 1" in condition and wins >= 1:
                condition_met = True
            elif "pvp_wins >= 10" in condition and pvp_wins >= 10:
                condition_met = True
            elif "balance >= 5000" in condition and balance >= 5000:
                condition_met = True
            elif "unique_characters >= 20" in condition and unique_chars >= 20:
                condition_met = True
            elif "season_wins >= 30" in condition and season_wins >= 30:
                condition_met = True
            elif "legendary_chars >= 5" in condition and legendary_chars >= 5:
                condition_met = True
            
            if condition_met:
                today = datetime.datetime.now().isoformat()
                c.execute('''INSERT INTO user_achievements 
                             (user_id, achievement_id, unlocked_date) 
                             VALUES (?, ?, ?)''', (user_id, achievement_id, today))
                
                update_user_balance(user_id, achievement["reward"])
                unlocked_achievements.append(achievement)
        
        conn.commit()
        return unlocked_achievements
        
    except sqlite3.Error as e:
        logger.error(f"Error checking achievements: {e}")
        return []
    finally:
        conn.close()

def get_user_achievements(user_id):
    """Получает достижения пользователя"""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute('''SELECT ua.achievement_id, ua.unlocked_date, ua.reward_claimed 
                     FROM user_achievements ua
                     WHERE ua.user_id = ?''', (user_id,))
        
        achievements = []
        for row in c.fetchall():
            achievement_id, unlocked_date, reward_claimed = row
            if achievement_id in ACHIEVEMENTS:
                achievement = ACHIEVEMENTS[achievement_id].copy()
                achievement["unlocked_date"] = unlocked_date
                achievement["reward_claimed"] = bool(reward_claimed)
                achievements.append(achievement)
        
        return achievements
    except sqlite3.Error as e:
        logger.error(f"Error getting user achievements: {e}")
        return []
    finally:
        conn.close()

# === РЕФЕРАЛЬНАЯ СИСТЕМА ===
REFERRAL_SYSTEM = {
    "reward_per_friend": 100,
    "bonus_on_friend_deposit": 50,
    "level_rewards": {
        3: 300,
        5: 600,
        10: 1500
    }
}

def generate_referral_code(user_id):
    """Генерирует реферальный код"""
    return f"REF{user_id % 10000:04d}"

def handle_referral(user_id, referrer_code):
    """Обрабатывает реферальное приглашение"""
    if not referrer_code or not referrer_code.startswith("REF"):
        return False
    
    try:
        referrer_id = int(referrer_code[3:])
        if referrer_id == user_id:
            return False
        
        conn = get_db_connection()
        c = conn.cursor()
        
        c.execute('SELECT 1 FROM users WHERE user_id = ?', (referrer_id,))
        if not c.fetchone():
            return False
        
        c.execute('UPDATE users SET referrals_count = referrals_count + 1 WHERE user_id = ?', (referrer_id,))
        update_user_balance(referrer_id, REFERRAL_SYSTEM["reward_per_friend"])
        update_user_balance(user_id, 50)
        
        conn.commit()
        return True
        
    except (ValueError, sqlite3.Error) as e:
        logger.error(f"Error handling referral: {e}")
        return False
    finally:
        conn.close()

def get_referral_stats(user_id):
    """Получает статистику рефералов"""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute('SELECT referrals_count FROM users WHERE user_id = ?', (user_id,))
        result = c.fetchone()
        referrals_count = result[0] if result else 0
        
        next_reward = None
        for level, reward in sorted(REFERRAL_SYSTEM["level_rewards"].items()):
            if referrals_count < level:
                next_reward = {"level": level, "reward": reward, "needed": level - referrals_count}
                break
        
        return {
            "referrals_count": referrals_count,
            "next_reward": next_reward,
            "referral_code": generate_referral_code(user_id)
        }
    except sqlite3.Error as e:
        logger.error(f"Error getting referral stats: {e}")
        return {"referrals_count": 0, "next_reward": None, "referral_code": generate_referral_code(user_id)}
    finally:
        conn.close()

# === СЕЗОННАЯ СИСТЕМА ===
def update_seasonal_progress(user_id, win=False):
    """Обновляет сезонный прогресс"""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        
        if win:
            c.execute('UPDATE users SET total_wins = total_wins + 1 WHERE user_id = ?', (user_id,))
        c.execute('UPDATE users SET total_bets = total_bets + 1 WHERE user_id = ?', (user_id,))
        
        c.execute('''INSERT OR REPLACE INTO seasonal_progress 
                     (user_id, season, wins, bets, characters_collected) 
                     VALUES (?, ?, COALESCE((SELECT wins FROM seasonal_progress WHERE user_id = ? AND season = ?), 0) + ?,
                             COALESCE((SELECT bets FROM seasonal_progress WHERE user_id = ? AND season = ?), 0) + 1,
                             (SELECT COUNT(*) FROM user_collections WHERE user_id = ?))''',
                  (user_id, CURRENT_SEASON["theme"], user_id, CURRENT_SEASON["theme"], 1 if win else 0, 
                   user_id, CURRENT_SEASON["theme"], user_id))
        
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Error updating seasonal progress: {e}")
    finally:
        conn.close()

def get_seasonal_leaderboard():
    """Получает сезонную таблицу лидеров"""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute('''SELECT u.username, sp.wins, sp.bets, sp.characters_collected
                     FROM seasonal_progress sp
                     JOIN users u ON sp.user_id = u.user_id
                     WHERE sp.season = ?
                     ORDER BY sp.wins DESC, sp.characters_collected DESC
                     LIMIT 10''', (CURRENT_SEASON["theme"],))
        return [{"username": row[0], "wins": row[1], "bets": row[2], "characters": row[3]} for row in c.fetchall()]
    except sqlite3.Error as e:
        logger.error(f"Error getting seasonal leaderboard: {e}")
        return []
    finally:
        conn.close()

# === ВИЗУАЛЬНЫЕ УЛУЧШЕНИЯ ===
def format_character_display(character_name):
    """Форматирует отображение персонажа с эмодзи"""
    if character_name not in CHARACTERS:
        return character_name
    
    char_data = CHARACTERS[character_name]
    rarity_data = CHARACTER_RARITY[char_data["rarity"]]
    universe_emoji = UNIVERSE_EMOJIS.get(char_data["universe"], "🎮")
    
    return f"{rarity_data['emoji']} {universe_emoji} {character_name}"

def format_seasonal_message(text):
    """Добавляет сезонное оформление к сообщению"""
    return f"{SEASON_EMOJI} {text}"

# === СЕЗОННЫЙ МАГАЗИН ===
def get_seasonal_shop():
    """Возвращает товары для текущего сезона"""
    base_items = {
        "basic_box": {
            "name": "📦 Обычная колода",
            "description": "1 случайный персонаж (шанс на редкого)",
            "price": 100,
            "type": "gacha",
            "rarity_pool": ["common", "rare"]
        },
        "premium_box": {
            "name": "💎 Премиум колда",
            "description": "1 случайный персонаж (шанс на эпического)",
            "price": 300,
            "type": "gacha", 
            "rarity_pool": ["common", "rare", "epic"]
        },
        "legendary_box": {
            "name": "⭐ Легендарная колода",
            "description": "1 случайный персонаж (гарантированно эпический или выше)",
            "price": 800,
            "type": "gacha",
            "rarity_pool": ["epic", "legendary"]
        }
    }
    
    if CURRENT_SEASON["theme"] == "dragons":
        seasonal_items = {
            "dragon_box": {
                "name": "🐉 Драконья колода",
                "description": "Повышенный шанс получить Дань Хэнов и драконьих персонажей!",
                "price": 600,
                "type": "gacha",
                "rarity_pool": ["rare", "epic", "legendary"],
                "season_boost": True,
                "dragon_boost": True
            }
        }
        base_items.update(seasonal_items)
    
    return base_items

SEASONAL_SHOP = get_seasonal_shop()

# === ОСНОВНЫЕ КОМАНДЫ ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start с проверкой подписки"""
    user = update.effective_user
    
    # Проверяем подписку
    is_subscribed = await check_subscription(user.id, context)
    if not is_subscribed:
        await show_subscription_required(update, context)
        return
    
    # Обработка реферальных ссылок
    if context.args and context.args[0].startswith('ref_'):
        try:
            referrer_code = context.args[0][4:]
            handle_referral(user.id, referrer_code)
        except:
            pass
    
    # Обработка PvP deep links
    if context.args and context.args[0].startswith('pvp_'):
        try:
            creator_id = int(context.args[0].split('_')[1])
            await handle_pvp_deep_link(update, context, creator_id, user)
            return
        except (ValueError, IndexError):
            pass
    
    # Основное меню
    balance = get_user_balance_safe(user.id)
    referral_stats = get_referral_stats(user.id)
    
    keyboard = [
        [InlineKeyboardButton("🎰 Сделать ставку", callback_data="menu_bet")],
        [InlineKeyboardButton("⚔️ PvP с другом", callback_data="menu_pvp")],
        [InlineKeyboardButton("📚 Моя коллекция", callback_data="menu_collection")],
        [InlineKeyboardButton("🏪 Сезонный магазин", callback_data="menu_shop")],
        [InlineKeyboardButton("💰 Мой баланс", callback_data="menu_balance")],
        [InlineKeyboardButton("📅 Ежедневная награда", callback_data="menu_daily")],
        [InlineKeyboardButton("🏆 Таблица лидеров", callback_data="menu_leaderboard")],
        [InlineKeyboardButton("📊 Детальная статистика", callback_data="menu_detailed_stats")],
        [InlineKeyboardButton("🎯 Мои достижения", callback_data="menu_achievements")],
        [InlineKeyboardButton("👥 Реферальная система", callback_data="menu_referral")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    new_achievements = check_achievements(user.id)
    achievements_text = ""
    if new_achievements:
        achievements_text = f"\n\n🎉 Новые достижения!\n" + "\n".join([f"• {ach['name']} (+{ach['reward']} монет)" for ach in new_achievements])

    season_info = f"{SEASON_NAME} {SEASON_EMOJI}\n"
    if CURRENT_SEASON["theme"] == "dragons":
        season_info += "🐉 Особенности сезона:\n"
        season_info += "• Новые Дань Хэны: Пожиратель Луны и Освободитель Пустоши!\n"
        season_info += "• Увеличен шанс получить всех Дань Хэнов\n"

    await update.message.reply_text(
        f"""{format_seasonal_message(f"Привет, {user.first_name}! 👋")}

🎰 Добро пожаловать в систему ставок на битвы персонажей!

{season_info}
Твой баланс: {balance} монет 💰
Рефералов приглашено: {referral_stats['referrals_count']} 👥{achievements_text}

Выбери действие:""",
        reply_markup=reply_markup
    )

async def handle_pvp_deep_link(update: Update, context: ContextTypes.DEFAULT_TYPE, creator_id: int, user):
    """Обработка глубокой ссылки PvP"""
    user_id = user.id
    
    # Проверяем подписку
    is_subscribed = await check_subscription(user_id, context)
    if not is_subscribed:
        await show_subscription_required(update, context)
        return
    
    if user_id == creator_id:
        await update.message.reply_text(
            "❌ Нельзя принять свой же вызов!\n\n"
            "Создай вызов и отправь ссылку другу."
        )
        return
    
    if creator_id not in active_pvp_challenges:
        await update.message.reply_text(
            "❌ Вызов не найден или истек!\n\n"
            "Возможно, вызов был отменен или время его действия истекло."
        )
        return
    
    creator_data = active_pvp_challenges[creator_id]
    creator_name = creator_data['creator_name']
    
    keyboard = [
        [InlineKeyboardButton("✅ Принять вызов", callback_data=f"pvp_accept_{creator_id}")],
        [InlineKeyboardButton("❌ Отклонить", callback_data=f"pvp_decline_{creator_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"⚔️ PvP ВЫЗОВ! ⚔️\n\n"
        f"{creator_name} вызывает тебя на битву команд!\n\n"
        f"Приз: 100 монет 🪙\n"
        f"Ставка: 50 монет с игрока\n"
        f"Правила:\n"
        f"• Каждому выдаётся 5 случайных персонажей\n"
        f"• Выбери 3 в свою команду\n"
        f"• Побеждает команда с большей силой!\n\n"
        f"Готов сразиться?",
        reply_markup=reply_markup
    )

async def check_subscription_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик проверки подписки"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    is_subscribed = await check_subscription(user.id, context)
    
    if is_subscribed:
        await start(update, context)
    else:
        await query.message.reply_text(
            "❌ Вы все еще не подписаны на все каналы!\n\n"
            "Пожалуйста, подпишитесь на все каналы из списка и попробуйте снова."
        )

async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик меню"""
    query = update.callback_query
    await query.answer()
    
    # Проверяем подписку для всех действий
    is_subscribed = await check_subscription(query.from_user.id, context)
    if not is_subscribed:
        await show_subscription_required(update, context)
        return
    
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
    elif query.data == "menu_collection":
        await collection_command(query, context)
    elif query.data == "menu_shop":
        await shop_command(query, context)
    elif query.data == "menu_detailed_stats":
        await detailed_stats_command(query, context)
    elif query.data == "menu_season_leaderboard":
        await season_leaderboard_command(query, context)
    elif query.data == "menu_achievements":
        await achievements_command(query, context)
    elif query.data == "menu_referral":
        await referral_command(query, context)
    elif query.data == "menu_pvp":
        await pvp_command_from_menu(query, context)

async def balance_command_from_menu(query, context):
    """Проверить баланс"""
    user = query.from_user
    balance = get_user_balance_safe(user.id)
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="menu_back")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await safe_edit_message(query,
        f"💰 ТВОЙ БАЛАНС: {balance} монет\n\n"
        f"Используй кнопки ниже для ставок!",
        reply_markup=reply_markup
    )

async def daily_command_from_menu(query, context):
    """Ежедневная награда"""
    user = query.from_user
    
    # Проверяем подписку
    is_subscribed = await check_subscription(user.id, context)
    if not is_subscribed:
        await show_subscription_required(update, context)
        return
    
    # ПРОВЕРЯЕМ, МОЖНО ЛИ ПОЛУЧИТЬ НАГРАДУ
    if not can_get_daily_reward(user.id):
        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="menu_back")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await safe_edit_message(query,
            "⏰ ЕЖЕДНЕВНАЯ НАГРАДА ⏰\n\n"
            "Уже получена! ❌\n\n"
            "Приходи за новой наградой через 24 часа! ⏳\n\n"
            f"Текущий баланс: {get_user_balance_safe(user.id)} монет 💰",
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
            f"📅 ЕЖЕДНЕВНАЯ НАГРАДА 📅\n\n"
            f"Игрок: {user.first_name}\n"
            f"Награда: +{daily_reward} монет 💰\n\n"
            f"Новый баланс: {get_user_balance_safe(user.id)} монет\n\n"
            f"Следующая награда через 24 часа! ⏰",
            reply_markup=reply_markup
        )
    else:
        await safe_edit_message(query, "❌ Ошибка при получении награды!")

async def leaderboard_command_from_menu(query, context):
    """Таблица лидеров по балансу"""
    top_users = get_leaderboard()
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="menu_back")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if not top_users:
        await safe_edit_message(query,
            "🏆 ТАБЛИЦА ЛИДЕРОВ 🏆\n\n"
            "Пока здесь пусто!\n\n"
            "Стань первым в рейтинге! 🎯\n"
            "• Делай ставки через 🎰\n" 
            "• Получай ежедневные награды 📅\n"
            "• Выигрывай и поднимайся в топ! 💰\n\n"
            f"Твой баланс: {get_user_balance_safe(query.from_user.id)} монет",
            reply_markup=reply_markup
        )
        return
    
    leaderboard_text = "🏆 ТОП-10 БОГАЧЕЙ 🏆\n\n"
    
    for i, (username, balance, score) in enumerate(top_users, 1):
        medal = ""
        if i == 1: medal = "🥇"
        elif i == 2: medal = "🥈" 
        elif i == 3: medal = "🥉"
        else: medal = "💰"
        
        display_name = username if username else f"Игрок {i}"
        leaderboard_text += f"{medal} {i}. {display_name}\n"
        leaderboard_text += f"   Баланс: {balance} монет | Очки: {score}\n\n"
    
    # Получаем текущую позицию пользователя
    user_rank = get_user_rank(query.from_user.id)
    user_balance = get_user_balance_safe(query.from_user.id)
    
    leaderboard_text += f"Твоя позиция: #{user_rank} (Баланс: {user_balance} монет)"
    
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
        f"📊 ТВОЯ СТАТИСТИКА 📊\n\n"
        f"Баланс: {balance} монет 💰\n"
        f"PvP побед: {pvp_wins} 🏆\n"
        f"PvP поражений: {pvp_losses} 💀\n"
        f"Винрейт: {winrate:.1f}% 📈\n\n"
        f"Всего PvP битв: {total_pvp} ⚔️",
        reply_markup=reply_markup
    )

# === КОМАНДА КОЛЛЕКЦИИ ===
async def collection_command(query, context):
    """Показывает коллекцию персонажей"""
    user = query.from_user
    collection = get_user_collection(user.id)
    stats = get_collection_stats(user.id)
    
    if not collection:
        keyboard = [[InlineKeyboardButton("🏪 В магазин", callback_data="menu_shop")],
                   [InlineKeyboardButton("🔙 Назад", callback_data="menu_back")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await safe_edit_message(query,
            "📚 МОЯ КОЛЛЕКЦИЯ 📚\n\n"
            "Твоя коллекция пуста!\n\n"
            "🎴 Как получить персонажей:\n"
            "• Покупай колоды в магазине 🏪\n"
            "• Выигрывай в ставках 🎰\n"
            "• Участвуй в PvP битвах ⚔️\n"
            "• Получай сезонные награды " + SEASON_EMOJI,
            reply_markup=reply_markup
        )
        return
    
    characters_by_rarity = {}
    for char_data in collection:
        char_name = char_data["name"]
        if char_name in CHARACTERS:
            rarity = CHARACTERS[char_name]["rarity"]
            if rarity not in characters_by_rarity:
                characters_by_rarity[rarity] = []
            characters_by_rarity[rarity].append(char_data)
    
    text = "📚 МОЯ КОЛЛЕКЦИЯ 📚\n\n"
    text += f"Всего персонажей: {stats['total']}\n"
    
    for rarity, data in CHARACTER_RARITY.items():
        count = stats["by_rarity"].get(rarity, 0)
        text += f"{data['emoji']} {rarity.capitalize()}: {count}\n"
    
    text += f"\nВселенные: {len(stats['unique_universes'])}\n"
    
    for rarity, data in CHARACTER_RARITY.items():
        if rarity in characters_by_rarity:
            text += f"\n{data['emoji']} {rarity.upper()}:\n"
            for char_data in characters_by_rarity[rarity][:5]:
                char_name = char_data["name"]
                char_display = format_character_display(char_name)
                text += f"• {char_display} (использован: {char_data['times_used']} раз)\n"
            
            if len(characters_by_rarity[rarity]) > 5:
                text += f"• ... и еще {len(characters_by_rarity[rarity]) - 5}\n"
    
    keyboard = [[InlineKeyboardButton("🏪 Магазин", callback_data="menu_shop")],
                [InlineKeyboardButton("🔙 Назад", callback_data="menu_back")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await safe_edit_message(query, text, reply_markup)

# === КОМАНДА МАГАЗИНА ===
async def shop_command(query, context):
    """Показывает сезонный магазин"""
    user = query.from_user
    balance = get_user_balance_safe(user.id)
    
    text = f"{format_seasonal_message('🏪 СЕЗОННЫЙ МАГАЗИН 🏪')}\n\n"
    text += f"Твой баланс: {balance} монет 💰\n"
    text += f"Сезон: {SEASON_NAME} {SEASON_EMOJI}\n\n"
    
    for item_id, item in SEASONAL_SHOP.items():
        text += f"{item['name']}\n"
        text += f"{item['description']}\n"
        text += f"Цена: {item['price']} монет\n\n"
    
    keyboard = []
    for item_id, item in SEASONAL_SHOP.items():
        if balance >= item['price']:
            button_text = f"🛒 {item['name']} - {item['price']} монет"
        else:
            button_text = f"❌ {item['name']} - {item['price']} монет"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"buy_{item_id}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="menu_back")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await safe_edit_message(query, text, reply_markup)

async def buy_item_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка покупки в магазине"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    item_id = query.data.split('_')[1]
    
    if item_id not in SEASONAL_SHOP:
        await safe_edit_message(query, "❌ Товар не найден!")
        return
    
    item = SEASONAL_SHOP[item_id]
    balance = get_user_balance_safe(user.id)
    
    if balance < item['price']:
        await safe_edit_message(query, "❌ Недостаточно монет для покупки!")
        return
    
    success = update_user_balance_safe(user.id, -item['price'])
    if not success:
        await safe_edit_message(query, "❌ Ошибка при покупке!")
        return
    
    if item['type'] == 'gacha':
        await handle_gacha_purchase(query, context, user.id, item)
    
    check_achievements(user.id)

async def handle_gacha_purchase(query, context, user_id, item):
    """Обрабатывает покупку гача-колоды"""
    rarity_pool = []
    for rarity in item['rarity_pool']:
        base_chance = CHARACTER_RARITY[rarity]['chance']
        
        if item.get('season_boost'):
            base_chance = int(base_chance * 1.3)
        
        rarity_pool.extend([rarity] * base_chance)
    
    selected_rarity = random.choice(rarity_pool)
    
    available_chars = [name for name, data in CHARACTERS.items() 
                      if data['rarity'] == selected_rarity]
    
    if item.get('dragon_boost') and CURRENT_SEASON["theme"] == "dragons":
        dragon_chars = [name for name in available_chars 
                       if CURRENT_SEASON["theme"] in CHARACTERS[name].get("season_boost", [])]
        if dragon_chars:
            available_chars.extend(dragon_chars * 3)
    
    if not available_chars:
        await safe_edit_message(query, "❌ Ошибка: нет доступных персонажей!")
        update_user_balance_safe(user_id, item['price'])
        return
    
    selected_char = random.choice(available_chars)
    char_data = CHARACTERS[selected_char]
    
    added = add_character_to_collection(user_id, selected_char)
    
    if added:
        char_display = format_character_display(selected_char)
        rarity_emoji = CHARACTER_RARITY[selected_rarity]['emoji']
        
        season_boost_info = ""
        if CURRENT_SEASON["theme"] in char_data.get("season_boost", []):
            season_boost_info = f"\n🎁 СЕЗОННЫЙ БУСТ! Этот персонаж усилен в {SEASON_NAME}!"
        
        await safe_edit_message(query,
            f"🎉 ПОЗДРАВЛЯЕМ! 🎉\n\n"
            f"Ты получил нового персонажа:\n"
            f"{char_display}\n\n"
            f"Редкость: {selected_rarity.capitalize()} {rarity_emoji}\n"
            f"Сила: {char_data['power']}\n"
            f"Вселенная: {char_data['universe']} {UNIVERSE_EMOJIS.get(char_data['universe'], '🎮')}"
            f"{season_boost_info}\n\n"
            f"Персонаж добавлен в твою коллекцию! 📚"
        )
    else:
        await safe_edit_message(query,
            f"🎉 Ты получил: {format_character_display(selected_char)}\n\n"
            f"Но у тебя уже есть этот персонаж!\n"
            f"Попробуй другую колоду для новых персонажей."
        )

# === ДЕТАЛЬНАЯ СТАТИСТИКА ===
async def detailed_stats_command(query, context):
    """Показывает детальную статистику"""
    user = query.from_user
    user_id = user.id
    
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute('''SELECT total_wins, total_bets, pvp_wins, pvp_losses, balance, games_played 
                     FROM users WHERE user_id = ?''', (user_id,))
        result = c.fetchone()
        
        if not result:
            await safe_edit_message(query, "❌ Статистика не найдена!")
            return
        
        total_wins, total_bets, pvp_wins, pvp_losses, balance, games_played = result
        
        # Сезонная статистика
        season_progress = get_current_season_progress(user_id)
        season_wins = season_progress["wins"]
        season_bets = season_progress["bets"]
        
        # Рассчитываем проценты
        win_rate = (total_wins / total_bets * 100) if total_bets > 0 else 0
        pvp_total = pvp_wins + pvp_losses
        pvp_win_rate = (pvp_wins / pvp_total * 100) if pvp_total > 0 else 0
        season_win_rate = (season_wins / season_bets * 100) if season_bets > 0 else 0
        
        # Статистика коллекции
        collection_stats = get_collection_stats(user_id)
        
        text = f"{format_seasonal_message('📊 ДЕТАЛЬНАЯ СТАТИСТИКА 📊')}\n\n"
        
        text += f"{SEASON_EMOJI} {SEASON_NAME}\n"
        text += f"• Побед: {season_wins}/{season_bets} ({season_win_rate:.1f}%)\n\n"
        
        text += f"👤 Общая статистика:\n"
        text += f"• Всего ставок: {total_bets}\n"
        text += f"• Побед: {total_wins} ({win_rate:.1f}%)\n"
        text += f"• Игр сыграно: {games_played}\n"
        text += f"• Баланс: {balance} монет\n\n"
        
        text += f"⚔️ PvP статистика:\n"
        text += f"• Побед: {pvp_wins}\n"
        text += f"• Поражений: {pvp_losses}\n"
        text += f"• Винрейт: {pvp_win_rate:.1f}%\n\n"
        
        text += f"📚 Коллекция:\n"
        text += f"• Всего персонажей: {collection_stats['total']}\n"
        for rarity, data in CHARACTER_RARITY.items():
            count = collection_stats['by_rarity'].get(rarity, 0)
            text += f"• {data['emoji']} {rarity.capitalize()}: {count}\n"
        text += f"• Вселенных: {len(collection_stats['unique_universes'])}\n"
        
    except sqlite3.Error as e:
        logger.error(f"Error getting detailed stats: {e}")
        text = "❌ Ошибка загрузки статистики"
    finally:
        conn.close()
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="menu_back")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await safe_edit_message(query, text, reply_markup)

# === СЕЗОННЫЙ РЕЙТИНГ ===
async def season_leaderboard_command(query, context):
    """Показывает сезонный рейтинг"""
    leaderboard = get_seasonal_leaderboard()
    
    text = f"{format_seasonal_message('🏆 СЕЗОННЫЙ РЕЙТИНГ 🏆')}\n\n"
    text += f"Сезон: {SEASON_NAME} {SEASON_EMOJI}\n\n"
    
    if not leaderboard:
        text += "Пока здесь пусто!\nБудь первым в сезонном рейтинге! 🎯"
    else:
        for i, player in enumerate(leaderboard, 1):
            medal = ""
            if i == 1: medal = "🥇"
            elif i == 2: medal = "🥈" 
            elif i == 3: medal = "🥉"
            else: medal = "🏅"
            
            username = player['username'] if player['username'] else f"Игрок {i}"
            text += f"{medal} {i}. {username}\n"
            text += f"   Побед: {player['wins']} | Ставок: {player['bets']} | Персонажей: {player['characters']}\n\n"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="menu_back")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await safe_edit_message(query, text, reply_markup)

# === СИСТЕМА ДОСТИЖЕНИЙ ===
async def achievements_command(query, context):
    """Показывает достижения пользователя"""
    user = query.from_user
    achievements = get_user_achievements(user.id)
    
    text = f"{format_seasonal_message('🎯 МОИ ДОСТИЖЕНИЯ 🎯')}\n\n"
    
    if not achievements:
        text += "У тебя пока нет достижений!\n\n"
        text += "Как получить достижения:\n"
        text += "• Выигрывай в ставках 🎰\n"
        text += "• Собирай коллекцию персонажей 📚\n"
        text += "• Участвуй в PvP битвах ⚔️\n"
        text += "• Накопи богатство 💰\n"
    else:
        text += f"Получено: {len(achievements)}/{len(ACHIEVEMENTS)} достижений\n\n"
        
        for achievement in achievements:
            status = "✅" if achievement.get("reward_claimed", True) else "🔄"
            text += f"{status} {achievement['name']}\n"
            text += f"{achievement['description']}\n"
            text += f"Награда: {achievement['reward']} монет\n"
            if achievement.get('unlocked_date'):
                text += f"Получено: {achievement['unlocked_date'][:10]}\n"
            text += "\n"
    
    all_achievement_ids = set(ACHIEVEMENTS.keys())
    unlocked_ids = set(ach['name'] for ach in achievements)
    locked_ids = all_achievement_ids - unlocked_ids
    
    if locked_ids:
        text += "🎯 Ближайшие цели:\n"
        for achievement_id in list(locked_ids)[:3]:
            achievement = ACHIEVEMENTS[achievement_id]
            text += f"• {achievement['name']}\n"
            text += f"  {achievement['description']}\n"
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="menu_back")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await safe_edit_message(query, text, reply_markup)

# === РЕФЕРАЛЬНАЯ СИСТЕМА ===
async def referral_command(query, context):
    """Показывает реферальную систему"""
    user = query.from_user
    stats = get_referral_stats(user.id)
    
    text = f"{format_seasonal_message('👥 РЕФЕРАЛЬНАЯ СИСТЕМА 👥')}\n\n"
    
    text += f"Твоя статистика:\n"
    text += f"• Приглашено друзей: {stats['referrals_count']}\n"
    text += f"• Твой реферальный код: {stats['referral_code']}\n\n"
    
    text += f"🎁 Как это работает:\n"
    text += f"• За каждого приглашенного друга: {REFERRAL_SYSTEM['reward_per_friend']} монет\n"
    text += f"• Друг получает бонус при регистрации: 50 монет\n\n"
    
    text += f"🏆 Уровневые награды:\n"
    for level, reward in REFERRAL_SYSTEM['level_rewards'].items():
        status = "✅" if stats['referrals_count'] >= level else "⏳"
        text += f"{status} {level} друзей - {reward} монет\n"
    
    if stats['next_reward']:
        text += f"\n🎯 До следующей награды:\n"
        text += f"• Нужно пригласить: {stats['next_reward']['needed']} друзей\n"
        text += f"• Награда: {stats['next_reward']['reward']} монет\n"
    
    text += f"\n📢 Твоя реферальная ссылка:\n"
    text += f"https://t.me/{(await context.bot.get_me()).username}?start=ref_{stats['referral_code']}\n\n"
    text += f"Отправь эту ссылку друзьям и получай награды!"
    
    keyboard = [
        [InlineKeyboardButton("📊 Общая статистика", callback_data="menu_detailed_stats")],
        [InlineKeyboardButton("🔙 Назад", callback_data="menu_back")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await safe_edit_message(query, text, reply_markup)

# === СИСТЕМА СТАВОК ===
async def bet_command_from_menu(query, context):
    """Начало ставки из меню"""
    user = query.from_user
    
    # Проверяем подписку
    is_subscribed = await check_subscription(user.id, context)
    if not is_subscribed:
        await show_subscription_required(update, context)
        return
    
    balance = get_user_balance_safe(user.id)
    
    if 'current_bet' in context.user_data:
        del context.user_data['current_bet']
    if 'current_battle' in context.user_data:
        del context.user_data['current_battle']
    
    if balance < 10:
        await safe_edit_message(query,
            f"❌ Недостаточно монет!\n\n"
            f"Твой баланс: {balance} монет\n"
            f"Минимальная ставка: 10 монет\n\n"
            f"Получи ежедневную награду или пригласи друзей!"
        )
        return
    
    characters_list = list(CHARACTERS.keys())
    if len(characters_list) < 2:
        await safe_edit_message(query, "❌ Ошибка: недостаточно персонажей для битвы")
        return
    
    char1_name, char2_name = random.sample(characters_list, 2)
    while char1_name == char2_name:
        char2_name = random.choice(characters_list)
    
    char1 = CHARACTERS[char1_name]
    char2 = CHARACTERS[char2_name]
    
    season_boost_1 = 1.15 if CURRENT_SEASON["theme"] in char1.get("season_boost", []) else 1.0
    season_boost_2 = 1.15 if CURRENT_SEASON["theme"] in char2.get("season_boost", []) else 1.0
    
    char1_power_boosted = int(char1['power'] * season_boost_1)
    char2_power_boosted = int(char2['power'] * season_boost_2)
    
    context.user_data['current_battle'] = {
        'char1': char1_name,
        'char2': char2_name,
        'char1_power': char1_power_boosted,
        'char2_power': char2_power_boosted,
        'char1_universe': char1['universe'],
        'char2_universe': char2['universe'],
        'char1_season_boosted': season_boost_1 > 1.0,
        'char2_season_boosted': season_boost_2 > 1.0
    }
    
    keyboard = [
        [InlineKeyboardButton(f"💰 Ставка 10 монет (x1.5)", callback_data="bet_10")],
        [InlineKeyboardButton(f"💰 Ставка 25 монет (x2.0)", callback_data="bet_25")],
        [InlineKeyboardButton(f"💰 Ставка 50 монет (x2.5)", callback_data="bet_50")],
        [InlineKeyboardButton(f"💰 Ставка 100 монет (x3.0)", callback_data="bet_100")],
        [InlineKeyboardButton("🔙 Назад", callback_data="menu_back")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    season_info = ""
    if season_boost_1 > 1.0:
        season_info += f"🎁 Сезонный бонус! {char1_name} получает +15% силы\n"
    if season_boost_2 > 1.0:
        season_info += f"🎁 Сезонный бонус! {char2_name} получает +15% силы\n"
    
    await safe_edit_message(query,
        f"🎰 СТАВКА НА БИТВУ 🎰\n\n"
        f"{format_character_display(char1_name)} ({char1_power_boosted} силы)\n"
        f"⚡ ПРОТИВ ⚡\n"
        f"{format_character_display(char2_name)} ({char2_power_boosted} силы)\n\n"
        f"{season_info}\n"
        f"Твой баланс: {balance} монет\n"
        f"Выбери сумму ставки:",
        reply_markup=reply_markup
    )

async def bet_selection_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора суммы ставки"""
    query = update.callback_query
    await query.answer()
    
    # Проверяем подписку
    is_subscribed = await check_subscription(query.from_user.id, context)
    if not is_subscribed:
        await show_subscription_required(update, context)
        return
    
    if not query.data or not query.data.startswith('bet_'):
        logger.warning(f"Invalid bet callback data: {query.data}")
        await safe_edit_message(query, "❌ Ошибка: неверные данные")
        return
    
    try:
        bet_amount = int(query.data.split('_')[1])
        valid_amounts = [10, 25, 50, 100]
        if bet_amount not in valid_amounts:
            raise ValueError("Invalid bet amount")
    except (ValueError, IndexError) as e:
        logger.warning(f"Invalid bet amount in callback: {query.data}, error: {e}")
        await safe_edit_message(query, "❌ Ошибка: неверная сумма ставки")
        return
    
    user = query.from_user
    
    balance = get_user_balance_safe(user.id)
    if balance < bet_amount:
        await safe_edit_message(query,
            f"❌ Недостаточно монет!\n\n"
            f"Ты хотел поставить: {bet_amount} монет\n"
            f"Твой баланс: {balance} монет\n\n"
            f"Используй /start для новой ставки"
        )
        return
    
    context.user_data['current_bet'] = {
        'amount': bet_amount,
        'multiplier': {10: 1.5, 25: 2.0, 50: 2.5, 100: 3.0}[bet_amount]
    }
    
    battle_data = context.user_data.get('current_battle')
    if not battle_data:
        await safe_edit_message(query, "❌ Ошибка! Начни новую ставку через /start")
        return
    
    keyboard = [
        [InlineKeyboardButton(f"🎯 Ставка на {battle_data['char1']}", callback_data="choose_1")],
        [InlineKeyboardButton(f"🎯 Ставка на {battle_data['char2']}", callback_data="choose_2")],
        [InlineKeyboardButton(f"❌ Отмена", callback_data="cancel_bet")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await safe_edit_message(query,
        f"🎯 ВЫБОР ПОБЕДИТЕЛЯ 🎯\n\n"
        f"Ставка: {bet_amount} монет\n"
        f"Множитель: x{context.user_data['current_bet']['multiplier']}\n"
        f"Выигрыш: {int(bet_amount * context.user_data['current_bet']['multiplier'])} монет\n\n"
        f"На кого ставишь?",
        reply_markup=reply_markup
    )

async def choose_fighter_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора бойца"""
    query = update.callback_query
    await query.answer()
    
    # Проверяем подписку
    is_subscribed = await check_subscription(query.from_user.id, context)
    if not is_subscribed:
        await show_subscription_required(update, context)
        return
    
    if not query.data or not query.data.startswith('choose_'):
        logger.warning(f"Invalid fighter callback data: {query.data}")
        await safe_edit_message(query, "❌ Ошибка: неверные данные")
        return
    
    try:
        chosen_fighter = int(query.data.split('_')[1])
        if chosen_fighter not in [1, 2]:
            raise ValueError("Invalid fighter choice")
    except (ValueError, IndexError) as e:
        logger.warning(f"Invalid fighter choice in callback: {query.data}, error: {e}")
        await safe_edit_message(query, "❌ Ошибка: неверный выбор бойца")
        return
    
    user = query.from_user
    
    battle_data = context.user_data.get('current_battle')
    bet_data = context.user_data.get('current_bet')
    
    if not battle_data or not bet_data:
        await safe_edit_message(query, "❌ Ошибка! Данные о ставке утеряны. Начни новую ставку через /start")
        return
    
    total_power = battle_data['char1_power'] + battle_data['char2_power']
    char1_chance = battle_data['char1_power'] / total_power
    char2_chance = battle_data['char2_power'] / total_power
    
    winner = 1 if random.random() < char1_chance else 2
    
    if chosen_fighter == winner:
        win_amount = int(bet_data['amount'] * bet_data['multiplier'])
        success = update_user_balance_safe(user.id, win_amount)
        result_text = f"🎉 ПОБЕДА! +{win_amount} монет!" if success else "🎉 ПОБЕДА! (ошибка начисления)"
        result_emoji = "✅"
        update_seasonal_progress(user.id, win=True)
        
        if random.random() < 0.3:
            loser_name = battle_data['char2'] if winner == 1 else battle_data['char1']
            add_character_to_collection(user.id, loser_name)
    else:
        success = update_user_balance_safe(user.id, -bet_data['amount'])
        result_text = f"💥 ПРОИГРЫШ! -{bet_data['amount']} монет" if success else "💥 ПРОИГРЫШ! (ошибка списания)"
        result_emoji = "❌"
        update_seasonal_progress(user.id, win=False)
    
    if success:
        update_user_score(user.id, user.username, 1)
    
    if 'current_bet' in context.user_data:
        del context.user_data['current_bet']
    if 'current_battle' in context.user_data:
        del context.user_data['current_battle']
    
    winner_name = battle_data['char1'] if winner == 1 else battle_data['char2']
    loser_name = battle_data['char2'] if winner == 1 else battle_data['char1']
    
    current_balance = get_user_balance_safe(user.id)
    
    season_bonus_info = ""
    if battle_data.get('char1_season_boosted') and winner == 1:
        season_bonus_info = f"\n🎁 Сезонный бонус сыграл роль!"
    elif battle_data.get('char2_season_boosted') and winner == 2:
        season_bonus_info = f"\n🎁 Сезонный бонус сыграл роль!"
    
    await safe_edit_message(query,
        f"⚔️ РЕЗУЛЬТАТ БИТВЫ ⚔️\n\n"
        f"{UNIVERSE_EMOJIS[battle_data['char1_universe']]} {battle_data['char1']} 🆚 "
        f"{UNIVERSE_EMOJIS[battle_data['char2_universe']]} {battle_data['char2']}\n\n"
        f"🏆 ПОБЕДИТЕЛЬ: {winner_name}\n"
        f"💀 ПРОИГРАВШИЙ: {loser_name}\n\n"
        f"ТВОЯ СТАВКА: на {battle_data['char1'] if chosen_fighter == 1 else battle_data['char2']}\n"
        f"СТАВКА: {bet_data['amount']} монет\n"
        f"МНОЖИТЕЛЬ: x{bet_data['multiplier']}\n\n"
        f"{result_emoji} {result_text}{season_bonus_info}\n\n"
        f"Новый баланс: {current_balance} монет\n\n"
        f"Следующая ставка: /start"
    )
    
    check_achievements(user.id)

async def cancel_bet_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка отмены ставки"""
    query = update.callback_query
    await query.answer()
    
    if 'current_bet' in context.user_data:
        del context.user_data['current_bet']
    if 'current_battle' in context.user_data:
        del context.user_data['current_battle']
    
    text = "❌ Ставка отменена\n\nВсе данные о текущей ставке очищены.\n\nИспользуй /start для возврата в меню"
    
    await safe_edit_message(query, text)

# === PvP СИСТЕМА ===
async def pvp_command_from_menu(query, context):
    """Меню PvP"""
    user = query.from_user
    
    # Проверяем подписку
    is_subscribed = await check_subscription(user.id, context)
    if not is_subscribed:
        await show_subscription_required(update, context)
        return
    
    keyboard = [
        [InlineKeyboardButton("🎯 Создать вызов", callback_data="pvp_create")],
        [InlineKeyboardButton("❌ Отменить вызов", callback_data="pvp_cancel")],
        [InlineKeyboardButton("🔙 Назад", callback_data="menu_back")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await safe_edit_message(query,
        f"⚔️ PvP СИСТЕМА ⚔️\n\n"
        f"Привет, {user.first_name}!\n\n"
        f"Как работает PvP:\n"
        f"• Создай вызов и получи ссылку для друга\n"
        f"• Друг переходит по ссылке и принимает вызов\n"
        f"• Каждому выдаётся 5 случайных персонажей\n"
        f"• Выбери 3 персонажа в свою команду\n"
        f"• Побеждает команда с большей суммарной силой!\n\n"
        f"Ставка: 50 монет с каждого игрока\n"
        f"Выигрыш: 100 монет победителю!\n\n"
        f"Твой баланс: {get_user_balance_safe(user.id)} монет\n"
        f"Выбери действие:",
        reply_markup=reply_markup
    )

async def pvp_create_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создание PvP вызова"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    user_id = user.id
    
    # Проверяем подписку
    is_subscribed = await check_subscription(user_id, context)
    if not is_subscribed:
        await show_subscription_required(update, context)
        return
    
    balance = get_user_balance_safe(user_id)
    if balance < 50:
        await safe_edit_message(query,
            f"❌ Недостаточно монет для PvP!\n\n"
            f"Требуется: 50 монет\n"
            f"Твой баланс: {balance} монет\n\n"
            f"Получи ежедневную награду или выиграй в обычных ставках!"
        )
        return
    
    if user_id in active_pvp_challenges:
        await safe_edit_message(query,
            "⚠️ У тебя уже есть активный вызов!\n\n"
            "Дождись ответа или отмени текущий вызов."
        )
        return
    
    challenge_id = f"pvp_{user_id}_{int(time.time())}"
    active_pvp_challenges[user_id] = {
        'challenge_id': challenge_id,
        'created_at': time.time(),
        'creator_name': user.first_name,
        'creator_username': user.username,
        'creator_id': user_id
    }
    
    deep_link = f"https://t.me/{context.bot.username}?start=pvp_{user_id}"
    
    await safe_edit_message(query,
        f"🎯 ВЫЗОВ СОЗДАН! 🎯\n\n"
        f"Твой вызов готов!\n\n"
        f"Отправь другу эту ссылку:\n"
        f"{deep_link}\n\n"
        f"Или эту команду:\n"
        f"/start pvp_{user_id}\n\n"
        f"Как принять вызов:\n"
        f"1. Друг переходит по ссылке\n"
        f"2. Нажимает 'Принять вызов'\n"
        f"3. Выбирает команду из 3 персонажей\n"
        f"4. Начинается битва!\n\n"
        f"Вызов активен 5 минут. ⏰\n"
        f"Ставка: 50 монет с каждого игрока\n"
        f"Приз: 100 монет победителю! 🏆"
    )
    
    asyncio.create_task(pvp_challenge_timeout(user_id, context))

async def pvp_accept_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принятие PvP вызова"""
    query = update.callback_query
    await query.answer()
    
    # Проверяем подписку
    is_subscribed = await check_subscription(query.from_user.id, context)
    if not is_subscribed:
        await show_subscription_required(update, context)
        return
    
    try:
        creator_id = int(query.data.split('_')[-1])
    except (ValueError, IndexError):
        await safe_edit_message(query, "❌ Ошибка: неверный вызов")
        return
    
    user = query.from_user
    user_id = user.id
    
    if user_id == creator_id:
        await safe_edit_message(query, "❌ Нельзя принять свой же вызов!")
        return
    
    if creator_id not in active_pvp_challenges:
        await safe_edit_message(query, "❌ Вызов не найден или истек!")
        return
    
    creator_name = active_pvp_challenges[creator_id]['creator_name']
    
    creator_balance = get_user_balance_safe(creator_id)
    acceptor_balance = get_user_balance_safe(user_id)
    
    if creator_balance < 50 or acceptor_balance < 50:
        if creator_id in active_pvp_challenges:
            del active_pvp_challenges[creator_id]
        await safe_edit_message(query, "❌ У одного из игроков недостаточно монет!")
        return
    
    success1 = update_user_balance_safe(creator_id, -50)
    success2 = update_user_balance_safe(user_id, -50)
    
    if not success1 or not success2:
        await safe_edit_message(query, "❌ Ошибка при списании ставок!")
        return
    
    characters_list = list(CHARACTERS.keys())
    
    if len(characters_list) < 10:
        await safe_edit_message(query, "❌ Ошибка: недостаточно персонажей в базе")
        update_user_balance_safe(creator_id, 50)
        update_user_balance_safe(user_id, 50)
        return
    
    creator_characters = random.sample(characters_list, 5)
    remaining_chars = [c for c in characters_list if c not in creator_characters]
    if len(remaining_chars) < 5:
        acceptor_characters = random.sample(characters_list, 5)
    else:
        acceptor_characters = random.sample(remaining_chars, 5)
    
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
    
    if creator_id in active_pvp_challenges:
        del active_pvp_challenges[creator_id]
    
    await send_team_selection_menu(context, creator_id)
    await send_team_selection_menu(context, user_id)
    
    await safe_edit_message(query,
        f"✅ ВЫЗОВ ПРИНЯТ! ✅\n\n"
        f"Ты принял вызов от {creator_name}!\n\n"
        f"Теперь выбери 3 персонажа из 5 доступных для своей команды.\n"
        f"С твоего счета списано 50 монет. 💰"
    )
    
    try:
        await context.bot.send_message(
            chat_id=creator_id,
            text=f"✅ ТВОЙ PvP ВЫЗОВ ПРИНЯТ! ✅\n\n"
                 f"{user.first_name} принял твой вызов!\n\n"
                 f"Теперь выбери 3 персонажа из 5 доступных для своей команды.\n"
                 f"С твоего счета списано 50 монет. 💰"
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
    
    keyboard = []
    for i, char_name in enumerate(characters, 1):
        char_data = CHARACTERS.get(char_name, {})
        power = char_data.get('power', 0)
        emoji = "✅" if char_name in team_data.get('selected_team', []) else "⚪"
        button_text = f"{emoji} {char_name} ({power})"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"pvp_select_{user_id}_{i}")])
    
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
            text=f"⚔️ ВЫБОР КОМАНДЫ ⚔️\n\n"
                 f"Выбери 3 персонажа для своей команды:\n\n"
                 f"Доступные персонажи:\n" +
                 "\n".join([f"{i}. {char} ({CHARACTERS.get(char, {}).get('power', 0)} силы)" 
                           for i, char in enumerate(characters, 1)]) +
                 f"\n\nВыбрано: {selected_count}/3 персонажей\n"
                 f"Суммарная сила команды: {team_power}\n\n"
                 f"Нажми на персонажа чтобы добавить/убрать из команды.",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Error sending team selection menu to {user_id}: {e}")

async def pvp_select_character_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора персонажа в команду"""
    query = update.callback_query
    await query.answer()
    
    # Проверяем подписку
    is_subscribed = await check_subscription(query.from_user.id, context)
    if not is_subscribed:
        await show_subscription_required(update, context)
        return
    
    try:
        data_parts = query.data.split('_')
        target_user_id = int(data_parts[2])
        char_index = int(data_parts[3]) - 1
    except (ValueError, IndexError):
        await safe_edit_message(query, "❌ Ошибка выбора персонажа")
        return
    
    user_id = query.from_user.id
    
    if user_id != target_user_id or user_id not in pvp_team_selection:
        await safe_edit_message(query, "❌ Ошибка доступа")
        return
    
    team_data = pvp_team_selection[user_id]
    characters = team_data.get('characters', [])
    
    if char_index < 0 or char_index >= len(characters):
        await safe_edit_message(query, "❌ Неверный индекс персонажа")
        return
    
    selected_char = characters[char_index]
    selected_team = team_data.get('selected_team', [])
    
    if selected_char in selected_team:
        selected_team.remove(selected_char)
    else:
        if len(selected_team) < 3:
            selected_team.append(selected_char)
        else:
            await query.answer("❌ Можно выбрать только 3 персонажа!", show_alert=True)
            return
    
    team_data['selected_team'] = selected_team
    
    await send_team_selection_menu(context, user_id)
    
    try:
        await query.message.delete()
    except:
        pass

async def pvp_confirm_team_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение выбранной команды"""
    query = update.callback_query
    await query.answer()
    
    # Проверяем подписку
    is_subscribed = await check_subscription(query.from_user.id, context)
    if not is_subscribed:
        await show_subscription_required(update, context)
        return
    
    try:
        target_user_id = int(query.data.split('_')[2])
    except (ValueError, IndexError):
        await safe_edit_message(query, "❌ Ошибка подтверждения")
        return
    
    user_id = query.from_user.id
    
    if user_id != target_user_id or user_id not in pvp_team_selection:
        await safe_edit_message(query, "❌ Ошибка доступа")
        return
    
    team_data = pvp_team_selection[user_id]
    selected_team = team_data.get('selected_team', [])
    
    if len(selected_team) != 3:
        await query.answer("❌ Выбери ровно 3 персонажа!", show_alert=True)
        return
    
    team_data['ready'] = True
    
    team_power = sum(CHARACTERS.get(char, {}).get('power', 0) for char in selected_team)
    
    await safe_edit_message(query,
        f"✅ КОМАНДА ПОДТВЕРЖДЕНА! ✅\n\n"
        f"Твоя команда:\n" +
        "\n".join([f"• {char} ({CHARACTERS.get(char, {}).get('power', 0)} силы)" 
                  for char in selected_team]) +
        f"\n\nСуммарная сила: {team_power}\n\n"
        f"Ожидаем подтверждения противника..."
    )
    
    opponent_id = team_data['opponent_id']
    if opponent_id in pvp_team_selection and pvp_team_selection[opponent_id].get('ready'):
        await start_pvp_battle(context, user_id, opponent_id)

async def start_pvp_battle(context, player1_id, player2_id):
    """Начинает PvP битву между двумя игроками"""
    if player1_id not in pvp_team_selection or player2_id not in pvp_team_selection:
        return
    
    player1_data = pvp_team_selection[player1_id]
    player2_data = pvp_team_selection[player2_id]
    
    player1_team = player1_data.get('selected_team', [])
    player2_team = player2_data.get('selected_team', [])
    
    if len(player1_team) != 3 or len(player2_team) != 3:
        logger.error("Invalid team selection in PvP battle")
        return
    
    team1_power = sum(CHARACTERS.get(char, {}).get('power', 0) for char in player1_team)
    team2_power = sum(CHARACTERS.get(char, {}).get('power', 0) for char in player2_team)
    
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
        winner_id = random.choice([player1_id, player2_id])
        loser_id = player2_id if winner_id == player1_id else player1_id
        winner_name = player1_data['player_name'] if winner_id == player1_id else player2_data['player_name']
        loser_name = player2_data['player_name'] if winner_id == player1_id else player1_data['player_name']
    
    update_user_balance_safe(winner_id, 100)
    update_pvp_stats(winner_id, loser_id)
    
    update_user_score(winner_id, "", 5)
    update_user_score(loser_id, "", 2)
    
    battle_text = f"⚔️ PvP БИТВА ЗАВЕРШЕНА! ⚔️\n\n"
    battle_text += f"{player1_data['player_name']} 🆚 {player2_data['player_name']}\n\n"
    
    battle_text += f"Команда {player1_data['player_name']}:\n"
    for char in player1_team:
        power = CHARACTERS.get(char, {}).get('power', 0)
        battle_text += f"• {char} ({power} силы)\n"
    battle_text += f"Суммарно: {team1_power} силы\n\n"
    
    battle_text += f"Команда {player2_data['player_name']}:\n"
    for char in player2_team:
        power = CHARACTERS.get(char, {}).get('power', 0)
        battle_text += f"• {char} ({power} силы)\n"
    battle_text += f"Суммарно: {team2_power} силы\n\n"
    
    battle_text += f"🏆 ПОБЕДИТЕЛЬ: {winner_name}\n"
    battle_text += f"💰 Выигрыш: 100 монет!\n\n"
    battle_text += f"Новые балансы:\n"
    battle_text += f"• {winner_name}: {get_user_balance_safe(winner_id)} монет\n"
    battle_text += f"• {loser_name}: {get_user_balance_safe(loser_id)} монет"
    
    try:
        await context.bot.send_message(chat_id=player1_id, text=battle_text)
        await context.bot.send_message(chat_id=player2_id, text=battle_text)
    except Exception as e:
        logger.error(f"Error sending battle results: {e}")
    
    if player1_id in pvp_team_selection:
        del pvp_team_selection[player1_id]
    if player2_id in pvp_team_selection:
        del pvp_team_selection[player2_id]

async def pvp_cancel_battle_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена битвы во время выбора команды"""
    query = update.callback_query
    await query.answer()
    
    # Проверяем подписку
    is_subscribed = await check_subscription(query.from_user.id, context)
    if not is_subscribed:
        await show_subscription_required(update, context)
        return
    
    try:
        target_user_id = int(query.data.split('_')[3])
    except (ValueError, IndexError):
        await safe_edit_message(query, "❌ Ошибка отмены")
        return
    
    user_id = query.from_user.id
    
    if user_id != target_user_id or user_id not in pvp_team_selection:
        await safe_edit_message(query, "❌ Ошибка доступа")
        return
    
    team_data = pvp_team_selection[user_id]
    opponent_id = team_data.get('opponent_id')
    
    if opponent_id:
        update_user_balance_safe(user_id, 50)
        update_user_balance_safe(opponent_id, 50)
    
    if user_id in pvp_team_selection:
        del pvp_team_selection[user_id]
    if opponent_id and opponent_id in pvp_team_selection:
        del pvp_team_selection[opponent_id]
    
    await safe_edit_message(query, "❌ Битва отменена. Ставки возвращены.")
    
    if opponent_id:
        try:
            await context.bot.send_message(
                chat_id=opponent_id,
                text="❌ Противник отменил битву. Ставки возвращены."
            )
        except Exception as e:
            logger.error(f"Error notifying opponent about battle cancel: {e}")

async def pvp_decline_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отклонение PvP вызова"""
    query = update.callback_query
    await query.answer()
    
    # Проверяем подписку
    is_subscribed = await check_subscription(query.from_user.id, context)
    if not is_subscribed:
        await show_subscription_required(update, context)
        return
    
    try:
        creator_id = int(query.data.split('_')[-1])
    except (ValueError, IndexError):
        await safe_edit_message(query, "❌ Ошибка: неверный вызов")
        return
    
    if creator_id in active_pvp_challenges:
        del active_pvp_challenges[creator_id]
    
    await safe_edit_message(query, "❌ Вызов отклонен")
    
    try:
        await context.bot.send_message(
            chat_id=creator_id,
            text=f"❌ Твой PvP вызов был отклонен"
        )
    except Exception as e:
        logger.error(f"Error notifying challenge creator about decline: {e}")

async def pvp_cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена PvP вызова"""
    query = update.callback_query
    await query.answer()
    
    # Проверяем подписку
    is_subscribed = await check_subscription(query.from_user.id, context)
    if not is_subscribed:
        await show_subscription_required(update, context)
        return
    
    user_id = query.from_user.id
    
    if user_id in active_pvp_challenges:
        del active_pvp_challenges[user_id]
        await safe_edit_message(query, "✅ Вызов отменен")
    else:
        await safe_edit_message(query, "❌ У тебя нет активных вызовов")

async def pvp_challenge_timeout(user_id, context):
    """Таймаут для PvP вызова"""
    await asyncio.sleep(300)
    
    if user_id in active_pvp_challenges:
        del active_pvp_challenges[user_id]
        
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="⏰ Время твоего PvP вызова истекло"
            )
        except Exception as e:
            logger.error(f"Error notifying about challenge timeout: {e}")

# === ОБНОВЛЕННОЕ ГЛАВНОЕ МЕНЮ ===
async def menu_back_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню"""
    query = update.callback_query
    await query.answer()
    
    # Проверяем подписку
    is_subscribed = await check_subscription(query.from_user.id, context)
    if not is_subscribed:
        await show_subscription_required(update, context)
        return
    
    user = query.from_user
    balance = get_user_balance_safe(user.id)
    referral_stats = get_referral_stats(user.id)
    
    keyboard = [
        [InlineKeyboardButton("🎰 Сделать ставку", callback_data="menu_bet")],
        [InlineKeyboardButton("⚔️ PvP с другом", callback_data="menu_pvp")],
        [InlineKeyboardButton("📚 Моя коллекция", callback_data="menu_collection")],
        [InlineKeyboardButton("🏪 Сезонный магазин", callback_data="menu_shop")],
        [InlineKeyboardButton("💰 Мой баланс", callback_data="menu_balance")],
        [InlineKeyboardButton("📅 Ежедневная награда", callback_data="menu_daily")],
        [InlineKeyboardButton("🏆 Таблица лидеров", callback_data="menu_leaderboard")],
        [InlineKeyboardButton("📊 Детальная статистика", callback_data="menu_detailed_stats")],
        [InlineKeyboardButton("🎯 Мои достижения", callback_data="menu_achievements")],
        [InlineKeyboardButton("👥 Реферальная система", callback_data="menu_referral")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    text = f"""{format_seasonal_message("Главное меню 🎮")}

{SEASON_NAME} {SEASON_EMOJI}
Твой баланс: {balance} монет 💰
Рефералов: {referral_stats['referrals_count']} 👥

Выбери действие:"""
    
    await safe_edit_message(query, text, reply_markup)

# === ЗАПУСК БОТА ===
def main():
    """Основная функция запуска бота"""
    try:
        init_db()
        
        application = Application.builder().token(BOT_TOKEN).build()
        
        application.add_handler(CommandHandler("start", start))
        
        # Обработчик проверки подписки
        application.add_handler(CallbackQueryHandler(check_subscription_handler, pattern="^check_subscription$"))
        
        # Обработчики меню
        application.add_handler(CallbackQueryHandler(menu_handler, pattern="^menu_(bet|balance|daily|leaderboard|stats|pvp|collection|shop|detailed_stats|season_leaderboard|achievements|referral)$"))
        application.add_handler(CallbackQueryHandler(menu_back_handler, pattern="^menu_back$"))
        
        # Обработчики ставок
        application.add_handler(CallbackQueryHandler(bet_selection_handler, pattern="^bet_"))
        application.add_handler(CallbackQueryHandler(choose_fighter_handler, pattern="^(choose_1|choose_2)$"))
        application.add_handler(CallbackQueryHandler(cancel_bet_handler, pattern="^cancel_bet$"))
        
        # Обработчики магазина
        application.add_handler(CallbackQueryHandler(buy_item_handler, pattern="^buy_"))
        
        # Обработчики PvP
        application.add_handler(CallbackQueryHandler(pvp_create_handler, pattern="^pvp_create$"))
        application.add_handler(CallbackQueryHandler(pvp_accept_handler, pattern="^pvp_accept_"))
        application.add_handler(CallbackQueryHandler(pvp_decline_handler, pattern="^pvp_decline_"))
        application.add_handler(CallbackQueryHandler(pvp_cancel_handler, pattern="^pvp_cancel$"))
        application.add_handler(CallbackQueryHandler(pvp_select_character_handler, pattern="^pvp_select_"))
        application.add_handler(CallbackQueryHandler(pvp_confirm_team_handler, pattern="^pvp_confirm_"))
        application.add_handler(CallbackQueryHandler(pvp_cancel_battle_handler, pattern="^pvp_cancel_battle_"))
        
        print("🎰 Бот ставок успешно запущен!")
        print(f"🐉 Текущий сезон: {SEASON_NAME} {SEASON_EMOJI}")
        print("🔐 Обязательная подписка на каналы активирована")
        print("📚 Система коллекционирования активирована")
        print("🏪 Сезонный магазин настроен") 
        print("📊 Детальная статистика готова")
        print("👥 Реферальная система запущена")
        print("🎯 Система достижений активна")
        print("🤖 Бот готов к работе!")
        print("\nДля остановки нажмите Ctrl+C")
        
        application.run_polling(
            poll_interval=3,
            timeout=30,
            drop_pending_updates=True
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка при запуске бота: {e}")
        sys.exit(1)

if __name__ == '__main__':
    health_thread = threading.Thread(target=start_health_check_server, daemon=True)
    health_thread.start()
    
    main()
