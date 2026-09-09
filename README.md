# Auto Join Request Acceptor

Lean Python Telegram bot that approves channel and group join requests quickly.
The repository contains only the bot runtime and deployment documentation.

## Local run

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN="your-new-token"
export TELEGRAM_ADMIN_ID="your-telegram-user-id"
PORT=8082 python bot.py
```

Required environment variables:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ADMIN_ID`

Optional:

- `CHANNEL_URL` — fallback link for the “VISIT CHANNEL” button
- `PORT` — health endpoint port; defaults to `8080`
- `STATE_FILE` — local stats/user state path; defaults to `bot_state.json`
- `MONGO_URL` — optional MongoDB connection string for persistent state
- `MONGO_DB_NAME` — MongoDB database name; defaults to `auto_join_acceptor`

The bot must be an administrator with permission to approve join requests.

## Admin commands

- `/status` — check that the bot is online
- `/stats` — total users, channels, and groups
- `/cast` — reply to a text, photo, video, document, or button message and send `/cast`
- `/cancel` — cancel an active cast flow

## Fast approval behavior

The approval API call is completed before the optional welcome message work.
Welcome-link lookup runs in the background and is cached per chat, so repeated
private-channel requests do not wait for repeated Telegram invite-link calls.
Pending Telegram updates are discarded on restart to avoid replaying old events.

## Oracle Cloud

Use the complete [Oracle deployment guide](ORACLE_DEPLOY.md). It covers:

- lean shallow cloning
- Python virtualenv and dependencies
- secure `.env` setup
- systemd startup and logs
- pulling updated code and restarting safely
- local health checks

Keep Telegram credentials out of Git and never commit `.env`.