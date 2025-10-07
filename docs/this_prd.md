# Little Ghost — Telegram Userbot (Python/Telethon + SQLite)

## 1. Product Goal
**Objective:** To build _Little Ghost_, a userbot system based on Python + Telethon with two main components: the **Wizard** (interface bot) and the **Userbot** (automated executor).
All data is stored in **SQLite** and **local files**, with optional integration with the **Google Sheets API** to log relevant messages based on keywords.

**Why Python:**
- Mature Telegram library ecosystem (`python-telegram-bot`, `Telethon`).
- Lightweight, easy to configure, and supports async operations and simple logging.

---

## 2. General Architecture
```
┌────────────────────────────┐
│  Little Ghost Framework     │
│  ├─ Wizard Bot (PTB)        │
│  ├─ Userbot (Telethon)      │
│  ├─ Core Modules            │
│  └─ SQLite / JSON / Logs    │
└────────────────────────────┘
                    │
                    ▼
           [Google Sheets API]
```

The Wizard serves as a conversational interface to create, manage, and monitor userbot activities.
The Userbot executes automated commands like **Auto Reply**, **Watcher**, **Broadcast**, and more.

---

## 3. Directory Layout
```
little-ghost/
├─ services/
│  ├─ wizard/           # Interface bot (python-telegram-bot)
│  │  └─ commands/      # Conversation flows per wizard command
│  └─ userbot/          # Automated executor (Telethon)
│     └─ commands/      # Userbot task handlers per command
├─ core/
│  ├─ domain/           # Domain entities & rules
│  ├─ usecases/         # Business logic (jobs, auto-reply, watcher, broadcast)
│  └─ infra/            # Adapters (telethon, sheets, storage)
├─ pkg/logger.py        # Main logger
├─ data/                # SQLite + runtime configuration
├─ credentials/         # Google API credentials
├─ scripts/dev.sh       # Run wizard & userbot concurrently
├─ .env                 # Environment configuration
└─ docs/                # Documentation
```

---

## 4. Key Concepts & Features

### 4.1 Wizard Bot
- Library: `python-telegram-bot` (polling mode).
- Token and configuration are stored in `.env` (`WIZARD_BOT_TOKEN`, `ADMIN_CHAT_ID`).
- Only `ADMIN_CHAT_ID` can access the wizard.

**Main Menu (Horizontal ReplyKeyboardMarkup):**
```
[ Create Userbot | Token Login ]
[ Manage Userbot | Admin Settings ]
[ Help ]
```

#### 4.1.1 Create Userbot
- The wizard guides the user through a new login process using **OTP / QR login** directly from the chat interface.
- Users can enter their phone number manually or use the **"📱 Share Phone Number"** button (`KeyboardButton(request_contact=True)`) to share it automatically.
- If the account has **Two-Factor Authentication (2FA)** enabled, the wizard will prompt for the additional password.
- When entering the OTP, the user can type with spaces (e.g., 4 5 6 7 8 9) for convenience, and the wizard will process it as 456789 in the background.
- `API_ID` and `API_HASH` values are taken from the `.env` file.
- After a successful login, the wizard displays and saves the generated **session string** to SQLite.
- This session string is automatically saved and can be reused via the "Token Login" menu.

#### 4.1.2 Token Login
- Used to log in with an existing **session string**.
- The wizard will ask the user to enter the session string, then run the userbot based on it.
- Once successful, the userbot becomes active and is ready to receive commands from the Wizard or its task system.

#### 4.1.3 Manage Userbot
- This menu displays a list of active userbot commands via `ReplyKeyboardMarkup`. Each button opens a short conversation explaining the next steps (e.g., select scope, enter keywords) to be friendly for new users.
- Available buttons:
  - `🤖 Auto Reply`
  - `👀 Watcher`
  - `📢 Broadcast`
  - `📊 Job Status`
  - `⛔ Stop Jobs`
  - `🆘 Help`
  - `🤖 Choose Userbot`
  - `⬅️ Back`
- The wizard creates a new task in SQLite for each instruction, and the Userbot Service executes it asynchronously.
- The latest status of each task can be monitored via `📊 Job Status`, while `⛔ Stop Jobs` flags a running task for the worker to stop it safely.
- Every conversation always displays a `⬅️ Back` button so the admin can return to the menu at any time without typing a manual command.

