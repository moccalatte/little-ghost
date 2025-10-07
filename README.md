# Little Ghost — Telegram Userbot

Little Ghost is a powerful and modular Telegram userbot system built with Python, featuring Telethon and `python-telegram-bot`. This project allows you to automate actions on your Telegram account through a secure and easy-to-use bot interface.

The system consists of two main components:
1.  **Wizard Bot**: A Telegram bot (`python-telegram-bot`) that serves as a secure interface to manage your userbots. Only the admin can access it.
2.  **Userbot Service**: A background service (`Telethon`) that executes automated tasks such as data scraping, message replies, or broadcasting.

## Key Features
- **Wizard-Based Management**: Control all your userbots from a single, secure wizard bot.
- **Multi-Account Support**: Manage multiple userbot accounts simultaneously.
- **Task-Based Architecture**: The wizard delegates tasks to the userbot service, which runs them asynchronously.
- **Session String Generator**: Create Telethon session strings directly from the wizard via OTP/QR code without leaving the app.
- **Group & Channel Scraping**: Get a complete list of all groups and channels your userbot has joined.
- **Local Storage**: All data (sessions, tasks, configurations) is stored locally in an SQLite database.
- **Detailed Logging**: Activities are logged to files for easy debugging.
- **Per-Admin Conversation Logs**: Every wizard interaction is saved in `logs/wizard/users/{telegram_id}.log` for easy review.
- **Automated QA**: The Admin menu provides sequential automated testing to ensure all userbot commands remain functional after changes.

---

## Setup & Installation

### 1. Prerequisites
- Python 3.10+
- A Telegram account with API access.

### 2. Obtain Required Credentials

You will need four main credentials to put into your `.env` file:

- `WIZARD_BOT_TOKEN`: The token for your Wizard Bot. Get it from [@BotFather](https://t.me/BotFather) on Telegram.
- `ADMIN_CHAT_ID`: Your Telegram chat ID. Get it by sending a message to [@userinfobot](https://t.me/userinfobot).
- `API_ID` and `API_HASH`: Your Telegram API credentials. Get them from [my.telegram.org](https://my.telegram.org) under "API development tools."

### 3. Project Configuration

1. **Clone this repository:**
   ```bash
   git clone <YOUR_REPOSITORY_URL>
   cd little-ghost
   ```

2. **Create the `.env` file:**
   Copy `.env.example` to `.env` and fill in your credentials.
   ```bash
   cp .env.example .env
   ```

3. **Grant execution permissions to the script:**
   ```bash
   chmod +x scripts/dev.sh
   ```

---

## How to Run

This project is designed to be run with a script that handles dependency installation, service execution (Wizard and Userbot), and logging.

### Run Wizard and Userbot Concurrently

**Run the development environment:**
```bash
./scripts/dev.sh
```

The script performs the following actions:
1. Creates a `.venv` if it doesn't exist and ensures `pip` is available.
2. Installs dependencies from `requirements.txt` into the `.venv`.
3. Checks for existing running instances using PID files.
4. Runs the **Wizard Bot** and **Userbot Service** in parallel with different PIDs.
5. Displays combined logs (`logs/wizard.log`, `logs/userbot.log`).

Press `Ctrl+C` at any time, and the script will stop both services cleanly.

---

## Usage Guide

### Step 1: Start the Wizard Bot
- Open a chat with your Wizard Bot on Telegram.
- Send the `/start` or `/menu` command at any time to bring up the main keyboard.

### Step 2: Create or Add a Userbot
- **🧙‍♂️ Create Userbot**: Follow the OTP/QR flow directly from the wizard. You can enter your phone number manually or use the "📱 Share Phone Number" button.
- **🪄 Token Login**: Send an existing Telethon Session String. The wizard saves it to SQLite, and the userbot is ready to go.

### Step 3: Manage the Userbot
1. Select **"🛠️ Manage Userbot"** and choose the userbot you want to manage.
2. The reply keyboard will show command buttons: `🤖 Auto Reply`, `👀 Watcher`, `📢 Broadcast`, `📊 Job Status`, `⛔ Stop Jobs`, `🆘 Help`, and navigation options.
3. Each button starts a short conversation to guide you step-by-step.
4. The wizard saves instructions to the `tasks` table, and the Userbot Service executes them asynchronously.

---

## Project Structure
```
little-ghost/
├─ services/       # Code for the Wizard Bot and Userbot Service
├─ core/           # Core business logic and infrastructure
├─ pkg/            # Shared packages like the logger
├─ data/           # SQLite database and session files
├─ logs/           # Generated log files
├─ pids/           # PID files for running processes
├─ scripts/        # Scripts to run the project
├─ .env            # Configuration file (must be created)
└─ README.md       # This documentation
```

---

## Troubleshooting

- Check the service logs in `logs/wizard.log` and `logs/userbot.log` for error messages.
- User activity logs are stored in `logs/wizard/users/{telegram_userid}.log`.
- If the virtual environment causes issues, delete the `.venv` folder and run `./scripts/dev.sh` again to recreate it.
- If services stop unexpectedly, check the PID files in `pids/` and ensure no zombie processes are left.
  ```bash
  # Check for running processes
  ps aux | grep "services.wizard.main"
  ps aux | grep "services.userbot.main"

  # Terminate if necessary
  pkill -f services.wizard.main
  pkill -f services.userbot.main
  ```