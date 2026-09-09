# Auto Join Request Acceptor

Python Telegram bot that automatically approves channel and group join requests.

## Run & Operate

- Run workflow: `PORT=8082 python bot.py`
- Health check: `GET /health`
- Required secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ADMIN_ID`
- Optional environment: `CHANNEL_URL`, `STATE_FILE`, `MONGO_URL`, `MONGO_DB_NAME`

## Stack

- Python 3.12
- `python-telegram-bot`
- `aiohttp` health endpoint
- Optional MongoDB persistence via `pymongo`

## Where things live

- `bot.py` — bot handlers, join-request approval, health endpoint, and state management
- `requirements.txt` — Python dependencies
- `.replit` — Replit run workflow

## Architecture decisions

- Local state is used when `MONGO_URL` is not configured.
- The bot and health endpoint run in one process so the workflow can be monitored by Replit.

## Product

- Automatically approves Telegram channel and group join requests.
- Provides admin status, stats, and message-casting commands.

## User preferences

None recorded.

## Gotchas

- The bot must be an administrator with permission to approve join requests.
- Keep Telegram credentials in Replit Secrets; do not place them in `.replit` or source files.
- MongoDB is recommended for durable state outside the current Replit environment.

## Pointers

- See `README.md` for admin commands and Oracle deployment notes.
