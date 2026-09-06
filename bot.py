import asyncio
import html
import json
import logging
import os
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from aiohttp import web
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatJoinRequestHandler,
    ChatMemberHandler,
    CommandHandler,
    ConversationHandler,
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
STATE_FILE = Path(os.getenv("STATE_FILE", "bot_state.json"))

bot_username = ""
CAST_PIN, CAST_CONFIRM = range(2)

SMALL_CAPS = str.maketrans(
    "abcdefghijklmnopqrstuvwxyz",
    "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢ",
)


def small_caps(text: str) -> str:
    return text.translate(SMALL_CAPS)


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {
            "users": [],
            "casts": 0,
            "managed_chats": {},
        }
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return {
            "users": sorted({int(user_id) for user_id in state.get("users", [])}),
            "casts": int(state.get("casts", 0)),
            "managed_chats": {
                str(chat_id): chat
                for chat_id, chat in state.get("managed_chats", {}).items()
            },
        }
    except (OSError, ValueError, TypeError):
        logger.exception("Could not read bot state; starting with empty stats")
        return {
            "users": [],
            "casts": 0,
            "managed_chats": {},
        }


state = load_state()
known_users = set(state["users"])
state_save_lock = asyncio.Lock()


def save_state(snapshot: Optional[str] = None) -> None:
    payload = snapshot if snapshot is not None else json.dumps(state)
    temporary_file = STATE_FILE.with_suffix(".tmp")
    temporary_file.write_text(payload, encoding="utf-8")
    temporary_file.replace(STATE_FILE)


async def persist_state() -> None:
    async with state_save_lock:
        snapshot = json.dumps(state)
        await asyncio.to_thread(save_state, snapshot)


def remember_user(user_id: int) -> bool:
    if user_id not in known_users:
        known_users.add(user_id)
        state["users"].append(user_id)
        return True
    return False


def remember_managed_chat(chat) -> None:
    if chat.type == "channel":
        kind = "channel"
    elif chat.type in {"group", "supergroup"}:
        kind = "group"
    else:
        return

    state["managed_chats"][str(chat.id)] = {
        "type": kind,
        "title": chat.title or kind.title(),
    }


def is_admin(update: Update) -> bool:
    return getattr(update.effective_user, "id", None) == ADMIN_ID


def welcome_buttons() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "➕ " + small_caps("Add Me To Your Group"),
                    url=f"https://t.me/{bot_username}?startgroup=true",
                )
            ],
            [
                InlineKeyboardButton(
                    "➕ " + small_caps("Add Me To Your Channel"),
                    url=f"https://t.me/{bot_username}?startchannel=true",
                )
            ],
        ]
    )


def accepted_buttons(
    chat_username: Optional[str], invite_url: Optional[str] = None
) -> InlineKeyboardMarkup:
    if chat_username:
        channel_url = f"https://t.me/{chat_username}"
    elif invite_url and is_valid_url(invite_url):
        channel_url = invite_url
    elif is_valid_url(CHANNEL_URL):
        channel_url = CHANNEL_URL
    else:
        channel_url = ""

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
                    url=f"https://t.me/{bot_username}?start=alive",
                )
            ],
        ]
    )


def is_valid_url(value: Optional[str]) -> bool:
    if not value:
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def first_name(user) -> str:
    return (getattr(user, "first_name", None) or "Friend").strip()


async def start_handler(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    user = update.effective_user
    if message is None:
        return

    logger.info("Received /start from user %s", getattr(user, "id", "unknown"))
    if user is not None and remember_user(user.id):
        asyncio.create_task(persist_state())

    display_name = html.escape(small_caps(first_name(user).title()))
    text = (
        f"<blockquote><b>{small_caps('Hello')}, {display_name} ❞</b></blockquote>\n\n"
        f"<b>🤖 {small_caps('Welcome To Auto Request Accept Bot')}!</b>\n\n"
        f"<b>{small_caps('This Bot Automatically Accepts All Join Request From Your Channel Or Group.')}</b>\n\n"
        f"<b>{small_caps('Just Add Me To Your Group Or Channel')}\n"
        f"{small_caps('And Make It Admin With Full Rights')}.</b>"
    )
    try:
        await message.reply_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=welcome_buttons(),
        )
    except TelegramError:
        logger.exception("Could not reply to /start")


