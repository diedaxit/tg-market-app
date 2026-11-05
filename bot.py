import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

BOT_TOKEN = "9076307904:AAFQs_dohcZxxAUdfGoR5wZeBK9ytk_pF6A"
WEBAPP_URL = "https://atminttagsbot.onrender.com"

# Изображение обложки (твой логотип)
BANNER_URL = "https://raw.githubusercontent.com/diedaxit/tg-market-app/main/minttags_logo.jpg"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Главное меню в точности как на примере
def get_start_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🏷️ Играть", web_app=WebAppInfo(url=WEBAPP_URL))
        ],
        [
            InlineKeyboardButton(text="📜 Правила игры", callback_data="show_rules"),
            InlineKeyboardButton(text="❓ FAQ & Помощь", callback_data="show_faq")
        ],
        [
            InlineKeyboardButton(text="💬 Поддержка", url="https://t.me/MintTagsSupport")
        ]
    ])

def get_back_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🏷️ Играть в MintTags", web_app=WebAppInfo(url=WEBAPP_URL))
        ],
        [
            InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_menu")
        ]
    ])

RULES_TEXT = (
    "📜 <b>Правила игры «MintTags» & Пользовательское соглашение</b>\n\n"
    "<b>1. Это игра.</b> Теги, никнеймы, монеты COIN, баланс и порядковый номер Member #ID — "
    "исключительно виртуальные игровые предметы. Они не имеют реальной материальной стоимости, "
    "не продаются за реальные деньги, не выводятся и не дают прав на реальные юзернеймы Telegram.\n\n"
    "<b>2. Покупки и донаты.</b> За Telegram Stars приобретаются исключительно игровые возможности "
    "(ускорители фарма, минт, слоты). Покупка считается выполненной в момент зачисления предмета в игре. "
    "Если покупка не начислилась — напиши в поддержку, проверим логи. Деньги за выданные покупки не возвращаются.\n\n"
    "<b>3. Сбои.</b> Игра работает по принципу «как есть». Мы не обязаны восстанавливать утерянные из-за сбоев "
    "или действий игрока теги и балансы. Ошибки на стороне сервера компенсируются по усмотрению администрации.\n\n"
    "<b>4. Честная игра.</b> Запрещены автокликеры, скрипты, баги, дюпы и мультиаккаунты. "
    "За нарушение аккаунт блокируется без возврата покупок.\n\n"
    "<i>Запуская игру, вы безоговорочно соглашаетесь с условиями.</i>"
)

FAQ_TEXT = (
    "❓ <b>Часто задаваемые вопросы (FAQ)</b>\n\n"
    "🔹 <b>Как работает минт?</b>\n"
    "Нажимай кнопку минта в приложении, чтобы выбивать случайные теги разной степени редкости.\n\n"
    "🔹 <b>Как получать монеты COIN?</b>\n"
    "Каждый тег в твоей коллекции приносит пассивный доход каждую секунду в режиме 24/7.\n\n"
    "🔹 <b>Это реальные юзернеймы?</b>\n"
    "Нет, это коллекционные цифровые симуляторы внутри игры.\n\n"
    "🔹 <b>Нужна помощь?</b>\n"
    "Обращайся в официальную поддержку: @MintTagsSupport"
)

def get_welcome_text(name: str) -> str:
    return (
        f"Привет, <b>{name}</b>! 👋\n\n"
        "🏷️ <b>MintTags</b> — минти редкие теги и собирай блатные юзернеймы.\n\n"
        "<blockquote>"
        "💎 10 редкостей — от обычного до мифического\n"
        "⚡ Пассивный доход в COIN каждую секунду\n"
        "👑 Уникальный статус и порядковый номер Member #ID\n"
        "🏆 Рейтинг лучших холдеров и призы каждый день"
        "</blockquote>\n\n"
        "Какой тег выпадет тебе? Жми <b>«Играть»</b> 👇\n\n"
        "<i>Играя, ты принимаешь правила и соглашение.</i>"
    )

# Команда /start
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    name = message.from_user.first_name or "Игрок"
    text = get_welcome_text(name)
    await message.answer(text, reply_markup=get_start_keyboard(), parse_mode="HTML")

# Команды /rules, /terms
@dp.message(Command(commands=["rules", "terms"]))
async def cmd_rules(message: types.Message):
    await message.answer(RULES_TEXT, reply_markup=get_back_keyboard(), parse_mode="HTML")

# Команды /faq, /info
@dp.message(Command(commands=["faq", "info"]))
async def cmd_faq(message: types.Message):
    await message.answer(FAQ_TEXT, reply_markup=get_back_keyboard(), parse_mode="HTML")

# Команда /help, /helper, /support
@dp.message(Command(commands=["help", "helper", "support"]))
async def cmd_help(message: types.Message):
    help_text = (
        "🛠️ <b>Служба поддержки MintHelper</b>\n\n"
        "Возник вопрос, баг или предложение?\n"
        "Напиши нам: @MintTagsSupport\n\n"
        "При обращении сразу отправь свой Telegram ID и скриншот."
    )
    await message.answer(help_text, reply_markup=get_back_keyboard(), parse_mode="HTML")

# Колбэки кнопок под сообщением
@dp.callback_query(F.data == "show_rules")
async def cb_rules(call: types.CallbackQuery):
    await call.message.edit_text(RULES_TEXT, reply_markup=get_back_keyboard(), parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data == "show_faq")
async def cb_faq(call: types.CallbackQuery):
    await call.message.edit_text(FAQ_TEXT, reply_markup=get_back_keyboard(), parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data == "back_to_menu")
async def cb_back(call: types.CallbackQuery):
    name = call.from_user.first_name or "Игрок"
    await call.message.edit_text(get_welcome_text(name), reply_markup=get_start_keyboard(), parse_mode="HTML")
    await call.answer()
