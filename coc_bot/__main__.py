import asyncio
import logging
import os
import sys

from .config import load_config
from .database import Database
from .bot import UsherBot


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


async def main() -> None:
    config = load_config()
    setup_logging(config.log_level)

    # Ensure the data directory exists
    data_dir = os.path.dirname(config.sqlite_path)
    if data_dir:
        os.makedirs(data_dir, exist_ok=True)

    db = Database(config.sqlite_path)
    await db.init()

    bot = UsherBot(config=config, db=db)
    try:
        await bot.start(config.discord_token)
    except KeyboardInterrupt:
        pass
    finally:
        await bot.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