async def status_handler(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None or not is_admin(update):
        return

    await message.reply_text(
        f"<b>✅ {small_caps('Auto Request Acceptor Is Online')}.</b>\n\n"
        f"<b>{small_caps('Join Requests Are Being Approved Automatically')}.</b>",
        parse_mode=ParseMode.HTML,
    )


async def stats_handler(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None or not is_admin(update):
        return

    await message.reply_text(
        f"<b>📊 {small_caps('Bot Stats')}</b>\n\n"
        f"<b>{small_caps('Total Users')}: {len(state['users'])}</b>\n"
        f"<b>{small_caps('Total Channels')}: "
        f"{sum(chat['type'] == 'channel' for chat in state['managed_chats'].values())}</b>\n"
        f"<b>{small_caps('Total Groups')}: "
        f"{sum(chat['type'] == 'group' for chat in state['managed_chats'].values())}</b>",
        parse_mode=ParseMode.HTML,
    )


async def cast_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    message = update.effective_message
    if message is None or not is_admin(update):
        return ConversationHandler.END

    source = message.reply_to_message
    if source is None:
        await message.reply_text(
            f"<b>{small_caps('Reply To Any Text, Photo, Video, Document Or Button Message And Send /cast.')}</b>",
            parse_mode=ParseMode.HTML,
        )
        return ConversationHandler.END

    context.user_data["cast_source_chat_id"] = source.chat_id
    context.user_data["cast_source_message_id"] = source.message_id
    context.user_data["cast_reply_markup"] = source.reply_markup
    pin_buttons = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ " + small_caps("Yes, Pin It"), callback_data="cast_pin_yes"
                ),
                InlineKeyboardButton(
                    "❌ " + small_caps("No"), callback_data="cast_pin_no"
                ),
            ]
        ]
    )
    await message.reply_text(
        f"<b>{small_caps('Do You Want To Pin This Broadcast?')}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=pin_buttons,
    )
    return CAST_PIN


async def cast_pin_choice(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    callback = update.callback_query
    if callback is None:
        return ConversationHandler.END

    await callback.answer()
    context.user_data["cast_pin"] = callback.data == "cast_pin_yes"
    confirm_buttons = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ " + small_caps("Confirm Cast"), callback_data="cast_confirm_yes"
                ),
                InlineKeyboardButton(
                    "❌ " + small_caps("Cancel"), callback_data="cast_confirm_no"
                ),
            ]
        ]
    )
    await callback.edit_message_text(
        f"<b>{small_caps('Confirm Cast To All Users?')}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=confirm_buttons,
    )
    return CAST_CONFIRM


async def cast_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    callback = update.callback_query
    if callback is None:
        return ConversationHandler.END

    await callback.answer()
    if callback.data == "cast_confirm_no":
        context.user_data.clear()
        await callback.edit_message_text(
            f"<b>{small_caps('Cast Cancelled')}.</b>",
            parse_mode=ParseMode.HTML,
        )
        return ConversationHandler.END

    source_chat_id = context.user_data.pop("cast_source_chat_id", None)
    source_message_id = context.user_data.pop("cast_source_message_id", None)
    source_reply_markup = context.user_data.pop("cast_reply_markup", None)
    should_pin = context.user_data.pop("cast_pin", False)
    if source_chat_id is None or source_message_id is None:
        await callback.edit_message_text(
            f"<b>{small_caps('Cast Source Expired. Please Try Again')}.</b>",
            parse_mode=ParseMode.HTML,
        )
        return ConversationHandler.END

    sent = 0
    failed = 0
    pin_failed = 0
    for user_id in list(state["users"]):
        try:
            copied = await context.bot.copy_message(
                chat_id=user_id,
                from_chat_id=source_chat_id,
                message_id=source_message_id,
                reply_markup=source_reply_markup,
            )
            sent += 1
            if should_pin:
                try:
                    await context.bot.pin_chat_message(
                        chat_id=user_id,
                        message_id=copied.message_id,
                        disable_notification=True,
                    )
                except TelegramError:
                    pin_failed += 1
        except TelegramError:
            failed += 1

    state["casts"] += 1
    await persist_state()
    result = (
        f"<b>✅ {small_caps('Cast Complete')}</b>\n\n"
        f"<b>"
        f"{small_caps('Sent')}: {sent}\n"
        f"{small_caps('Failed')}: {failed}</b>"
    )
    if should_pin:
        result += f"\n<b>{small_caps('Pin Failed')}: {pin_failed}</b>"
    await callback.edit_message_text(
        result,
        parse_mode=ParseMode.HTML,
    )
    return ConversationHandler.END


