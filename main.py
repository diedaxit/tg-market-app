import asyncio
import os
import uvicorn
from server import app
from bot import bot, dp

async def run_server():
    port = int(os.environ.get("PORT", 8000))
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await asyncio.gather(
        run_server(),
        dp.start_polling(bot, drop_pending_updates=True)
    )

if __name__ == "__main__":
    asyncio.run(main())
