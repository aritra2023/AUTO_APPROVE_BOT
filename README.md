# Auto Join Request Acceptor

Minimal Python Telegram bot that automatically approves channel and group join requests.

## Run

```bash
pip install -r requirements.txt
python bot.py
```

Required environment variables:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ADMIN_ID`

Optional:

- `CHANNEL_URL` — fallback link for the “VISIT CHANNEL” button when a join request does not include a channel username or invite link
- `PORT` — health endpoint port; defaults to `8080`
- `STATE_FILE` — local stats/user state path; defaults to `bot_state.json`
- `MONGO_URL` — optional MongoDB connection string; when configured, users, casts, and managed chats survive restarts
- `MONGO_DB_NAME` — MongoDB database name; defaults to `auto_join_acceptor`

The bot must be added as an administrator with permission to invite users via link / approve join requests.

Admin commands:

- `/status` — check that the bot is online
- `/stats` — total users, total channels, and total groups
- `/cast` — reply to any text, photo, video, document, or button message and send `/cast`; it copies the message without a forward tag
- `/cancel` — cancel an active cast flow

## Replit and Oracle

Use the same command on both platforms:

```bash
python bot.py
```

Keep the two required values in environment variables or secrets. MongoDB is not required by this version.

The web endpoint is available at `/health` and returns a small JSON status response.

For a permanent Oracle Cloud VM deployment, follow [ORACLE_DEPLOY.md](ORACLE_DEPLOY.md).