async def cast_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    context.user_data.clear()
    message = update.effective_message
    if message is not None:
        await message.reply_text(
            f"<b>{small_caps('Cast Cancelled')}.</b>",
            parse_mode=ParseMode.HTML,
        )
    return ConversationHandler.END


async def callback_handler(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    callback = update.callback_query
    if callback is None:
        return

    if callback.data == "visit_channel":
        await callback.answer(
            "Set CHANNEL_URL to enable the channel link button.",
            show_alert=True,
        )


async def my_chat_member_handler(
    update: Update, _: ContextTypes.DEFAULT_TYPE
) -> None:
    membership = update.my_chat_member
    if membership is None:
        return

    new_status = membership.new_chat_member.status
    chat_id = str(membership.chat.id)
    if new_status in {"administrator", "creator"}:
        remember_managed_chat(membership.chat)
    elif new_status in {"left", "kicked"}:
        state["managed_chats"].pop(chat_id, None)
    else:
        return
    await persist_state()


async def join_request_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    request = update.chat_join_request
    if request is None:
        return

    chat_title = request.chat.title or "YOUR CHANNEL OR GROUP"
    user_id = request.from_user.id
    delivery_chat_id = request.user_chat_id

    try:
        await context.bot.approve_chat_join_request(request.chat.id, user_id)
        logger.info("Approved join request from %s in %s", user_id, request.chat.id)
    except TelegramError:
        logger.exception("Could not approve join request from %s", user_id)
        return

    remember_user(user_id)
    remember_managed_chat(request.chat)
    visit_url = await resolve_visit_url(context.bot, request.chat)
    alive_text = small_caps("Tap Button Below To Check I'm Alive Or Not")
    accepted_name = html.escape(small_caps(first_name(request.from_user).title()))
    accepted_chat = html.escape(small_caps(chat_title.title()))
    text = (
        f"<b>{small_caps('Welcome')}, {accepted_name}!</b>\n\n"
        f"<b>{small_caps('Your Respected Request Of Joining')} "
        f"{accepted_chat} "
        f"{small_caps('Has Been Already Accepted')}.</b>\n\n"
        f"<b>☑️ {alive_text}.</b>"
    )
    try:
        await context.bot.send_message(
            delivery_chat_id,
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=accepted_buttons(
                getattr(request.chat, "username", None),
                visit_url,
            ),
        )
    except TelegramError:
        logger.exception("Could not send welcome message to join-request chat")
    await persist_state()


async def resolve_visit_url(bot, chat) -> Optional[str]:
    """Return a current public username URL or a non-expiring invite URL."""
    if getattr(chat, "username", None):
        return f"https://t.me/{chat.username}"

    try:
        full_chat = await bot.get_chat(chat.id)
        if getattr(full_chat, "username", None):
            return f"https://t.me/{full_chat.username}"
        current_invite = getattr(full_chat, "invite_link", None)
        if is_valid_url(current_invite):
            return current_invite
    except TelegramError:
        logger.exception("Could not fetch current invite link for chat %s", chat.id)

    try:
        invite = await bot.create_chat_invite_link(
            chat_id=chat.id,
            name="Auto Request Acceptor Visit Link",
            creates_join_request=False,
        )
        if is_valid_url(invite.invite_link):
            return invite.invite_link
    except TelegramError:
        logger.exception("Could not create a fresh invite link for chat %s", chat.id)

    return CHANNEL_URL if is_valid_url(CHANNEL_URL) else None


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
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .connection_pool_size(64)
        .get_updates_connection_pool_size(4)
        .pool_timeout(10)
        .connect_timeout(10)
        .read_timeout(30)
        .write_timeout(30)
        .build()
    )
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("status", status_handler))
    application.add_handler(CommandHandler("stats", stats_handler))
    application.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("cast", cast_handler)],
            states={
                CAST_PIN: [
                    CallbackQueryHandler(cast_pin_choice, pattern="^cast_pin_")
                ],
                CAST_CONFIRM: [
                    CallbackQueryHandler(cast_confirm, pattern="^cast_confirm_")
                ],
            },
            fallbacks=[CommandHandler("cancel", cast_cancel)],
            per_user=True,
            per_chat=True,
        )
    )
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(
        ChatMemberHandler(my_chat_member_handler, ChatMemberHandler.MY_CHAT_MEMBER)
    )
    application.add_handler(ChatJoinRequestHandler(join_request_handler, block=False))
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
    await application.updater.start_polling(
        allowed_updates=["message", "callback_query", "chat_join_request", "my_chat_member"]
    )
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