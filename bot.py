import asyncio
import logging
import os
from typing import Optional

from aiohttp import web
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
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


async def start_handler(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None:
        return

    logger.info("Received /start from user %s", getattr(user, "id", "unknown"))
    text = (
        f"HELLO, {first_name(user)}!\n\n"
        "🤖 WELCOME TO AUTO REQUEST ACCEPT BOT!\n\n"
        "THIS BOT AUTOMATICALLY ACCEPTS ALL JOIN REQUEST FROM YOUR CHANNEL OR GROUP.\n\n"
        "JUST ADD THIS BOT IN YOUR GROUP OR CHANNEL\n"
        "AND MAKE IT ADMIN WITH FULL RIGHTS."
    )
    try:
        await message.reply_text(text, reply_markup=welcome_buttons())
    except TelegramError:
        logger.exception("Could not reply to /start")


async def help_handler(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return

    text = (
        "WHAT CAN THIS BOT DO?\n\n"
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
        "✅ AUTO REQUEST ACCEPTOR IS ONLINE.\n\n"
        "JOIN REQUESTS ARE BEING APPROVED AUTOMATICALLY."
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

    text = (
        f"WELCOME, {first_name(request.from_user)}!\n\n"
        f"YOUR RESPECTED REQUEST OF JOINING {chat_title.upper()} "
        "HAS BEEN ALREADY ACCEPTED.\n\n"
        "✅ TAP BUTTON BELOW TO CHECK I'M ALIVE OR NOT."
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