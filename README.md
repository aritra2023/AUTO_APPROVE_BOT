# Auto Join Request Acceptor

Minimal Python Telegram bot that automatically approves channel and group join requests.

## Run

```bash
pip install -r requirements.txt
python bot.py
```

Required environment variables:

- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ADMIN_ID`

Optional:

- `CHANNEL_URL` — target channel link for the “VISIT CHANNEL” button
- `PORT` — health endpoint port; defaults to `8080`

The bot must be added as an administrator with permission to invite users via link / approve join requests. The `/status` command is restricted to `TELEGRAM_ADMIN_ID`.

## Replit and Oracle

Use the same command on both platforms:

```bash
python bot.py
```

Keep the four required values in environment variables or secrets. MongoDB is not required by this version.

The web endpoint is available at `/health` and returns a small JSON status response.