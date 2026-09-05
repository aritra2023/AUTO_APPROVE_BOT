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

- `CHANNEL_URL` — target channel link for the “VISIT CHANNEL” button
- `PORT` — health endpoint port; defaults to `8080`
- `STATE_FILE` — local stats/user state path; defaults to `bot_state.json`

The bot must be added as an administrator with permission to invite users via link / approve join requests.

Admin commands:

- `/status` — check that the bot is online
- `/stats` — users, approved requests, and broadcast count
- `/cast` — reply to any text, photo, video, document, or button message and send `/cast`; it copies the message without a forward tag

## Replit and Oracle

Use the same command on both platforms:

```bash
python bot.py
```

Keep the two required values in environment variables or secrets. MongoDB is not required by this version.

The web endpoint is available at `/health` and returns a small JSON status response.