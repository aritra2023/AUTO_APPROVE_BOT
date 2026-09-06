import asyncio
import html
import json
import logging
import os
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from aiohttp import web
from pyrogram import Client
from pyrogram.errors import (
    FloodWait,
    PhoneCodeExpired,
    PhoneCodeInvalid,
    RPCError as PyrogramRPCError,
    SessionPasswordNeeded,
    Unauthorized,
)
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
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
    MessageHandler,
    filters,
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
TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID", "0") or "0")
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "").strip()

bot_username = ""
CAST_PIN, CAST_CONFIRM = range(2)
LOGIN_CONTACT, LOGIN_CODE, LOGIN_PASSWORD, LOGIN_CHANNEL, LOGIN_MODE, LOGIN_COUNT = range(
    10, 16
)
user_client: Optional[Client] = None

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
            "request_users": [],
            "approved": 0,
            "casts": 0,
            "managed_chats": {},
        }
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return {
            "users": sorted({int(user_id) for user_id in state.get("users", [])}),
            "request_users": sorted(
                {int(user_id) for user_id in state.get("request_users", [])}
            ),
            "approved": int(state.get("approved", 0)),
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
            "request_users": [],
            "approved": 0,
            "casts": 0,
            "managed_chats": {},
        }


state = load_state()


def save_state() -> None:
    temporary_file = STATE_FILE.with_suffix(".tmp")
    temporary_file.write_text(json.dumps(state), encoding="utf-8")
    temporary_file.replace(STATE_FILE)


def remember_user(user_id: int) -> None:
    if user_id not in state["users"]:
        state["users"].append(user_id)
        state["users"].sort()
        save_state()


def remember_request_user(user_id: int) -> None:
    if user_id not in state["request_users"]:
        state["request_users"].append(user_id)
        state["request_users"].sort()


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
    if user is not None:
        remember_user(user.id)

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


async def help_handler(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return

    text = (
        f"<b>{small_caps('What Can This Bot Do?')}</b>\n\n"
        f"<b>{small_caps('This Bot Can Approve Join Request Automatically.')}</b>\n\n"
        f"<b>{small_caps('Just Add Bot As Administrator In Your Channels Or Groups And It Is Done')} ✅</b>"
    )
    await message.reply_text(text, parse_mode=ParseMode.HTML)


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


def user_client_configured() -> bool:
    return TELEGRAM_API_ID > 0 and bool(TELEGRAM_API_HASH)


async def get_user_client() -> Client:
    global user_client
    if not user_client_configured():
        raise RuntimeError("Telegram API ID and API hash are not configured.")
    if user_client is None:
        user_client = Client(
            "admin_user",
            api_id=TELEGRAM_API_ID,
            api_hash=TELEGRAM_API_HASH,
        )
    if not user_client.is_connected:
        await user_client.connect()
    return user_client


async def show_channel_prompt(message) -> int:
    await message.reply_text(
        f"<b>{small_caps('Login Done')} ✅</b>\n\n"
        f"<b>{small_caps('Send The Channel ID, @Username, Or Forward Any Message From That Channel')}.</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=ReplyKeyboardRemove(),
    )
    return LOGIN_CHANNEL


async def login_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    message = update.effective_message
    if message is None or not is_admin(update):
        return ConversationHandler.END
    if update.effective_chat and update.effective_chat.type != "private":
        await message.reply_text(
            f"<b>{small_caps('Use /login In The Bot Private Chat')}.</b>",
            parse_mode=ParseMode.HTML,
        )
        return ConversationHandler.END

    context.user_data.clear()
    if user_client is not None and user_client.is_connected:
        try:
            await user_client.get_me()
            return await show_channel_prompt(message)
        except Unauthorized:
            pass

    buttons = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ " + small_caps("Yes, Continue"),
                    callback_data="login_contact_yes",
                ),
                InlineKeyboardButton(
                    "❌ " + small_caps("Cancel"),
                    callback_data="login_contact_no",
                ),
            ]
        ]
    )
    await message.reply_text(
        f"<b>{small_caps('Telegram Login Required')}.</b>\n\n"
        f"<b>{small_caps('Do You Want To Share Your Telegram Contact For Login?')}</b>\n\n"
        f"<b>{small_caps('Your OTP And Password Will Not Be Saved Or Logged')}.</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=buttons,
    )
    return LOGIN_CONTACT


