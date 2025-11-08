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
                  games_played INTEGER DEFAULT 0, balance INTEGER DEFAULT 100)''')
    conn.commit()
    conn.close()

def update_user_score(user_id, username, points):
    conn = sqlite3.connect('navi_bot.db')
    c = conn.cursor()
    today = datetime.datetime.now().isoformat()
    
    c.execute('''INSERT OR REPLACE INTO users 
                 (user_id, username, score, last_activity, games_played, balance)
                 VALUES (?, ?, COALESCE((SELECT score FROM users WHERE user_id = ?), 0) + ?, ?, 
                 COALESCE((SELECT games_played FROM users WHERE user_id = ?), 0) + 1,
                 COALESCE((SELECT balance FROM users WHERE user_id = ?), 100))''',
              (user_id, username, user_id, points, today, user_id, user_id))
    conn.commit()
    conn.close()

def update_user_balance(user_id, amount):
    conn = sqlite3.connect('navi_bot.db')
    c = conn.cursor()
    c.execute('''UPDATE users SET balance = balance + ? WHERE user_id = ?''', 
              (amount, user_id))
    conn.commit()
    conn.close()

def get_user_balance(user_id):
    conn = sqlite3.connect('navi_bot.db')
    c = conn.cursor()
    c.execute('''SELECT balance FROM users WHERE user_id = ?''', (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 100

# Персонажи с их силой (скрыто от игроков)
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
    
    # Genshin Impact
    "Райдэн": {"universe": "Genshin Impact", "power": 90},
    "Чжун Ли": {"universe": "Genshin Impact", "power": 89},
    "Дилюк": {"universe": "Genshin Impact", "power": 82},
    "Гань Юй": {"universe": "Genshin Impact", "power": 85},
    "Нахида": {"universe": "Genshin Impact", "power": 87},
    "Венти": {"universe": "Genshin Impact", "power": 83},
    "Эола": {"universe": "Genshin Impact", "power": 81},
    "Кэ Цин": {"universe": "Genshin Impact", "power": 79},
    
    # Honkai Impact 3rd
    "Киана": {"universe": "Honkai Impact 3rd", "power": 95},
    "Мэй": {"universe": "Honkai Impact 3rd", "power": 88},
    "Броня": {"universe": "Honkai Impact 3rd", "power": 86},
    "Тереза": {"universe": "Honkai Impact 3rd", "power": 84},
    "Фу Хуа": {"universe": "Honkai Impact 3rd", "power": 89},
    "Сирин": {"universe": "Honkai Impact 3rd", "power": 92},
"Дуриан": {"universe": "Honkai Impact 3rd", "power": 83},
    "Рита": {"universe": "Honkai Impact 3rd", "power": 85},
    
    # Zenless Zone Zero
    "Билли": {"universe": "Zenless Zone Zero", "power": 78},
    "Никки": {"universe": "Zenless Zone Zero", "power": 76},
    "Соломон": {"universe": "Zenless Zone Zero", "power": 82},
    "Алекс": {"universe": "Zenless Zone Zero", "power": 79},
    "Бен": {"universe": "Zenless Zone Zero", "power": 77},
    "Короленок": {"universe": "Zenless Zone Zero", "power": 75}
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
    
    await update.message.reply_text(
        f"""*Привет, {user.first_name}!* 👋

🎰 *Добро пожаловать в систему ставок на битвы персонажей!*

*Твой баланс:* {balance} монет 💰

*Команды:*
/bet - Сделать ставку на битву ⚔️
/balance - Проверить баланс 💰
/daily - Ежедневная награда 🎁
/leaderboard - Таблица лидеров 🏆

*Выбирай персонажей, делай ставки и выигрывай!* 🎯
        """,
        parse_mode='Markdown'
    )

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверить баланс"""
    user = update.effective_user
    balance = get_user_balance(user.id)
    
    await update.message.reply_text(
        f"*💰 ТВОЙ БАЛАНС:* {balance} монет\n\n"
        f"*Используй* /bet *чтобы сделать ставку!*",
        parse_mode='Markdown'
    )

async def bet_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начать процесс ставки"""
    user = update.effective_user
    balance = get_user_balance(user.id)
    
    if balance < 10:
        await update.message.reply_text(
            f"*❌ Недостаточно монет!*\n\n"
            f"Твой баланс: {balance} монет\n"
            f"Минимальная ставка: 10 монет\n\n"
            f"*Жди ежедневную награду* /daily *или выигрывай в других ставках!*",
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
        [InlineKeyboardButton(f"💰 Ставка 100 монет (x3.0)", callback_data="bet_100")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"*🎰 СТАВКА НА БИТВУ* 🎰\n\n"
        f"{UNIVERSE_EMOJIS[char1['universe']]} *{char1_name}* ({char1['universe']})\n"
        f"⚡ ПРОТИВ ⚡\n"
        f"{UNIVERSE_EMOJIS[char2['universe']]} *{char2_name}* ({char2['universe']})\n\n"
        f"*Твой баланс:* {balance} монет\n"
        f"*Выбери сумму ставки:*",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def bet_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора ставки"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    bet_amount = int(query.data.split('_')[1])
balance = get_user_balance(user.id)
    
    # Проверяем баланс
    if balance < bet_amount:
        await query.edit_message_text(
            f"*❌ Недостаточно монет!*\n\n"
            f"Ты хотел поставить: {bet_amount} монет\n"
            f"Твой баланс: {balance} монет\n\n"
            f"*Используй* /bet *для новой ставки*",
            parse_mode='Markdown'
        )
        return
    
    battle_data = context.user_data.get('current_battle')
    if not battle_data:
        await query.edit_message_text("*Ошибка! Начни новую ставку* /bet", parse_mode='Markdown')
        return
    
    # Коэффициенты в зависимости от суммы ставки
    multipliers = {10: 1.5, 25: 2.0, 50: 2.5, 100: 3.0}
    multiplier = multipliers[bet_amount]
    
    # Сохраняем данные о ставке
    context.user_data['current_bet'] = {
        'amount': bet_amount,
        'multiplier': multiplier
    }
    
    keyboard = [
        [InlineKeyboardButton(f"🎯 Ставка на {battle_data['char1']}", callback_data="choose_1")],
        [InlineKeyboardButton(f"🎯 Ставка на {battle_data['char2']}", callback_data="choose_2")],
        [InlineKeyboardButton(f"❌ Отмена", callback_data="cancel_bet")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"*🎯 ВЫБОР ПОБЕДИТЕЛЯ* 🎯\n\n"
        f"*Ставка:* {bet_amount} монет\n"
        f"*Множитель:* x{multiplier}\n"
        f"*Выигрыш:* {int(bet_amount * multiplier)} монет\n\n"
        f"*На кого ставишь?*",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def choose_fighter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора бойца"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel_bet":
        await query.edit_message_text("*❌ Ставка отменена*\n\nИспользуй /bet для новой ставки", parse_mode='Markdown')
        return
    
    user = query.from_user
    chosen_fighter = int(query.data.split('_')[1])  # 1 или 2
    
    battle_data = context.user_data.get('current_battle')
    bet_data = context.user_data.get('current_bet')
    
    if not battle_data or not bet_data:
        await query.edit_message_text("*Ошибка! Начни новую ставку* /bet", parse_mode='Markdown')
        return
    
    # Рассчитываем шансы на победу based на силе персонажей
    total_power = battle_data['char1_power'] + battle_data['char2_power']
    char1_chance = battle_data['char1_power'] / total_power
    char2_chance = battle_data['char2_power'] / total_power
    
    # Определяем победителя based на шансах
    winner = 1 if random.random() < char1_chance else 2
    
    # Определяем выигрыш
    if chosen_fighter == winner:
        win_amount = int(bet_data['amount'] * bet_data['multiplier'])
        update_user_balance(user.id, win_amount)
        result_text = f"🎉 *ПОБЕДА!* +{win_amount} монет!"
        result_emoji = "✅"
    else:
        update_user_balance(user.id, -bet_data['amount'])
        result_text = f"💥 *ПРОИГРЫШ!* -{bet_data['amount']} монет"
        result_emoji = "❌"
    
    # Обновляем общий счет
    update_user_score(user.id, user.username, 1)
    
    # Показываем результат
    winner_name = battle_data['char1'] if winner == 1 else battle_data['char2']
    loser_name = battle_data['char2'] if winner == 1 else battle_data['char1']
    
    await query.edit_message_text(
        f"*⚔️ РЕЗУЛЬТАТ БИТВЫ* ⚔️\n\n"
        f"{UNIVERSE_EMOJIS[battle_data['char1_universe']]} *{battle_data['char1']}* 🆚 "
        f"{UNIVERSE_EMOJIS[battle_data['char2_universe']]} *{battle_data['char2']}*\n\n"
        f"🏆 *ПОБЕДИТЕЛЬ:* {winner_name}\n"
        f"💀 *ПРОИГРАВШИЙ:* {loser_name}\n\n"
        f"*ТВОЯ СТАВКА:* на {battle_data['char1'] if chosen_fighter == 1 else battle_data['char2']}\n"
f"*СТАВКА:* {bet_data['amount']} монет\n"
        f"*МНОЖИТЕЛЬ:* x{bet_data['multiplier']}\n\n"
        f"{result_emoji} {result_text}\n\n"
        f"*Новый баланс:* {get_user_balance(user.id)} монет\n\n"
        f"*Следующая ставка:* /bet",
        parse_mode='Markdown'
    )

async def daily_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ежедневная награда"""
    user = update.effective_user
    daily_reward = random.randint(50, 150)
    
    update_user_balance(user.id, daily_reward)
    update_user_score(user.id, user.username, 3)
    
    await update.message.reply_text(
        f"*📅 ЕЖЕДНЕВНАЯ НАГРАДА* 📅\n\n"
        f"*Игрок:* {user.first_name}\n"
        f"*Награда:* +{daily_reward} монет 💰\n\n"
        f"*Новый баланс:* {get_user_balance(user.id)} монет\n\n"
        f"*Используй* /bet *для ставок!* 🎰",
        parse_mode='Markdown'
    )

async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Таблица лидеров по балансу"""
    conn = sqlite3.connect('navi_bot.db')
    c = conn.cursor()
    c.execute('''SELECT username, balance, score 
                 FROM users 
                 ORDER BY balance DESC 
                 LIMIT 10''')
    top_users = c.fetchall()
    conn.close()
    
    if not top_users:
        await update.message.reply_text("*Таблица лидеров пуста!* Будьте первым! 🏆", parse_mode='Markdown')
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
        leaderboard_text += f"   Баланс: {balance} монет | Очки: {score}\n\n"
    
    # Получаем текущую позицию пользователя
    conn = sqlite3.connect('navi_bot.db')
    c = conn.cursor()
    c.execute('''SELECT COUNT(*) + 1 FROM users WHERE balance > 
                 (SELECT balance FROM users WHERE user_id = ?)''', 
              (update.effective_user.id,))
    user_rank = c.fetchone()[0]
    user_balance = get_user_balance(update.effective_user.id)
    conn.close()
    
    leaderboard_text += f"*Твоя позиция:* #{user_rank} (Баланс: {user_balance} монет)"
    
    await update.message.reply_text(leaderboard_text, parse_mode='Markdown')

# === ЗАПУСК БОТА ===
def main():
    # Инициализация базы данных
    init_db()
    
    # Создание приложения
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("bet", bet_command))
    application.add_handler(CommandHandler("balance", balance_command))
    application.add_handler(CommandHandler("daily", daily_command))
    application.add_handler(CommandHandler("leaderboard", leaderboard_command))
    application.add_handler(CallbackQueryHandler(bet_button, pattern="^bet_"))
    application.add_handler(CallbackQueryHandler(choose_fighter, pattern="^choose_"))
    application.add_handler(CallbackQueryHandler(choose_fighter, pattern="^cancel_bet"))
    
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

if name == 'main':
    main()
