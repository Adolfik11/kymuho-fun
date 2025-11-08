import logging
import random
import os
import sqlite3
import datetime
import time
import signal
import sys
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# === КОНФИГУРАЦИЯ ===
BOT_TOKEN = os.environ.get('BOT_TOKEN', '8578378221:AAHCZqygYGaDFqEbqSnVaORiHf2QF44RNWU')

# Обработка graceful shutdown
def signal_handler(sig, frame):
    print('Бот завершает работу...')
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# База данных для лидеров и баланса
def init_db():
    conn = sqlite3.connect('navi_bot.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, username TEXT, 
                  score INTEGER DEFAULT 0, last_activity TEXT,
                  games_played INTEGER DEFAULT 0, balance INTEGER DEFAULT 100,
                  pvp_wins INTEGER DEFAULT 0, pvp_losses INTEGER DEFAULT 0)''')
    conn.commit()
    conn.close()

def update_user_score(user_id, username, points):
    conn = sqlite3.connect('navi_bot.db')
    c = conn.cursor()
    today = datetime.datetime.now().isoformat()
    
    c.execute('''INSERT OR REPLACE INTO users 
                 (user_id, username, score, last_activity, games_played, balance, pvp_wins, pvp_losses)
                 VALUES (?, ?, COALESCE((SELECT score FROM users WHERE user_id = ?), 0) + ?, ?, 
                 COALESCE((SELECT games_played FROM users WHERE user_id = ?), 0) + 1,
                 COALESCE((SELECT balance FROM users WHERE user_id = ?), 100),
                 COALESCE((SELECT pvp_wins FROM users WHERE user_id = ?), 0),
                 COALESCE((SELECT pvp_losses FROM users WHERE user_id = ?), 0))''',
              (user_id, username, user_id, points, today, user_id, user_id, user_id, user_id))
    conn.commit()
    conn.close()

def update_user_balance(user_id, amount):
    conn = sqlite3.connect('navi_bot.db')
    c = conn.cursor()
    c.execute('''UPDATE users SET balance = balance + ? WHERE user_id = ?''', 
              (amount, user_id))
    conn.commit()
    conn.close()

def update_pvp_stats(winner_id, loser_id):
    conn = sqlite3.connect('navi_bot.db')
    c = conn.cursor()
    c.execute('''UPDATE users SET pvp_wins = pvp_wins + 1 WHERE user_id = ?''', (winner_id,))
    c.execute('''UPDATE users SET pvp_losses = pvp_losses + 1 WHERE user_id = ?''', (loser_id,))
    conn.commit()
    conn.close()

def get_user_balance(user_id):
    conn = sqlite3.connect('navi_bot.db')
    c = conn.cursor()
    c.execute('''SELECT balance FROM users WHERE user_id = ?''', (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 100

def get_pvp_stats(user_id):
    conn = sqlite3.connect('navi_bot.db')
    c = conn.cursor()
    c.execute('''SELECT pvp_wins, pvp_losses FROM users WHERE user_id = ?''', (user_id,))
    result = c.fetchone()
    conn.close()
    return result if result else (0, 0)

# Расширенный список персонажей
CHARACTERS = {
    # Honkai: Star Rail
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
    
    # Genshin Impact
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
    
    # Honkai Impact 3rd
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
    
    # Zenless Zone Zero
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

# Эмодзи для вселенных
UNIVERSE_EMOJIS = {
    "Honkai: Star Rail": "🎮",
    "Genshin Impact": "🌍",
    "Honkai Impact 3rd": "⚡",
    "Zenless Zone Zero": "🏙️"
}

# === КОМАНДЫ БОТА ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    balance = get_user_balance(user.id)
    
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
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    
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

async def bet_command_from_menu(query, context):
    user = query.from_user
    balance = get_user_balance(user.id)
    
    if balance < 10:
        await query.edit_message_text(
            f"*❌ Недостаточно монет!*\n\n"
            f"Твой баланс: `{balance}` монет\n"
            f"Минимальная ставка: `10` монет\n\n"
            f"*Жди ежедневную награду или выигрывай в других ставках!*",
            parse_mode='Markdown'
        )
        return
    
    # Выбираем двух случайных персонажей
    char1_name, char2_name = random.sample(list(CHARACTERS.keys()), 2)
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
    
    await query.edit_message_text(
        f"*🎰 СТАВКА НА БИТВУ* 🎰\n\n"
        f"{UNIVERSE_EMOJIS[char1['universe']]} *{char1_name}* ({char1['universe']})\n"
        f"⚡ **ПРОТИВ** ⚡\n"
        f"{UNIVERSE_EMOJIS[char2['universe']]} *{char2_name}* ({char2['universe']})\n\n"
        f"*Твой баланс:* `{balance}` монет\n"
        f"*Выбери сумму ставки:*",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def pvp_command_from_menu(query, context):
    await query.edit_message_text(
        "*⚔️ КОМАНДНОЕ PvP* ⚔️\n\n"
        "*Как это работает:*\n"
        "1. Бросаешь вызов другу\n"
        "2. Каждому выдается 5 случайных персонажей\n"
        "3. Выбираешь 3 в свою команду\n"
        "4. Побеждает команда с большей суммой силы\n\n"
        "*Ставка:* 50 монет с каждого\n"
        "*Победитель получает:* 90 монет\n\n"
        "Введи @username друга для вызова:",
        parse_mode='Markdown'
    )
    context.user_data['awaiting_pvp_opponent'] = True

# Остальные функции (bet_button, choose_fighter, daily_command, leaderboard_command) 
# остаются без изменений, но добавляем кнопку "Назад" в каждое меню

async def stats_command(query, context):
    user = query.from_user
    balance = get_user_balance(user.id)
    pvp_wins, pvp_losses = get_pvp_stats(user.id)
    total_pvp = pvp_wins + pvp_losses
    winrate = (pvp_wins / total_pvp * 100) if total_pvp > 0 else 0
    
    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="menu_back")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"*📊 ТВОЯ СТАТИСТИКА* 📊\n\n"
        f"*Баланс:* `{balance}` монет 💰\n"
        f"*PvP побед:* `{pvp_wins}` 🏆\n"
        f"*PvP поражений:* `{pvp_losses}` 💀\n"
        f"*Винрейт:* `{winrate:.1f}%` 📈\n\n"
        f"*Всего PvP битв:* `{total_pvp}` ⚔️",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def menu_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    balance = get_user_balance(user.id)
    
    keyboard = [
        [InlineKeyboardButton("🎰 Сделать ставку", callback_data="menu_bet")],
        [InlineKeyboardButton("⚔️ PvP с другом", callback_data="menu_pvp")],
        [InlineKeyboardButton("💰 Мой баланс", callback_data="menu_balance")],
        [InlineKeyboardButton("📅 Ежедневная награда", callback_data="menu_daily")],
        [InlineKeyboardButton("🏆 Таблица лидеров", callback_data="menu_leaderboard")],
        [InlineKeyboardButton("📊 Моя статистика", callback_data="menu_stats")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"""*Главное меню* 🎮

*Твой баланс:* `{balance}` монет 💰

*Выбери действие:*""",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

# Добавляем обработку PvP вызовов
async def handle_pvp_challenge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('awaiting_pvp_opponent'):
        opponent_username = update.message.text.strip()
        challenger = update.effective_user
        
        # Здесь должна быть логика поиска пользователя по username
        # Пока просто сохраняем вызов
        context.user_data['pvp_challenge'] = {
            'challenger_id': challenger.id,
            'challenger_name': challenger.first_name,
            'opponent_username': opponent_username
        }
        
        await update.message.reply_text(
            f"*Вызов отправлен!* ⚔️\n\n"
            f"Ждем ответа от {opponent_username}\n"
            f"Ставка: 50 монет с каждого\n"
            f"Победитель получает: 90 монет",
            parse_mode='Markdown'
        )
        context.user_data['awaiting_pvp_opponent'] = False

# Остальные существующие функции (bet_button, choose_fighter, daily_command, leaderboard_command) 
# остаются без изменений, но добавляем кнопки "Назад"

# === ЗАПУСК БОТА ===
def main():
    # Инициализация базы данных
    init_db()
    
    # Создание приложения
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("bet", bet_command_from_menu))
    application.add_handler(CommandHandler("balance", balance_command_from_menu))
    application.add_handler(CommandHandler("daily", daily_command_from_menu))
    application.add_handler(CommandHandler("leaderboard", leaderboard_command_from_menu))
    application.add_handler(CommandHandler("pvp", pvp_command_from_menu))
    
    # Обработчики кнопок
    application.add_handler(CallbackQueryHandler(menu_handler, pattern="^menu_"))
    application.add_handler(CallbackQueryHandler(menu_back, pattern="^menu_back"))
    application.add_handler(CallbackQueryHandler(bet_button, pattern="^bet_"))
    application.add_handler(CallbackQueryHandler(choose_fighter, pattern="^choose_"))
    application.add_handler(CallbackQueryHandler(choose_fighter, pattern="^cancel_bet"))
    
    # Обработчик текстовых сообщений для PvP
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_pvp_challenge))
    
    print("Бот ставок запущен! 🎰")
    print("Для остановки нажмите Ctrl+C")
    
    # Бесконечный polling с обработкой ошибок
    while True:
        try:
            application.run_polling(
                poll_interval=3,
                timeout=30,
                drop_pending_updates=True
            )
        except Exception as e:
            print(f"Ошибка: {e}. Перезапуск через 10 секунд...")
            time.sleep(10)

if __name__ == '__main__':
    main()
