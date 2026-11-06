import os
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, PreCheckoutQuery, InlineKeyboardMarkup,
    InlineKeyboardButton, WebAppInfo
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "9076307904:AAFQs_dohcZxxAUdfGoR5wZeBK9ytk_pF6A")
APP_URL = os.getenv("RENDER_EXTERNAL_URL", "https://atminttagsbot.onrender.com")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def cmd_start(message: Message):
    parts = message.text.split(" ")
    ref_param = parts[1] if len(parts) > 1 else ""
    webapp_url = f"{APP_URL}?startapp={ref_param}" if ref_param else APP_URL

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👑 ИГРАТЬ В MINTTAGS", web_app=WebAppInfo(url=webapp_url))],
        [InlineKeyboardButton(text="📢 НОВОСТИ @MintTags_News", url="https://t.me/MintTags_News")]
    ])
    await message.answer(
        "👑 <b>MintTags: Media Empire</b>\n\n"
        "Выбивай эксклюзивные <b>@username</b> и анонимные номера <b>+888 anonim</b>, "
        "умножай доход каналов до <b>×1000</b> и зарабатывай миллиарды GRAM!",
        reply_markup=kb,
        parse_mode="HTML"
    )

@dp.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(F.successful_payment)
async def successful_payment_handler(message: Message):
    await message.answer("⭐️ Оплата подтверждена! Бонусы зачислены на ваш аккаунт.")
