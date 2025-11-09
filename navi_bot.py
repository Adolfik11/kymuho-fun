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
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# === КОНФИГУРАЦИЯ ===
BOT_TOKEN = os.environ.get('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required!")

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Глобальные словари для хранения активных PvP вызовов и битв
active_pvp_challenges = {}
active_pvp_battles = {}

# Блокировки для thread-safe операций с балансом
balance_locks = {}
lock = threading.Lock()

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
    """Обновление счета пользователя - УПРОЩЕННАЯ ВЕРСИЯ"""
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
        
        # ПРОВЕРЯЕМ СУЩЕСТВОВАНИЕ ПОЛЬЗОВАТЕЛЕЙ
        c.execute('SELECT 1 FROM users WHERE user_id = ?', (winner_id,))
        winner_exists = c.fetchone()
        
        c.execute('SELECT 1 FROM users WHERE user_id = ?', (loser_id,))
        loser_exists = c.fetchone()
        
        # СОЗДАЕМ ПОЛЬЗОВАТЕЛЕЙ, ЕСЛИ ИХ НЕТ
        if not winner_exists:
            c.execute('INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 100)', (winner_id,))
        if not loser_exists:
            c.execute('INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 100)', (loser_id,))
        
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
    
    text = "*❌ Ставка отменена*\n\nВсе данные о текущей ставке очищены.\n\n*Используй* /start *для возврата в меню*"
    
    await safe_edit_message(query, text)

# === PvP СИСТЕМА (ВРЕМЕННО УБИРАЕМ ДЛЯ СТАБИЛЬНОСТИ) ===
async def pvp_command_from_menu(query, context):
    """Меню PvP - УПРОЩЕННАЯ ВЕРСИЯ"""
    await safe_edit_message(query,
        "*⚔️ PvP СИСТЕМА* ⚔️\n\n"
        "PvP система временно недоступна для стабилизации работы бота.\n"
        "Мы работаем над улучшением и скоро вернем эту функцию! 🛠️\n\n"
        "*Сейчас доступно:*\n"
        "• 🎰 Ставки на битвы персонажей\n"
        "• 💰 Ежедневные награды\n"
        "• 🏆 Таблица лидеров\n\n"
        "Используй /start для возврата в меню"
    )

# === ЗАПУСК БОТА ===
def main():
    """Основная функция запуска бота"""
    try:
        # Инициализация базы данных
        init_db()
        
        # Создание приложения
        application = Application.builder().token(BOT_TOKEN).build()
        
        # ТОЛЬКО ОСНОВНЫЕ ОБРАБОТЧИКИ
        application.add_handler(CommandHandler("start", start))
        
        # Обработчики меню
        application.add_handler(CallbackQueryHandler(menu_handler, pattern="^menu_(bet|balance|daily|leaderboard|stats|pvp)$"))
        application.add_handler(CallbackQueryHandler(menu_back_handler, pattern="^menu_back$"))
        
        # Обработчики ставок
        application.add_handler(CallbackQueryHandler(bet_selection_handler, pattern="^bet_"))
        application.add_handler(CallbackQueryHandler(choose_fighter_handler, pattern="^(choose_1|choose_2)$"))
        application.add_handler(CallbackQueryHandler(cancel_bet_handler, pattern="^cancel_bet$"))
        
        print("Бот ставок запущен! 🎰")
        print("Для остановки нажмите Ctrl+C")
        
        application.run_polling(
            poll_interval=3,
            timeout=30,
            drop_pending_updates=True
        )
        
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()