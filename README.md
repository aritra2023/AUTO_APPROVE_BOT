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
- `TELEGRAM_API_ID` and `TELEGRAM_API_HASH` — required for the admin `/login` bulk approval flow

Optional:

- `CHANNEL_URL` — fallback link for the “VISIT CHANNEL” button when a join request does not include a channel username or invite link
- `PORT` — health endpoint port; defaults to `8080`
- `STATE_FILE` — local stats/user state path; defaults to `bot_state.json`

The bot must be added as an administrator with permission to invite users via link / approve join requests.

Admin commands:

- `/status` — check that the bot is online
- `/stats` — total users, total channels, and total groups
- `/cast` — reply to any text, photo, video, document, or button message and send `/cast`; it copies the message without a forward tag
- `/login` — securely log the admin's Telegram user account in, select a channel, and approve all or a custom number of pending requests
- `/cancel` — cancel an active cast or bulk approval flow

The `/login` flow asks for the admin's Telegram contact and OTP in the private bot chat. OTPs and 2FA passwords are not logged or written to state; Pyrogram's local session file is ignored by git and should be kept private.

## Replit and Oracle

Use the same command on both platforms:

```bash
python bot.py
```

Keep the two required values in environment variables or secrets. MongoDB is not required by this version.

The web endpoint is available at `/health` and returns a small JSON status response.