async def login_contact_choice(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    callback = update.callback_query
    if callback is None:
        return ConversationHandler.END
    await callback.answer()
    if callback.data == "login_contact_no":
        context.user_data.clear()
        await callback.edit_message_text(
            f"<b>{small_caps('Login Cancelled')}.</b>",
            parse_mode=ParseMode.HTML,
        )
        return ConversationHandler.END

    await callback.edit_message_text(
        f"<b>{small_caps('Please Press The Button Below And Share Your Own Telegram Contact')}.</b>",
        parse_mode=ParseMode.HTML,
    )
    await callback.message.reply_text(
        f"<b>{small_caps('Share Contact')}</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=ReplyKeyboardMarkup(
            [[KeyboardButton("📱 " + small_caps("Share My Contact"), request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
    )
    return LOGIN_CONTACT


async def login_contact_received(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    message = update.effective_message
    contact = message.contact if message else None
    if message is None or contact is None:
        return LOGIN_CONTACT
    if contact.user_id and contact.user_id != ADMIN_ID:
        await message.reply_text(
            f"<b>{small_caps('Please Share Your Own Contact, Not Someone Else')}.</b>",
            parse_mode=ParseMode.HTML,
        )
        return LOGIN_CONTACT

    try:
        client = await get_user_client()
        try:
            await client.get_me()
            return await show_channel_prompt(message)
        except Unauthorized:
            pass

        sent_code = await client.send_code(contact.phone_number)
        context.user_data["login_phone"] = contact.phone_number
        context.user_data["login_code_hash"] = sent_code.phone_code_hash
        await message.reply_text(
            f"<b>{small_caps('OTP Sent')}.</b>\n\n"
            f"<b>{small_caps('Send The Telegram Login Code Here')}.</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardRemove(),
        )
        return LOGIN_CODE
    except (PyrogramRPCError, TelegramError):
        logger.exception("Could not start Telegram user login")
        await message.reply_text(
            f"<b>{small_caps('Could Not Send OTP. Please Check The Contact And Try Again')}.</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardRemove(),
        )
        return ConversationHandler.END


async def login_code_received(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    message = update.effective_message
    if message is None or not message.text:
        return LOGIN_CODE
    code = "".join(message.text.split())
    phone = context.user_data.get("login_phone")
    code_hash = context.user_data.get("login_code_hash")
    if not phone or not code_hash:
        await message.reply_text(
            f"<b>{small_caps('Login Session Expired. Send /login Again')}.</b>",
            parse_mode=ParseMode.HTML,
        )
        return ConversationHandler.END

    try:
        client = await get_user_client()
        await client.sign_in(phone, code_hash, code)
        return await show_channel_prompt(message)
    except SessionPasswordNeeded:
        await message.reply_text(
            f"<b>{small_caps('Two Step Verification Is Enabled')}.</b>\n\n"
            f"<b>{small_caps('Send Your Telegram 2FA Password')}.</b>",
            parse_mode=ParseMode.HTML,
        )
        return LOGIN_PASSWORD
    except PhoneCodeInvalid:
        await message.reply_text(
            f"<b>{small_caps('Invalid OTP. Send The Correct Code')}.</b>",
            parse_mode=ParseMode.HTML,
        )
        return LOGIN_CODE
    except PhoneCodeExpired:
        try:
            client = await get_user_client()
            resent_code = await client.resend_code(phone, code_hash)
            context.user_data["login_code_hash"] = resent_code.phone_code_hash
            await message.reply_text(
                f"<b>{small_caps('Previous OTP Expired')}.</b>\n\n"
                f"<b>{small_caps('A New OTP Was Sent. Send Only The Latest Code')}.</b>",
                parse_mode=ParseMode.HTML,
            )
            return LOGIN_CODE
        except PyrogramRPCError:
            logger.exception("Could not resend expired Telegram login code")
            await message.reply_text(
                f"<b>{small_caps('OTP Expired. Send /login Again')}.</b>",
                parse_mode=ParseMode.HTML,
            )
            return ConversationHandler.END
    except (PyrogramRPCError, TelegramError):
        logger.exception("Could not complete Telegram user login")
        await message.reply_text(
            f"<b>{small_caps('Login Failed. Please Send /login Again')}.</b>",
            parse_mode=ParseMode.HTML,
        )
        return ConversationHandler.END


async def login_password_received(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    message = update.effective_message
    if message is None or not message.text:
        return LOGIN_PASSWORD
    try:
        client = await get_user_client()
        await client.check_password(message.text)
        return await show_channel_prompt(message)
    except (PyrogramRPCError, TelegramError):
        logger.exception("Could not complete Telegram 2FA login")
        await message.reply_text(
            f"<b>{small_caps('Invalid 2FA Password. Try Again')}.</b>",
            parse_mode=ParseMode.HTML,
        )
        return LOGIN_PASSWORD


def forwarded_channel_id(message) -> Optional[int]:
    origin = getattr(message, "forward_origin", None)
    origin_chat = getattr(origin, "chat", None)
    if origin_chat is not None:
        return origin_chat.id
    old_forwarded_chat = getattr(message, "forward_from_chat", None)
    return getattr(old_forwarded_chat, "id", None)


def channel_reference_from_message(message) -> Optional[str]:
    forwarded_id = forwarded_channel_id(message)
    if forwarded_id is not None:
        return str(forwarded_id)
    text = (message.text or "").strip()
    return text or None


def normalized_status(status) -> str:
    value = getattr(status, "value", status)
    return str(value).lower().split(".")[-1]


async def login_channel_received(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    message = update.effective_message
    if message is None:
        return LOGIN_CHANNEL
    reference = channel_reference_from_message(message)
    if not reference:
        await message.reply_text(
            f"<b>{small_caps('Send A Channel ID, @Username, Or Forward A Channel Message')}.</b>",
            parse_mode=ParseMode.HTML,
        )
        return LOGIN_CHANNEL

    try:
        client = await get_user_client()
        chat = await client.get_chat(reference)
        logged_in_user = await client.get_me()
        user_member = await client.get_chat_member(chat.id, logged_in_user.id)
        user_status = normalized_status(user_member.status)
        if user_status not in {"administrator", "creator", "owner"}:
            await message.reply_text(
                f"<b>{small_caps('The Logged In Telegram Account Must Be An Admin Of This Channel')}.</b>",
                parse_mode=ParseMode.HTML,
            )
            return LOGIN_CHANNEL
        if (
            user_status == "administrator"
            and getattr(user_member, "can_invite_users", True) is False
        ):
            await message.reply_text(
                f"<b>{small_caps('The Logged In Telegram Account Needs Invite Or Join Request Permission')}.</b>",
                parse_mode=ParseMode.HTML,
            )
            return LOGIN_CHANNEL

        bot_member = await context.bot.get_chat_member(
            chat.id, (await context.bot.get_me()).id
        )
        bot_status = normalized_status(bot_member.status)
        if bot_status not in {"administrator", "creator", "owner"}:
            await message.reply_text(
                f"<b>{small_caps('The Bot Must Also Be An Admin Of This Channel')}.</b>",
                parse_mode=ParseMode.HTML,
            )
            return LOGIN_CHANNEL
        if (
            bot_status == "administrator"
            and getattr(bot_member, "can_invite_users", True) is False
        ):
            await message.reply_text(
                f"<b>{small_caps('The Bot Needs Invite Or Join Request Permission In This Channel')}.</b>",
                parse_mode=ParseMode.HTML,
            )
            return LOGIN_CHANNEL

        context.user_data["pending_chat_id"] = chat.id
        context.user_data["pending_chat_title"] = chat.title or str(chat.id)
        requests = [
            request
            async for request in client.get_chat_join_requests(chat.id, limit=1)
        ]
        if not requests:
            await message.reply_text(
                f"<b>{small_caps('No Pending Join Requests Found In')} "
                f"{html.escape(small_caps((chat.title or str(chat.id)).title()))}.</b>",
                parse_mode=ParseMode.HTML,
            )
            return ConversationHandler.END

        mode_buttons = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ " + small_caps("All"),
                        callback_data="login_requests_all",
                    ),
                    InlineKeyboardButton(
                        "🔢 " + small_caps("Custom"),
                        callback_data="login_requests_custom",
                    ),
                ]
            ]
        )
        await message.reply_text(
            f"<b>{small_caps('Channel')}: "
            f"{html.escape(small_caps((chat.title or str(chat.id)).title()))}</b>\n\n"
            f"<b>{small_caps('How Many Pending Requests Should Be Accepted?')}</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=mode_buttons,
        )
        return LOGIN_MODE
    except (PyrogramRPCError, TelegramError):
        logger.exception("Could not load channel join requests")
        await message.reply_text(
            f"<b>{small_caps('Could Not Access This Channel. Make Sure The Logged In Account Is Admin')}.</b>",
            parse_mode=ParseMode.HTML,
        )
        return LOGIN_CHANNEL


async def custom_count_prompt(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    message = update.effective_message
    if message is not None:
        await message.reply_text(
            f"<b>{small_caps('How Many Requests Should Be Accepted? Send A Number')}.</b>",
            parse_mode=ParseMode.HTML,
        )
    return LOGIN_COUNT


async def login_mode_choice(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    callback = update.callback_query
    if callback is None:
        return ConversationHandler.END
    await callback.answer()
    if callback.data == "login_requests_custom":
        await callback.edit_message_text(
            f"<b>{small_caps('How Many Requests Should Be Accepted? Send A Number')}.</b>",
            parse_mode=ParseMode.HTML,
        )
        return LOGIN_COUNT
    return await process_pending_requests(update, context, 0)


async def login_mode_text(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    message = update.effective_message
    choice = (message.text or "").strip().lower() if message else ""
    if choice in {"custom", "customs"}:
        return await custom_count_prompt(update, context)
    if choice == "all":
        return await process_pending_requests(update, context, 0)
    if message is not None:
        await message.reply_text(
            f"<b>{small_caps('Choose All Or Custom')}.</b>",
            parse_mode=ParseMode.HTML,
        )
    return LOGIN_MODE


async def login_count_received(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    message = update.effective_message
    if message is None or not message.text:
        return LOGIN_COUNT
    try:
        count = int(message.text.strip())
        if count < 1:
            raise ValueError
    except ValueError:
        await message.reply_text(
            f"<b>{small_caps('Send A Valid Positive Number')}.</b>",
            parse_mode=ParseMode.HTML,
        )
        return LOGIN_COUNT
    return await process_pending_requests(update, context, count)


async def login_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    context.user_data.clear()
    message = update.effective_message
    if message is not None:
        await message.reply_text(
            f"<b>{small_caps('Login Cancelled')}.</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=ReplyKeyboardRemove(),
        )
    return ConversationHandler.END


async def process_pending_requests(
    update: Update, context: ContextTypes.DEFAULT_TYPE, limit: int
) -> int:
    message = update.effective_message
    chat_id = context.user_data.get("pending_chat_id")
    chat_title = context.user_data.get("pending_chat_title", "channel")
    if chat_id is None:
        if message is not None:
            await message.reply_text(
                f"<b>{small_caps('Channel Selection Expired. Send /login Again')}.</b>",
                parse_mode=ParseMode.HTML,
            )
        return ConversationHandler.END

    progress_message = None
    if message is not None:
        progress_message = await message.reply_text(
            f"<b>{small_caps('Starting Request Approval For')} "
            f"{html.escape(small_caps(str(chat_title).title()))}...</b>",
            parse_mode=ParseMode.HTML,
        )

    approved = 0
    failed = 0
    try:
        client = await get_user_client()
        async for request in client.get_chat_join_requests(chat_id, limit=limit):
            try:
                await client.approve_chat_join_request(chat_id, request.user.id)
                approved += 1
                if approved % 25 == 0 and progress_message is not None:
                    await progress_message.edit_text(
                        f"<b>{small_caps('Approved')}: {approved}</b>",
                        parse_mode=ParseMode.HTML,
                    )
            except FloodWait as error:
                await asyncio.sleep(error.value)
                try:
                    await client.approve_chat_join_request(chat_id, request.user.id)
                    approved += 1
                except PyrogramRPCError:
                    failed += 1
            except (PyrogramRPCError, TelegramError):
                failed += 1
            await asyncio.sleep(0.05)
    except (PyrogramRPCError, TelegramError):
        logger.exception("Could not process pending requests")
        if progress_message is not None:
            await progress_message.edit_text(
                f"<b>{small_caps('Could Not Read Pending Requests')}.</b>",
                parse_mode=ParseMode.HTML,
            )
        return ConversationHandler.END

    if progress_message is not None:
        await progress_message.edit_text(
            f"<b>✅ {small_caps('Request Approval Complete')}</b>\n\n"
            f"<b>{small_caps('Approved')}: {approved}\n"
            f"{small_caps('Failed')}: {failed}</b>",
            parse_mode=ParseMode.HTML,
        )
    context.user_data.clear()
    return ConversationHandler.END


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
    save_state()
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
    save_state()


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
    remember_request_user(user_id)
    state["approved"] += 1
    remember_managed_chat(request.chat)
    save_state()
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
                getattr(request.invite_link, "invite_link", None),
            ),
        )
    except TelegramError:
        logger.exception("Could not send welcome message to join-request chat")


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
    application.add_handler(CommandHandler("stats", stats_handler))
    application.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("login", login_handler)],
            states={
                LOGIN_CONTACT: [
                    CallbackQueryHandler(
                        login_contact_choice, pattern="^login_contact_"
                    ),
                    MessageHandler(filters.CONTACT, login_contact_received),
                ],
                LOGIN_CODE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, login_code_received)
                ],
                LOGIN_PASSWORD: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND, login_password_received
                    )
                ],
                LOGIN_CHANNEL: [
                    MessageHandler(
                        (filters.TEXT | filters.FORWARDED) & ~filters.COMMAND,
                        login_channel_received,
                    )
                ],
                LOGIN_MODE: [
                    CallbackQueryHandler(
                        login_mode_choice, pattern="^login_requests_"
                    ),
                    CommandHandler(["custom", "customs"], custom_count_prompt),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, login_mode_text),
                ],
                LOGIN_COUNT: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND, login_count_received
                    )
                ],
            },
            fallbacks=[CommandHandler("cancel", login_cancel)],
            allow_reentry=True,
            per_user=True,
            per_chat=True,
        )
    )
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