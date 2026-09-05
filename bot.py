import asyncio
import logging
import os
from typing import Optional

from aiohttp import web
from pyrogram import Client, filters
from pyrogram.errors import RPCError
from pyrogram.types import CallbackQuery, ChatJoinRequest, InlineKeyboardButton, InlineKeyboardMarkup, Message


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("auto-join-acceptor")


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


API_ID = int(required_env("TELEGRAM_API_ID"))
API_HASH = required_env("TELEGRAM_API_HASH")
BOT_TOKEN = required_env("TELEGRAM_BOT_TOKEN")
ADMIN_ID = int(required_env("TELEGRAM_ADMIN_ID"))
CHANNEL_URL = os.getenv("CHANNEL_URL", "").strip()
PORT = int(os.getenv("PORT", "8080"))

app = Client(
    "auto_join_acceptor",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)

bot_username = ""


def welcome_buttons() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "+ ADD ME TO YOUR GROUP",
                    url=f"https://t.me/{bot_username}?startgroup=true",
                )
            ],
            [
                InlineKeyboardButton(
                    "+ ADD ME TO YOUR CHANNEL",
                    url=f"https://t.me/{bot_username}?startchannel=true",
                )
            ],
        ]
    )


def accepted_buttons(chat_username: Optional[str]) -> InlineKeyboardMarkup:
    channel_url = CHANNEL_URL
    if not channel_url and chat_username:
        channel_url = f"https://t.me/{chat_username}"

    visit_button = (
        InlineKeyboardButton("⏱️ VISIT CHANNEL", url=channel_url)
        if channel_url
        else InlineKeyboardButton("⏱️ VISIT CHANNEL", callback_data="visit_channel")
    )
    return InlineKeyboardMarkup(
        [
            [visit_button],
            [
                InlineKeyboardButton(
                    "🙋 CHECK I'M ALIVE OR NOT",
                    callback_data="alive",
                )
            ],
        ]
    )


def first_name(user) -> str:
    return (getattr(user, "first_name", None) or "Friend").strip()


@app.on_message(filters.command("start"))
async def start_handler(_: Client, message: Message) -> None:
    logger.info("Received /start from user %s", getattr(message.from_user, "id", "unknown"))
    text = (
        f"HELLO, {first_name(message.from_user)}!\n\n"
        "🤖 WELCOME TO AUTO REQUEST ACCEPT BOT!\n\n"
        "THIS BOT AUTOMATICALLY ACCEPTS ALL JOIN REQUEST FROM YOUR CHANNEL OR GROUP.\n\n"
        "JUST ADD THIS BOT IN YOUR GROUP OR CHANNEL\n"
        "AND MAKE IT ADMIN WITH FULL RIGHTS."
    )
    try:
        await message.reply_text(text, reply_markup=welcome_buttons())
    except RPCError:
        logger.exception("Could not reply to /start")


@app.on_message(filters.command(["help", "what"]))
async def help_handler(_: Client, message: Message) -> None:
    text = (
        "WHAT CAN THIS BOT DO?\n\n"
        "This Bot can Approve Join Request Automatically.\n\n"
        "Just add bot as Administrator in your channels/groups and it's done ✅"
    )
    await message.reply_text(text)


@app.on_message(filters.command("status") & filters.user(ADMIN_ID))
async def status_handler(_: Client, message: Message) -> None:
    await message.reply_text(
        "✅ AUTO REQUEST ACCEPTOR IS ONLINE.\n\n"
        "JOIN REQUESTS ARE BEING APPROVED AUTOMATICALLY."
    )


@app.on_callback_query()
async def callback_handler(_: Client, callback: CallbackQuery) -> None:
    if callback.data == b"alive":
        await callback.answer("✅ I'm alive and accepting requests.", show_alert=True)
    elif callback.data == b"visit_channel":
        await callback.answer(
            "Set CHANNEL_URL to enable the channel link button.",
            show_alert=True,
        )


@app.on_chat_join_request()
async def join_request_handler(_: Client, request: ChatJoinRequest) -> None:
    chat_title = request.chat.title or "YOUR CHANNEL OR GROUP"
    user_id = request.from_user.id

    try:
        await app.approve_chat_join_request(request.chat.id, user_id)
        logger.info("Approved join request from %s in %s", user_id, request.chat.id)
    except RPCError:
        logger.exception("Could not approve join request from %s", user_id)
        return

    text = (
        f"WELCOME, {first_name(request.from_user)}!\n\n"
        f"YOUR RESPECTED REQUEST OF JOINING {chat_title.upper()} "
        "HAS BEEN ALREADY ACCEPTED.\n\n"
        "✅ TAP BUTTON BELOW TO CHECK I'M ALIVE OR NOT."
    )
    try:
        await app.send_message(
            user_id,
            text,
            reply_markup=accepted_buttons(getattr(request.chat, "username", None)),
        )
    except RPCError:
        logger.info("Could not send welcome message to %s", user_id)


async def health(_: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "bot": "running"})


async def start_health_server() -> web.AppRunner:
    server = web.Application()
    server.router.add_get("/", health)
    server.router.add_get("/health", health)
    runner = web.AppRunner(server)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    logger.info("Health server listening on port %s", PORT)
    return runner


async def main() -> None:
    global bot_username

    await app.start()
    bot = await app.get_me()
    bot_username = bot.username or ""
    if not bot_username:
        raise RuntimeError("The bot account must have a username.")

    runner = await start_health_server()
    logger.info("@%s is ready.", bot_username)

    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
        await app.stop()


if __name__ == "__main__":
    asyncio.run(main())