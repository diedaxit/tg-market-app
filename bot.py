import os
import sqlite3
import psycopg2
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, PreCheckoutQuery, InlineKeyboardMarkup,
    InlineKeyboardButton, WebAppInfo, BotCommand
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "ВАШ_ТОКЕН_БОТА")
APP_URL = os.getenv("RENDER_EXTERNAL_URL", "https://atminttagsbot.onrender.com")
DATABASE_URL = os.getenv("DATABASE_URL", "")
DB_NAME = "market.db"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

def bot_db_query(sql: str, params: tuple = ()):
    if DATABASE_URL:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute(sql.replace("?", "%s"), params)
        rows = cur.fetchall()
        conn.close()
        return rows
    else:
        conn = sqlite3.connect(DB_NAME)
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        conn.close()
        return rows

async def setup_bot_commands():
    commands = [
        BotCommand(command="start", description="🚀 Запустить MintTags"),
        BotCommand(command="profile", description="👤 Мой профиль и баланс"),
        BotCommand(command="top", description="🏆 Топ-10 богатейших игроков"),
        BotCommand(command="help", description="❓ Помощь и список команд"),
        BotCommand(command="rules", description="📜 Юридические правила и оферта"),
        BotCommand(command="support", description="🛠 Связь с поддержкой @MintTagsSupport"),
    ]
    try:
        await bot.set_my_commands(commands)
    except Exception:
        pass

def get_webapp_kb(ref_param: str = ""):
    url = f"{APP_URL}?startapp={ref_param}" if ref_param else APP_URL
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👑 ИГРАТЬ В MINTTAGS", web_app=WebAppInfo(url=url))],
        [
            InlineKeyboardButton(text="📢 Новости", url="https://t.me/MintTags_News"),
            InlineKeyboardButton(text="🛠 Поддержка", url="https://t.me/MintTagsSupport")
        ]
    ])

@dp.message(CommandStart())
async def cmd_start(message: Message):
    await setup_bot_commands()
    parts = (message.text or "").split(" ")
    ref_param = parts[1] if len(parts) > 1 else ""
    await message.answer(
        "👑 <b>MintTags: Media Empire</b>\n\n"
        "Добро пожаловать в главный симулятор охоты за элитными <b>@username</b> и анонимными номерами <b>+888</b>!\n\n"
        "🔹 Крути слоты с каскадными иксами и собирай редкие серии\n"
        "🔹 Прокачивай номера в <b>Апгрейдере (до ×10)</b> и летай до Луны в <b>Ракетке (до ×1200)</b>\n"
        "🔹 Сливай редкие лоты приезжающему <b>Тайному Скупщику (+80%)</b>\n"
        "🔹 Торгуй с игроками на живом Аукционе!\n\n"
        "👇 Жми кнопку ниже, чтобы забрать <b>Подарок дня</b>:",
        reply_markup=get_webapp_kb(ref_param),
        parse_mode="HTML"
    )

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "❓ <b>Справочник команд @MintTagsBot:</b>\n\n"
        "• /start — Открыть меню запуска игры\n"
        "• /profile — Посмотреть свой баланс, уровень и статистику Сейфа\n"
        "• /top — Посмотреть Топ-10 магнатов сервера\n"
        "• /rules — Пользовательское соглашение и правила симулятора\n"
        "• /support — Написать в официальную поддержку\n\n"
        "📢 Официальный канал новостей: @MintTags_News\n"
        "🛠 Техническая поддержка: @MintTagsSupport",
        reply_markup=get_webapp_kb(),
        parse_mode="HTML"
    )

@dp.message(Command("profile"))
async def cmd_profile(message: Message):
    uid = message.from_user.id
    try:
        u_rows = bot_db_query(
            "SELECT member_number, balance, level, total_spins, refs_count, duel_wins FROM users WHERE tg_user_id = ?",
            (uid,)
        )
        c_rows = bot_db_query(
            "SELECT COUNT(*) FROM usernames WHERE owner_id = ? AND is_saved = 1",
            (uid,)
        )
        if not u_rows:
            await message.answer("Вы ещё не создали профиль! Нажмите кнопку ниже, чтобы войти в игру:", reply_markup=get_webapp_kb())
            return
        mem_id, bal, lvl, spins, refs, wins = u_rows[0]
        cnt = c_rows[0][0] if c_rows else 0
        await message.answer(
            f"👤 <b>Профиль магната #{mem_id}</b>\n\n"
            f"💰 Баланс: <b>{int(bal):,} GRAM</b>\n"
            f"⭐️ Уровень: <b>{lvl}</b>\n"
            f"💼 Предметов в Сейфе: <b>{cnt} шт.</b>\n"
            f"🎰 Сделано бросков: <b>{spins}</b>\n"
            f"⚔️ Побед в PvP: <b>{wins or 0}</b>\n"
            f"👥 Приглашено друзей: <b>{refs}</b>",
            reply_markup=get_webapp_kb(),
            parse_mode="HTML"
        )
    except Exception:
        await message.answer("Откройте приложение по кнопке ниже для синхронизации профиля:", reply_markup=get_webapp_kb())

@dp.message(Command("top"))
async def cmd_top(message: Message):
    try:
        rows = bot_db_query("SELECT username, balance, level FROM users ORDER BY balance DESC LIMIT 10")
        lines = ["🏆 <b>ТОП-10 МАГНАТОВ MINTTAGS:</b>\n"]
        for i, r in enumerate(rows):
            medal = "🥇" if i == 0 else ("🥈" if i == 1 else ("🥉" if i == 2 else f"#{i+1}"))
            lines.append(f"{medal} <b>{r[0] or 'Игрок'}</b> (Ур. {r[2]}) — <code>{int(r[1]):,} GRAM</code>")
        await message.answer("\n".join(lines), reply_markup=get_webapp_kb(), parse_mode="HTML")
    except Exception:
        await message.answer("Рейтинг обновляется. Загляните в игру!", reply_markup=get_webapp_kb())

@dp.message(Command("support"))
async def cmd_support(message: Message):
    await message.answer(
        "🛠 <b>Служба поддержки MintTags</b>\n\n"
        "По любым вопросам, предложениям, багам или проверке платежей Telegram Stars пишите напрямую нашему агенту:\n"
        "👉 <b>@MintTagsSupport</b>\n\n"
        "Новости и промокоды публикуются в канале: <b>@MintTags_News</b>",
        parse_mode="HTML"
    )

@dp.message(Command("rules"))
async def cmd_rules(message: Message):
    await message.answer(
        "📜 <b>Краткая правовая сводка (Полный текст внутри игры в разделе Настройки):</b>\n\n"
        "1. <b>Статус сервиса:</b> @MintTagsBot является развлекательной веб-игрой (симулятором). Все внутриигровые наименования (GRAM, виртуальные @username и номера +888) являются исключительно внутриигровыми очками и не являются криптовалютой, ценными бумагами или реальными активами Telegram/Fragment.\n"
        "2. <b>Цифровые покупки:</b> Приобретение внутриигровых усилений за Telegram Stars (XTR) является оплатой цифровой развлекательной услуги, предоставляемой мгновенно в момент зачисления бонуса.\n"
        "3. <b>Поддержка:</b> Все обращения принимаются через @MintTagsSupport.",
        parse_mode="HTML"
    )

@dp.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(F.successful_payment)
async def successful_payment_handler(message: Message):
    await message.answer("⭐️ Оплата подтверждена! Ваши внутриигровые бонусы успешно активированы.")
