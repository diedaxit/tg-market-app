import asyncio
import uvicorn
from server import app
from bot import bot, dp

async def run_server():
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

async def main():
    await asyncio.gather(
        run_server(),
        dp.start_polling(bot)
    )

if __name__ == "__main__":
    asyncio.run(main())