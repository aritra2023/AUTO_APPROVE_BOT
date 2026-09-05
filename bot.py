import asyncio
import html
import logging
import os
from typing import Optional

from aiohttp import web
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatJoinRequestHandler,
    CommandHandler,
    ContextTypes,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("auto-join-acceptor")


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


BOT_TOKEN = required_env("TELEGRAM_BOT_TOKEN")
ADMIN_ID = int(required_env("TELEGRAM_ADMIN_ID"))
CHANNEL_URL = os.getenv("CHANNEL_URL", "").strip()
PORT = int(os.getenv("PORT", "8080"))

bot_username = ""

SMALL_CAPS = str.maketrans(
    "abcdefghijklmnopqrstuvwxyz",
    "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀsᴛᴜᴠᴡxʏᴢ",
)


def small_caps(text: str) -> str:
    return text.translate(SMALL_CAPS)


def welcome_buttons() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "+ " + small_caps("Add Me To Your Group"),
                    url=f"https://t.me/{bot_username}?startgroup=true",
                )
            ],
            [
                InlineKeyboardButton(
                    "+ " + small_caps("Add Me To Your Channel"),
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
        InlineKeyboardButton("⏱️ " + small_caps("Visit Channel"), url=channel_url)
        if channel_url
        else InlineKeyboardButton(
            "⏱️ " + small_caps("Visit Channel"), callback_data="visit_channel"
        )
    )
    return InlineKeyboardMarkup(
        [
            [visit_button],
            [
                InlineKeyboardButton(
                    "🙋 " + small_caps("Check I'm Alive Or Not"),
                    callback_data="alive",
                )
            ],
        ]
    )


def first_name(user) -> str:
    return (getattr(user, "first_name", None) or "Friend").strip()


async def start_handler(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None:
        return

    logger.info("Received /start from user %s", getattr(user, "id", "unknown"))
    display_name = html.escape(small_caps(first_name(user).title()))
    text = (
        f"<blockquote>{small_caps('Hello')}, {display_name} ❞</blockquote>\n\n"
        f"🤖 {small_caps('Welcome To Auto Request Accept Bot')}!\n\n"
        f"{small_caps('This Bot Automatically Accepts All Join Request From Your Channel Or Group.')} \n\n"
        f"{small_caps('Just Add Me To Your Group Or Channel')}\n"
        f"{small_caps('And Make It Admin With Full Rights')}."
    )
    try:
        await message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=welcome_buttons(),
        )
    except TelegramError:
        logger.exception("Could not reply to /start")


async def help_handler(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return

    text = (
        "What can this bot do?\n\n"
        "This Bot can Approve Join Request Automatically.\n\n"
        "Just add bot as Administrator in your channels/groups and it's done ✅"
    )
    await message.reply_text(text)


async def status_handler(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None or getattr(user, "id", None) != ADMIN_ID:
        return

    await message.reply_text(
        f"✅ {small_caps('Auto Request Acceptor Is Online')}.\n\n"
        f"{small_caps('Join Requests Are Being Approved Automatically')}."
    )


async def callback_handler(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    callback = update.callback_query
    if callback is None:
        return

    if callback.data == "alive":
        await callback.answer("✅ I'm alive and accepting requests.", show_alert=True)
    elif callback.data == "visit_channel":
        await callback.answer(
            "Set CHANNEL_URL to enable the channel link button.",
            show_alert=True,
        )


async def join_request_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    request = update.chat_join_request
    if request is None:
        return

    chat_title = request.chat.title or "YOUR CHANNEL OR GROUP"
    user_id = request.from_user.id

    try:
        await context.bot.approve_chat_join_request(request.chat.id, user_id)
        logger.info("Approved join request from %s in %s", user_id, request.chat.id)
    except TelegramError:
        logger.exception("Could not approve join request from %s", user_id)
        return

    alive_text = small_caps("Tap Button Below To Check I'm Alive Or Not")
    text = (
        f"{small_caps('Welcome')}, {small_caps(first_name(request.from_user).title())}!\n\n"
        f"{small_caps('Your Respected Request Of Joining')} "
        f"{small_caps(chat_title.title())} "
        f"{small_caps('Has Been Already Accepted')}.\n\n"
        f"✅ {alive_text}."
    )
    try:
        await context.bot.send_message(
            user_id,
            text,
            reply_markup=accepted_buttons(getattr(request.chat, "username", None)),
        )
    except TelegramError:
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


def create_application() -> Application:
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler(["help", "what"], help_handler))
    application.add_handler(CommandHandler("status", status_handler))
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(ChatJoinRequestHandler(join_request_handler))
    return application


async def main() -> None:
    global bot_username

    application = create_application()
    await application.initialize()
    bot = await application.bot.get_me()
    bot_username = bot.username or ""
    if not bot_username:
        raise RuntimeError("The bot account must have a username.")

    await application.start()
    await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    runner = await start_health_server()
    logger.info("@%s is ready.", bot_username)

    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
        await application.updater.stop()
        await application.stop()
        await application.shutdown()


if __name__ == "__main__":
    asyncio.run(main())