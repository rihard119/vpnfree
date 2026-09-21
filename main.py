import asyncio
import logging
import os

from dotenv import load_dotenv
from telethon import TelegramClient

import storage
from control_bot import register_handlers

load_dotenv()
logging.basicConfig(level=logging.INFO)

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
BOT_TOKEN = os.environ["TG_BOT_TOKEN"]
ADMIN_ID = int(os.environ["TG_ADMIN_ID"])
USER_SESSION = os.environ.get("TG_USER_SESSION", "user_session")

# Optional SOCKS5 proxy for the userbot connection (not needed for the
# control bot - that one talks to Telegram's Bot API over plain HTTPS
# via long polling, which usually isn't blocked). Leave PROXY_HOST
# unset to disable.
PROXY = None
_proxy_host = os.environ.get("PROXY_HOST")
if _proxy_host:
    import socks  # provided by PySocks, a dependency of python-socks/telethon[socks]

    PROXY = (
        socks.SOCKS5,
        _proxy_host,
        int(os.environ.get("PROXY_PORT", 1080)),
        True,  # rdns
        os.environ.get("PROXY_USERNAME") or None,
        os.environ.get("PROXY_PASSWORD") or None,
    )


async def main() -> None:
    storage.init_db()

    user_client = TelegramClient(USER_SESSION, API_ID, API_HASH, proxy=PROXY)
    bot_client = TelegramClient("control_bot_session", API_ID, API_HASH)

    await user_client.start()  # first run: prompts for phone + login code
    await bot_client.start(bot_token=BOT_TOKEN)

    register_handlers(bot_client, user_client, ADMIN_ID)

    logging.info("Userbot + control bot running.")
    await asyncio.gather(
        user_client.run_until_disconnected(),
        bot_client.run_until_disconnected(),
    )


if __name__ == "__main__":
    asyncio.run(main())
