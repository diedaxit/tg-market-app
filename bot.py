import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

# Токен твоего бота
BOT_TOKEN = os.getenv("BOT_TOKEN", "9076307904:AAFQs_dohcZxxAUdfGoR5wZeBK9ytk_pF6A")

# Адрес развернутого приложения на Render
WEBAPP_URL = "https://atminttagsbot.onrender.com"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Главное меню кнопок под /start
def get_main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🚀 Запустить MintTags", web_app=WebAppInfo(url=WEBAPP_URL))
        ],
        [
            InlineKeyboardButton(text="📜 Правила & Оферта", callback_data="show_rules"),
            InlineKeyboardButton(text="❓ FAQ", callback_data="show_faq")
        ],
        [
            InlineKeyboardButton(text="💬 Поддержка", url="https://t.me/MintTagsSupport")
        ]
    ])

# Клавиатура возврата в меню
def get_back_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🚀 Запустить приложение", web_app=WebAppInfo(url=WEBAPP_URL))
        ]
    ])

# Текст правил и отказа от ответственности
RULES_TEXT = (
    "📜 <b>Правила игры «MintTags» & Пользовательское соглашение</b>\n\n"
    "<b>1. Игровой характер сервиса.</b>\n"
    "MintTags — исключительно виртуальный симулятор и развлекательная игра. "
    "Все генерируемые юзернеймы, теги, префиксы, монеты (COIN), балансы и номера участников "
    "(Member #ID) являются <b>исключительно внутриигровыми объектами</b>. "
    "Они не имеют реальной материальной ценности, не дают прав на реальные юзернеймы Telegram, "
    "не подлежат выводу, обмену на фиатные деньги, криптовалюту или передаче третьим лицам.\n\n"
    "<b>2. Отсутствие выплат и компенсаций.</b>\n"
    "Администрация сервиса не осуществляет выплаты денежных средств, не выкупает аккаунты, "
    "не передает реальные права на каналы/боты/юзернеймы платформы Telegram.\n\n"
    "<b>3. Игровые покупки и донаты.</b>\n"
    "Любые добровольные транзакции (включая Telegram Stars) совершаются исключительно ради "
    "получения виртуальных игровых преимуществ (ускорение фарма, минт, визуальные статусы). "
    "Услуга считается оказанной в момент зачисления виртуального предмета на игровой баланс. "
    "Возврат средств за полученные цифровые предметы не предусмотрен.\n\n"
    "<b>4. Сбои и работа «Как есть» (As Is).</b>\n"
    "Сервис предоставляется по принципу «как есть». Администрация не несет ответственности "
    "за временные сбои хостинга, рассинхронизацию баз данных или потерю внутриигровых монет.\n\n"
    "<b>5. Честная игра.</b>\n"
    "Запрещено использование скриптов, автокликеров, эксплойтов и мультиаккаунтов для накрутки. "
    "В случае выявления нарушений администрация оставляет за собой право аннулировать прогресс.\n\n"
    "<i>Запуская приложение или отправляя команду /start, вы безоговорочно принимаете данные условия.</i>"
)

# Текст FAQ
FAQ_TEXT = (
    "❓ <b>Часто задаваемые вопросы (FAQ)</b>\n\n"
    "🔹 <b>Что такое MintTags?</b>\n"
    "Это кликер и коллекционная игра, где каждый игрок получает порядковый номер (Member #X) "
    "и минтит виртуальные теги разной степени редкости.\n\n"
    "🔹 <b>Как получать больше COIN?</b>\n"
    "Каждый выбитый тег приносит пассивный доход в секунду. Чем выше редкость (Rare, Epic, Legendary, Mythic), "
    "тем больше монет капает в секунду.\n\n"
    "🔹 <b>Это настоящие юзернеймы Telegram?</b>\n"
    "Нет, это внутриигровые симуляторы редкости в рамках игровой механики.\n\n"
    "🔹 <b>Нашел баг или не начислились монеты?</b>\n"
    "Напиши в официальную поддержку: @MintTagsSupport"
)

# 1. Команда /start
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user_name = message.from_user.first_name or "Участник"
    text = (
        f"👋 Привет, <b>{user_name}</b>!\n\n"
        "Добро пожаловать в <b>MintTags</b> — симулятор и кликер редких юзернеймов!\n\n"
        "🏷️ <b>Твои возможности:</b>\n"
        "• Закрепи за собой статус раннего игрока с номером <code>Member #ID</code>\n"
        "• Минти эксклюзивные теги (Common ➔ Mythic)\n"
        "• Собирай пассивный доход монетами каждую секунду\n\n"
        "🎁 На твой баланс уже начислен стартовый бонус!\n\n"
        "Нажимай кнопку ниже, чтобы запустить приложение 👇"
    )
    await message.answer(text, reply_markup=get_main_keyboard(), parse_mode="HTML")

# 2. Команды /rules, /terms, /agreement
@dp.message(Command(commands=["rules", "terms", "agreement"]))
async def cmd_rules(message: types.Message):
    await message.answer(RULES_TEXT, reply_markup=get_back_keyboard(), parse_mode="HTML")

# 3. Команды /faq, /info
@dp.message(Command(commands=["faq", "info"]))
async def cmd_faq(message: types.Message):
    await message.answer(FAQ_TEXT, reply_markup=get_back_keyboard(), parse_mode="HTML")

# 4. Команда /help или /helper
@dp.message(Command(commands=["help", "helper", "support"]))
async def cmd_help(message: types.Message):
    help_text = (
        "🛠️ <b>Служба заботы MintHelper</b>\n\n"
        "Если у тебя возникли вопросы по работе бота, баги или предложения по игре:\n\n"
        "• Наш оператор поддержки: @MintTagsSupport\n"
        "• Новостной канал: @MintTagsNews\n\n"
        "При обращении сразу отправляй свой Telegram ID и скриншот проблемы."
    )
    await message.answer(help_text, reply_markup=get_back_keyboard(), parse_mode="HTML")

# Обработка нажатий на inline-кнопки под сообщением
@dp.callback_query(F.data == "show_rules")
async def cb_rules(call: types.CallbackQuery):
    await call.message.edit_text(RULES_TEXT, reply_markup=get_main_keyboard(), parse_mode="HTML")
    await call.answer()

@dp.callback_query(F.data == "show_faq")
async def cb_faq(call: types.CallbackQuery):
    await call.message.edit_text(FAQ_TEXT, reply_markup=get_main_keyboard(), parse_mode="HTML")
    await call.answer()
