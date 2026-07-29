import logging
from datetime import datetime, timedelta
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
import sqlite3

# --- Настройки ---
ADMIN_IDS = {5731537463, 8183675472}          # Разрешённые Telegram ID
DB_NAME = "game.db"

# Состояния для разговора (опрос дней / звёзд)
BAN_DAYS, STARS_AMOUNT = range(2)

# --- База данных ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        stars INTEGER DEFAULT 0,
        banned_until TEXT
    )''')
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT user_id, username, stars, banned_until FROM users")
    rows = c.fetchall()
    conn.close()
    return rows

def search_users(query):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    like = f"%{query}%"
    c.execute("SELECT user_id, username, stars, banned_until FROM users WHERE user_id LIKE ? OR username LIKE ?", (like, like))
    rows = c.fetchall()
    conn.close()
    return rows

def get_user(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT user_id, username, stars, banned_until FROM users WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row

def upsert_user(user_id, username, stars=0):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO users (user_id, username, stars) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username", (user_id, username, stars))
    conn.commit()
    conn.close()

def update_stars(user_id, stars):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET stars=? WHERE user_id=?", (stars, user_id))
    conn.commit()
    conn.close()

def ban_user(user_id, days):
    until = datetime.now() + timedelta(days=days)
    until_str = until.isoformat()
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET banned_until=? WHERE user_id=?", (until_str, user_id))
    conn.commit()
    conn.close()

def unban_user(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE users SET banned_until=NULL WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

# --- Клавиатуры ---
def main_menu_keyboard():
    keyboard = [[InlineKeyboardButton("🔍 Поиск пользователя", callback_data="admin_search")]]
    return InlineKeyboardMarkup(keyboard)

def user_list_keyboard(users, page=0, per_page=5):
    keyboard = []
    start = page * per_page
    end = start + per_page
    for row in users[start:end]:
        uid, uname, stars, ban = row
        display = f"{uname or 'Без ника'} ({uid}) ⭐{stars}"
        if ban:
            try:
                banned_until = datetime.fromisoformat(ban)
                if banned_until > datetime.now():
                    display += " 🚫"
            except:
                pass
        keyboard.append([InlineKeyboardButton(display, callback_data=f"user_{uid}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Назад", callback_data=f"page_{page-1}"))
    if len(users) > end:
        nav.append(InlineKeyboardButton("Вперёд ▶️", callback_data=f"page_{page+1}"))
    if nav:
        keyboard.append(nav)
    keyboard.append([InlineKeyboardButton("🔙 В главное меню", callback_data="admin_back")])
    return InlineKeyboardMarkup(keyboard)

def user_detail_keyboard(user_id):
    keyboard = [
        [InlineKeyboardButton("🚫 Забанить", callback_data=f"ban_{user_id}"),
         InlineKeyboardButton("🔓 Разбанить", callback_data=f"unban_{user_id}")],
        [InlineKeyboardButton("⭐ Выдать звёзды", callback_data=f"stars_{user_id}")],
        [InlineKeyboardButton("🔙 Назад к списку", callback_data="admin_back")],
    ]
    return InlineKeyboardMarkup(keyboard)

# --- Команда /admin ---
async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Доступ запрещён.")
        return
    await update.message.reply_text("🛡️ Админ-панель", reply_markup=main_menu_keyboard())

# --- Обработчики кнопок ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = query.from_user

    if user.id not in ADMIN_IDS:
        await query.edit_message_text("⛔ Нет доступа.")
        return

    # Главное меню
    if data == "admin_search":
        await query.edit_message_text("Введите username или ID пользователя для поиска:")
        context.user_data["expecting_search"] = True
        return

    # Назад к списку
    elif data == "admin_back":
        users = get_all_users()
        await query.edit_message_text("Список пользователей:", reply_markup=user_list_keyboard(users))
        return

    # Пагинация
    elif data.startswith("page_"):
        page = int(data.split("_")[1])
        users = get_all_users()
        await query.edit_message_text("Список пользователей:", reply_markup=user_list_keyboard(users, page=page))
        return

    # Карточка пользователя
    elif data.startswith("user_"):
        uid = int(data.split("_")[1])
        row = get_user(uid)
        if not row:
            await query.edit_message_text("Пользователь не найден.")
            return
        uid, uname, stars, ban = row
        text = f"👤 {uname or 'Без ника'} (ID: {uid})\n⭐ Звёзд: {stars}\n"
        if ban:
            try:
                until = datetime.fromisoformat(ban)
                if until > datetime.now():
                    text += f"🚫 Забанен до {until.strftime('%d.%m.%Y %H:%M')}"
                else:
                    text += "✅ Бан истёк"
            except:
                text += "🚫 Забанен (ошибка даты)"
        else:
            text += "✅ Не забанен"
        await query.edit_message_text(text, reply_markup=user_detail_keyboard(uid))
        return

    # Действия с пользователем
    elif data.startswith("ban_"):
        uid = int(data.split("_")[1])
        context.user_data["ban_target"] = uid
        await query.edit_message_text("⌨️ Введите количество дней бана (число):")
        return BAN_DAYS

    elif data.startswith("unban_"):
        uid = int(data.split("_")[1])
        unban_user(uid)
        row = get_user(uid)
        await query.edit_message_text(f"✅ Пользователь {row[1] or uid} разбанен.")
        return ConversationHandler.END

    elif data.startswith("stars_"):
        uid = int(data.split("_")[1])
        context.user_data["stars_target"] = uid
        await query.edit_message_text("⌨️ Введите количество звёзд для выдачи:")
        return STARS_AMOUNT

# --- Обработка текстового ввода ---
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        return

    text = update.message.text.strip()

    # Поиск пользователя (если ожидали ввод)
    if context.user_data.get("expecting_search"):
        context.user_data.pop("expecting_search")
        users = search_users(text)
        if not users:
            await update.message.reply_text("❌ Ничего не найдено.")
        else:
            await update.message.reply_text("Результаты поиска:", reply_markup=user_list_keyboard(users))
        return

    # Если предыдущего состояния нет, значит возможно вводится число для бана/звёзд
    # Но это обрабатывается через ConversationHandler, так что сюда попадём только в крайнем случае
    await update.message.reply_text("Неизвестная команда. Используйте /admin.")

# --- ConversationHandler для ввода дней / звёзд ---
async def receive_ban_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        return ConversationHandler.END
    try:
        days = int(update.message.text)
    except ValueError:
        await update.message.reply_text("❌ Введите целое число дней.")
        return BAN_DAYS
    uid = context.user_data.get("ban_target")
    if not uid:
        await update.message.reply_text("Ошибка. Начните заново /admin")
        return ConversationHandler.END
    ban_user(uid, days)
    row = get_user(uid)
    await update.message.reply_text(f"✅ Пользователь {row[1] or uid} забанен на {days} дн.")
    return ConversationHandler.END

async def receive_stars_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        return ConversationHandler.END
    try:
        amount = int(update.message.text)
    except ValueError:
        await update.message.reply_text("❌ Введите целое число звёзд.")
        return STARS_AMOUNT
    uid = context.user_data.get("stars_target")
    if not uid:
        await update.message.reply_text("Ошибка. Начните заново /admin")
        return ConversationHandler.END
    row = get_user(uid)
    if row:
        new_stars = row[2] + amount
        update_stars(uid, new_stars)
        await update.message.reply_text(f"✅ Выдано {amount}⭐ пользователю {row[1] or uid}. Теперь у него {new_stars}⭐.")
    else:
        await update.message.reply_text("Пользователь не найден в базе.")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Действие отменено.")
    return ConversationHandler.END

# --- Регистрация пользователя при старте (имитация из игры) ---
async def register_if_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """При любом сообщении регистрируем пользователя в базе, если его ещё нет."""
    user = update.effective_user
    if user:
        upsert_user(user.id, user.username or user.first_name, stars=0)

# --- Запуск ---
def main():
    logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
    init_db()

    application = Application.builder().token("7955684710:AAGcGV3C8Zcb0TQx1P7a5BQSK1BRle-sCss").build()

    # Регистрация нового пользователя (при любом сообщении)
    application.add_handler(MessageHandler(filters.ALL, register_if_new), group=0)

    # Conversation handler для ввода дней / звёзд
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern="^(ban_|stars_)")],
        states={
            BAN_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_ban_days)],
            STARS_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_stars_amount)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True,
    )
    application.add_handler(conv_handler)

    # Остальные обработчики
    application.add_handler(CommandHandler("admin", admin_start))
    application.add_handler(CallbackQueryHandler(button_handler, pattern="^(admin_|page_|user_|unban_|stars_)"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    application.run_polling()

if __name__ == "__main__":
    main()