## EatButCount Telegram Bot - Linux VPS Setup (Ubuntu)

This guide documents the full setup used to run the bot indefinitely on a Hetzner Ubuntu VPS.

It covers:

- Python environment setup
- .env configuration
- Running with systemd (auto-start on reboot, auto-restart on crash)
- Logs and troubleshooting
- Update workflow

Set these once and use the same values in all commands below:

```bash
APP_USER=<linux_username>
BASE_DIR=/home/$APP_USER/telegrambot
PROJECT_DIR=$BASE_DIR/telegramBot-for-EatButCount
VENV_DIR=$BASE_DIR/telegrambot-env
SERVICE_NAME=eatbutcount-bot
```

---

## 1. Server prerequisites

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git
```

Optional but recommended:

```bash
sudo timedatectl set-timezone Asia/Kolkata
```

---

## 2. Project layout used on server

Working paths in this guide:

- Base directory: `$BASE_DIR`
- Virtual env: `$VENV_DIR`
- Project code: `$PROJECT_DIR`
- Service name: `$SERVICE_NAME`

If your paths differ, update commands and systemd file accordingly.

---

## 3. Create virtual environment and install dependencies

```bash
cd "$BASE_DIR"
python3 -m venv telegrambot-env
source "$VENV_DIR/bin/activate"

cd "$PROJECT_DIR"
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 4. Configure .env

Create the env file in the project root:

```bash
nano "$PROJECT_DIR/.env"
```

Use this format:

- No spaces around `=`
- Prefer no quotes

Example:

```dotenv
VITE_SUPABASE_URL=https://your-project.supabase.co
VITE_SUPABASE_PUBLISHABLE_DEFAULT_KEY=your_publishable_key
TELEGRAM_TOKEN=your_telegram_token
GEMINI_API_KEY=your_gemini_api_key
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key
MCP_SERVER_URL=http://your-server-ip:8000/sse
GEMINI_MODEL=gemini-2.5-flash
```

Protect it:

```bash
chmod 600 "$PROJECT_DIR/.env"
```

---

## 5. Verify paths before creating service

Run these checks. Each should print `ok`.

```bash
test -f "$PROJECT_DIR/main.py" && echo ok_main
test -f "$PROJECT_DIR/.env" && echo ok_env
test -x "$VENV_DIR/bin/python" && echo ok_python
id "$APP_USER"
```

---

## 6. Create systemd service (run indefinitely)

Create the unit file:

```bash
sudo nano /etc/systemd/system/$SERVICE_NAME.service
```

Paste:

```ini
[Unit]
Description=EatButCount Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=<linux_username>
Group=<linux_username>
WorkingDirectory=<project_dir>
EnvironmentFile=<project_dir>/.env
Environment=PYTHONUNBUFFERED=1
ExecStart=<venv_dir>/bin/python <project_dir>/main.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Important: in the unit file, replace `<linux_username>`, `<project_dir>`, and `<venv_dir>` with real absolute values before saving.

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl start "$SERVICE_NAME"
```

Check status:

```bash
sudo systemctl status "$SERVICE_NAME" --no-pager -l
```

Why this runs forever:

- `Restart=always` restarts after crash/exit
- `enable` starts automatically on reboot

---

## 7. Logs and health checks

Follow logs live:

```bash
journalctl -u "$SERVICE_NAME" -f
```

Recent logs:

```bash
journalctl -u "$SERVICE_NAME" -n 100 --no-pager
```

Service lifecycle commands:

```bash
sudo systemctl restart "$SERVICE_NAME"
sudo systemctl stop "$SERVICE_NAME"
sudo systemctl start "$SERVICE_NAME"
sudo systemctl disable "$SERVICE_NAME"
```

---

## 8. Troubleshooting common failures

### A) "failed because of unavailable resources"

Usually one of these:

- wrong `User`/`Group`
- wrong `WorkingDirectory`
- wrong `EnvironmentFile`
- wrong python path in `ExecStart`
- case mismatch in folder names (Linux is case-sensitive)

Use:

```bash
sudo systemctl status "$SERVICE_NAME" --no-pager -l
journalctl -xeu "$SERVICE_NAME".service
```

### B) Service fails to read env values

Ensure `.env` has no spaces around `=`.

Bad:

```dotenv
TELEGRAM_TOKEN = "abc"
```

Good:

```dotenv
TELEGRAM_TOKEN=abc
```

### C) Bot runs manually but fails in systemd

Confirm exact command works first:

```bash
"$VENV_DIR/bin/python" "$PROJECT_DIR/main.py"
```

If manual run works, issue is usually in systemd unit paths or env file formatting.

---

## 9. Update/deploy workflow

From project directory:

```bash
cd "$PROJECT_DIR"
git pull
source "$VENV_DIR/bin/activate"
pip install -r requirements.txt
sudo systemctl restart "$SERVICE_NAME"
sudo systemctl status "$SERVICE_NAME" --no-pager -l
```

---

## 10. Security checklist

- Keep `.env` out of git (`.gitignore`)
- Use `chmod 600` on `.env`
- Rotate leaked tokens/keys immediately
- Avoid posting real API keys in chat/screenshots