#### 4.1.4 Admin Settings
- Provides advanced utilities, currently consisting of:
  - `🧪 Automated Testing` — the wizard asks which userbot to test, then triggers an `auto_test` task.
    - The task runs all main commands sequentially (Sync Groups → Auto Reply → Watcher → Broadcast) in a safe/dry-run mode.
    - All steps, results, and task snapshots are recorded in `logs/userbot/jobs/auto_test/<process_id>.log` and `tasks.details.auto_test`.
  - `👷 Manage Userbot (WIP)` — a maintenance sub-menu.
    - Currently available is `📂 Sync Users Groups`: the wizard queues a sync task for all userbots. The Userbot Service updates the `groups` table (complete with `group_type` and `username`) and writes an incremental log to `logs/admin/sync_<telegram_userid>.log` (only new entries based on `telegram_group_id`).
    - This menu will become the hub for advanced features like per-userbot DB cleaning, granular log pulling, warnings, etc.
- The admin menu always displays a custom keyboard so the admin can quickly switch between utilities or return to the main menu.

---

### 4.2 Userbot
- Library: `Telethon`.
- Handles async tasks in parallel: Auto Reply, Watcher, Broadcast, Get Groups/Channels.
- Each task has a unique `process_id` for monitoring and control via the Wizard.
- Job status data is stored in SQLite (`data/userbots.db`).

---

## 5. Storage & Data
- **Database:** `data/userbots.db`
  Contains tables:
  - `userbots`: userbot profiles (username, string_session, status)
  - `tasks`: list of active tasks (process_id, command, status, start_time)
  - `config`: keywords, target lists, default settings
  - `groups`: list of connected groups/channels
- **Checkpoint:** `data/state.json` to avoid message duplication.
- **Logs:** `logs/{service}/{context}/{date}.log` records all activities and errors (including FloodWait / rate limits).

---

## 6. Command & Workflow

### 6.1 🤖 Auto Reply
- The wizard guides the admin to select a target scope via buttons: `🌐 All Groups`, `📡 All Channels`, or `🎯 Specific Targets` (entering chat IDs without the `-100` prefix, with a brief tutorial on how to get the ID).
- After that, the admin enters trigger keywords. A format like `need without nut` automatically adds an exclusion. The wizard also provides a button to add exclusions manually or skip it.
- The final step is to write the reply message. The `⬅️ Back` button is always visible so the admin can return to the menu at any time.
- The userbot attaches a `Telethon.events.NewMessage` handler per target, records each hit in `details.replied_count`, and saves the log to `logs/userbot/jobs/auto_reply/<process_id>.log`.

### 6.2 👀 Watcher
- The Watcher menu now offers two actions: `➕ Create Watcher` to create a new rule and `📜 Watcher Logs` to display a summary of the 8 most recent watcher tasks (status, total hits, Google Sheets and system error notes).
- The watcher creation flow is similar to Auto Reply: select target scope, define keywords, and optionally add exclusions.
- The wizard then asks for the logging destination (`🗂 Local Log` or `📄 Google Sheets`) and a watcher label. If Sheets is selected, the admin enters the sheet ID/URL; the wizard also displays a short tutorial:
  1. Enable the Google Sheets API & create a Service Account.
  2. Save the JSON credentials to `credentials/service_account.json` (an icon is provided in the project structure) — this folder is git-ignored, so it's safe to place local files there.
  3. Share the sheet with the service account's email with editor access.
- If the credential file name is different, the system automatically uses the only `.json` file in the `credentials/` folder or uses the `GOOGLE_SHEETS_CREDENTIAL_FILE` env var to point to a specific file.
- Configuration data (keywords, exclusions, destination) is stored in the `details` column; when Sheets mode is active, the backend adds `destination.resolved` metadata with the spreadsheet and worksheet title for easy auditing from the log menu.
- The userbot monitors new messages according to the rules and logs matches to `logs/userbot/jobs/watcher/<process_id>.log` complete with metadata (chat id, message content).
- For Google Sheets mode, the system ensures the header row (`sender_username`, `sender_telegram_id`, `message`, `group_name`, `timestamp_utc`, `process_id`, `label`, `chat_id`, `message_id`) is created automatically if the sheet is empty. Each hit writes this data; if a failure occurs (credentials, permissions, sheet not found, etc.), the job status changes to error and the `details.last_sheet_error` column stores the source message.

