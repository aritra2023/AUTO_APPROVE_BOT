# Oracle Cloud Deployment

This is a lean Python-only repository. Oracle runs only `bot.py`; there is no
Node.js, pnpm, frontend, API server, or public webhook to configure.

The bot uses Telegram long polling, so Oracle needs outbound HTTPS only. Keep
only SSH (`TCP 22`) open in the OCI security list. The health port is local-only
unless you intentionally open it.

## 1. Create the Oracle VM

In OCI, create a Compute instance with:

- Ubuntu 22.04 or 24.04
- 1 OCPU and 1 GB RAM is enough for this bot
- An SSH key pair
- A public IPv4 address
- Ingress TCP 22 allowed from your own IP

Ampere A1 Flex is a good free-tier choice when available. E2 Micro is also
enough for this Python bot.

## 2. Connect over SSH

From your computer:

```bash
chmod 400 oracle-key.pem
ssh -i oracle-key.pem ubuntu@YOUR_ORACLE_PUBLIC_IP
```

Use `opc` instead of `ubuntu` if you created an Oracle Linux instance.

## 3. Install the runtime

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git
sudo mkdir -p /opt/auto-join-bot
sudo chown -R "$USER":"$(id -gn)" /opt/auto-join-bot
```

## 4. Upload the project

For a Git repository, use a shallow clone so old Git history is not downloaded:

```bash
cd /opt
git clone --depth 1 --single-branch --branch main YOUR_REPOSITORY_URL auto-join-bot
cd /opt/auto-join-bot
```

Or copy the project from your computer:

```bash
scp -i oracle-key.pem -r . ubuntu@YOUR_ORACLE_PUBLIC_IP:/tmp/auto-join-bot
```

Then on Oracle:

```bash
sudo rm -rf /opt/auto-join-bot
sudo mv /tmp/auto-join-bot /opt/auto-join-bot
sudo chown -R "$USER":"$(id -gn)" /opt/auto-join-bot
cd /opt/auto-join-bot
```

## 5. Install Python dependencies

```bash
cd /opt/auto-join-bot
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
deactivate
```

The requirements file intentionally contains `python-telegram-bot`, not the
separate PyPI package named `telegram`. Installing both can corrupt the shared
`telegram` import namespace.

## 6. Add environment variables

Create the file without putting secrets into the repository:

```bash
cd /opt/auto-join-bot
nano .env
```

Use this format:

```dotenv
TELEGRAM_BOT_TOKEN=YOUR_BOT_TOKEN
TELEGRAM_ADMIN_ID=YOUR_TELEGRAM_USER_ID
CHANNEL_URL=https://t.me/YOUR_CHANNEL
PORT=8082
STATE_FILE=/opt/auto-join-bot/bot_state.json
MONGO_URL=YOUR_MONGODB_CONNECTION_STRING
MONGO_DB_NAME=auto_join_acceptor
```

`CHANNEL_URL` is optional when join requests come from a public channel or an
invite link. `MONGO_URL` should be kept private. Protect the file:

```bash
chmod 600 /opt/auto-join-bot/.env
```

## 7. Test it manually once

```bash
cd /opt/auto-join-bot
set -a
. ./.env
set +a
.venv/bin/python bot.py
```

You should see:

```text
Application started
@your_bot is ready
```

Press `Ctrl+C` after confirming startup.

## 8. Run it permanently with systemd

Create the service using the current Oracle user:

```bash
sudo tee /etc/systemd/system/auto-join-bot.service > /dev/null <<EOF
[Unit]
Description=Telegram Auto Join Request Acceptor
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
Group=$(id -gn)
WorkingDirectory=/opt/auto-join-bot
EnvironmentFile=/opt/auto-join-bot/.env
ExecStart=/opt/auto-join-bot/.venv/bin/python /opt/auto-join-bot/bot.py
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
```

Start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now auto-join-bot
sudo systemctl status auto-join-bot --no-pager
```

Follow live logs:

```bash
sudo journalctl -u auto-join-bot -f
```

Check the local health endpoint:

```bash
curl http://127.0.0.1:8082/health
```

## 9. Telegram setup

1. Open the bot and send `/start`.
2. Add the bot to the target channel or group.
3. Make it an administrator.
4. Give it permission to invite users / approve join requests.
5. Submit a fresh join request to test.
6. Use `/status` and `/stats` from the configured admin account.

## 10. Updating the bot

Run this after pushing updated code to the repository:

```bash
cd /opt/auto-join-bot
git pull --ff-only origin main

# Keep the existing .env and bot_state.json.
# Remove both old distributions once, because the conflicting package
# named "telegram" may have overwritten shared import files.
.venv/bin/python -m pip uninstall -y telegram python-telegram-bot || true
.venv/bin/python -m pip install --upgrade --force-reinstall -r requirements.txt

sudo systemctl restart auto-join-bot
sudo systemctl status auto-join-bot --no-pager
sudo journalctl -u auto-join-bot -n 50 --no-pager
```

If `git pull --ff-only` reports local changes, do not use a destructive reset.
Inspect them first:

```bash
git status
git diff
```

Back up `bot_state.json` before replacing the VM. It contains local user and
admin-chat statistics. If MongoDB is configured, it is the durable source of
state after restart.

## Health and troubleshooting

```bash
curl http://127.0.0.1:8082/health
sudo systemctl is-active auto-join-bot
sudo journalctl -u auto-join-bot -n 100 --no-pager
```

Expected health response:

```json
{"status": "ok", "bot": "running"}
```

If Telegram join approval is still slow, set `CHANNEL_URL` in `.env`. This
avoids private-chat invite-link discovery and lets the welcome message use the
known URL immediately. Approval itself does not wait for that welcome message.
