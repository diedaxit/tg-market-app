import asyncio
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

BOT_TOKEN = "9076307904:AAFQs_dohcZxxAUdfGoR5wZeBK9ytk_pF6A"
WEBAPP_URL = "WEBAPP_URL = "https://atminttagsbot.onrender.com"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def start_handler(message: Message):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚀 Открыть Vault",
                    web_app=WebAppInfo(url=WEBAPP_URL)
                )
            ]
        ]
    )
    await message.answer(
        f"Привет, {message.from_user.first_name}!\n\n"
        "Заходи в приложение, получай свой постоянный номер входа (Member #) "
        "и выбивай редкие @юзернеймы!",
        reply_markup=keyboard
    )

async def main():
    print("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