### 6.3 📢 Broadcast
- The broadcast conversation is divided into several guided steps:
  1. Choose content mode (`📝 Manual Message` or `🔁 Forward Message`). Manual mode supports text and media (image/document + caption); the wizard downloads the file to `data/uploads/` so the userbot can resend it. Forward mode asks the admin to forward the original message to be broadcast.
  2. Set a schedule (`▶️ Send Now`, `⏳ Delay`, `🔁 Interval`). For delay/interval, the wizard asks for the number of minutes (minimum 1) while warning about FloodWait risks.
  3. Select target scope (`All Groups`, `All Channels`, or `Specific Targets` with a tutorial for IDs without `-100`).
- The task details store the content structure (`text`, `photo`, `document`, `forward`) and schedule so the userbot can use `send_message`, `send_file`, or `forward_messages` as needed. The last delivery information is stored in the `details` column and the log `logs/userbot/jobs/broadcast/<process_id>.log`.

### 6.4 📂 Sync Users Groups (Admin)
- Available in the `⚙️ Admin Settings` → `👷 Manage Userbot (WIP)` menu.
- The wizard queues a `sync_groups` task for each userbot. The Userbot Service scans Telethon dialogs and updates the `groups` table (including `group_type`, `username`, `access_hash`).
- The sync result is also logged to `logs/admin/sync_<telegram_userid>.log` (JSONL format). When re-run, the system only adds new entries based on `telegram_group_id`. Progress is written every 50 entries (`⏳ page x/y`) for easy monitoring.

### 6.5 📊 Job Status
- Presents a summary of the 15 most recent tasks (command, status, process id) directly from the `tasks` table.
- Additional information like broadcast schedules or watcher labels is pulled from the `details` column so the admin can quickly see the latest configuration.

### 6.6 ⛔ Stop Jobs
- The wizard marks a task as `status = 'stopped'` based on the admin's choice; the main userbot loop reads this status and calls `command.stop` to stop the associated handler/loop.
- The task details are stamped with `stopped_at` for auditing.

### 6.7 🆘 Help
- Displays a summary of the `Manage Userbot` buttons, tips on re-running /menu, and the location of conversation logs (`logs/wizard/users/<telegram_id>.log`).

### 6.8 Admin Auto Test
- The `auto_test` task runs the sequence: Sync Groups → Auto Reply → Watcher → Broadcast in dry-run mode. For broadcast, the content is sent as a manual message so the latest flow is still validated.
- Each step is logged to `details.auto_test` and to the file `logs/userbot/jobs/auto_test/<process_id>.log` to facilitate regression debugging.

---

## 7. Logging & Auditing
- All wizard and userbot activities are logged.
- Every admin conversation with the wizard is saved to `logs/wizard/users/{telegram_userid}-{timestamp}.log`.
- FloodWait, Timeout, and Limit errors are logged in `logs/userbot/errors/{telegram_id}-{date}.log`.
- Terminal and background process logs are also saved automatically.
- Format: `[timestamp] [level] [service] [context] message`.
- PID management system prevents multiple instances with PID files in `pids/{service}.pid`.

---

## 8. Security & Privacy
- Wizard access is restricted by `ADMIN_CHAT_ID`.
- Session strings can be encrypted with `SESSION_SECRET`.
- Sensitive data is never sent out except to the Google Sheets API.

---

## 9. Reliability & Job Handling
- Async jobs can be stopped safely.
- FloodWait and rate limits are handled with a backoff retry mechanism.
- Task management is SQLite-based for synchronization.

---

## 10. Wizard Menu Summary

| Main Menu | Function |
|---|---|
| **Create Userbot** | Login via OTP/QR, generating a new session string |
| **Token Login** | Login using an existing session string |
| **Manage Userbot** | Display and manage all userbot commands |
| **Admin Settings** | Advanced settings (details to follow) |
| **Help** | Complete guide to using Little Ghost |

---

_"Little Ghost" is a flexible, quiet, and robust userbot — ready to work behind the scenes without constant supervision._