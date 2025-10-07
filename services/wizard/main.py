import os
import sys
import logging
import sqlite3
import re
from datetime import datetime
from pathlib import Path
from textwrap import dedent

from dotenv import load_dotenv
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton
from telegram.constants import ParseMode
from telegram.error import Conflict
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from telethon import TelegramClient, errors
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError

from .commands import build_command_registry
from .commands.base import CommandDependencies, WizardCommand
from .commands.utils import create_task as enqueue_task, parse_custom_target_ids

# Muat environment variables dari .env di root proyek
load_dotenv()

# Impor modul proyek (sekarang berfungsi karena dijalankan dari root)
from pkg.logger import setup_logger
from pkg.pid_manager import PIDManager
from core.infra.database import get_db_connection, initialize_database

# Setup logger
logger = setup_logger('wizard', 'main')

# Ambil konfigurasi dari environment
WIZARD_BOT_TOKEN = os.getenv('WIZARD_BOT_TOKEN')
ADMIN_CHAT_ID_RAW = os.getenv('ADMIN_CHAT_ID')
API_ID_RAW = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')

missing_vars = [name for name, value in {
    'WIZARD_BOT_TOKEN': WIZARD_BOT_TOKEN,
    'ADMIN_CHAT_ID': ADMIN_CHAT_ID_RAW,
    'API_ID': API_ID_RAW,
    'API_HASH': API_HASH,
}.items() if not value]

if missing_vars:
    logger.critical(f"Variabel environment wajib belum diisi: {', '.join(missing_vars)}")
    sys.exit(1)

try:
    ADMIN_CHAT_ID = int(ADMIN_CHAT_ID_RAW)
except (TypeError, ValueError):
    logger.critical("ADMIN_CHAT_ID harus berupa angka valid.")
    sys.exit(1)

try:
    API_ID = int(API_ID_RAW)
except (TypeError, ValueError):
    logger.critical("API_ID harus berupa angka valid.")
    sys.exit(1)

ASK_SESSION_STRING, CREATE_PHONE, CREATE_CODE, CREATE_PASSWORD = range(4)

USER_LOG_DIR = Path("logs/wizard/users")


def log_user_event(user_id: int | None, role: str, message: str) -> None:
    if user_id is None:
        return
    try:
        USER_LOG_DIR.mkdir(parents=True, exist_ok=True)
        # Format filename: {telegram_userid}.log
        log_file_path = USER_LOG_DIR / f"{user_id}.log"
        timestamp_log = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Write log entry
        with log_file_path.open("a", encoding="utf-8") as fh:
            fh.write(f"[{timestamp_log}] [{role}] {message}\n")
    except Exception as exc:
        logger.error("Gagal menulis log pengguna %s: %s", user_id, exc)


def log_incoming(update: Update, content: str) -> None:
    user = update.effective_user
    log_user_event(user.id if user else None, "USER", content)


def log_outgoing(user_id: int, content: str) -> None:
    log_user_event(user_id, "WIZARD", content)


def _chunk_markdown(text: str, limit: int = 3500) -> list[str]:
    lines = text.split("\n")
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in lines:
        line_with_break = line + "\n"
        if current_len + len(line_with_break) > limit and current:
            chunks.append("".join(current).rstrip())
            current = [line_with_break]
            current_len = len(line_with_break)
        else:
            current.append(line_with_break)
            current_len += len(line_with_break)

    if current:
        chunks.append("".join(current).rstrip())

    return chunks or [text]


async def reply_markdown(message, text: str, reply_markup=None) -> None:
    chunks = _chunk_markdown(text)
    markup = reply_markup
    for chunk in chunks:
        await message.reply_text(chunk, reply_markup=markup, parse_mode=ParseMode.MARKDOWN)
        markup = None


async def _cleanup_create_session(context: ContextTypes.DEFAULT_TYPE) -> None:
    client = context.user_data.pop('create_client', None)
    if client:
        try:
            await client.disconnect()
        except Exception as exc:
            logger.warning("Gagal memutus koneksi client Telethon saat cleanup: %s", exc)
    context.user_data.pop('create_phone', None)
    context.user_data.pop('create_need_password', None)


command_dependencies = CommandDependencies(
    logger=logger,
    log_outgoing=log_outgoing,
    log_incoming=log_incoming,
    back_button="⬅️ Back",
)

COMMAND_REGISTRY = build_command_registry(command_dependencies)
COMMAND_BY_SLUG = {command.slug: command for command in COMMAND_REGISTRY.values()}
LABEL_TO_COMMAND = {command.label: command for command in COMMAND_REGISTRY.values()}

CMD_AUTO_REPLY = COMMAND_BY_SLUG['auto_reply'].label
CMD_WATCHER = COMMAND_BY_SLUG['watcher'].label
CMD_BROADCAST = COMMAND_BY_SLUG['broadcast'].label
CMD_INFO = COMMAND_BY_SLUG['info'].label
CMD_STOP = COMMAND_BY_SLUG['stop_job'].label
CMD_HELP = COMMAND_BY_SLUG['manage_help'].label

CMD_CHOOSE_USERBOT = "🤖 Choose Userbot"
CMD_BACK_TO_MENU = "⬅️ Back"

MANAGE_COMMAND_KEYBOARD = [
    [CMD_AUTO_REPLY, CMD_WATCHER],
    [CMD_BROADCAST, CMD_INFO],
    [CMD_STOP, CMD_HELP],
    [CMD_CHOOSE_USERBOT],
    [CMD_BACK_TO_MENU],
]

MANAGE_COMMAND_MARKUP = ReplyKeyboardMarkup(MANAGE_COMMAND_KEYBOARD, resize_keyboard=True)

ADMIN_MENU_TEST = "🧪 Automated Testing"
ADMIN_MENU_MANAGE = "👷 Manage Userbot (WIP)"
ADMIN_MENU_BACK = "⬅️ Back to Menu"
ADMIN_MENU_KEYBOARD = [[ADMIN_MENU_TEST, ADMIN_MENU_MANAGE], [ADMIN_MENU_BACK]]
ADMIN_MENU_MARKUP = ReplyKeyboardMarkup(ADMIN_MENU_KEYBOARD, resize_keyboard=True)

AUTO_TEST_SCOPE_ALL = "Test all groups & channels"
AUTO_TEST_SCOPE_CUSTOM = "Test specific groups/channels (enter IDs)"
AUTO_TEST_SCOPE_MARKUP = ReplyKeyboardMarkup(
    [[AUTO_TEST_SCOPE_ALL], [AUTO_TEST_SCOPE_CUSTOM], [ADMIN_MENU_BACK]],
    resize_keyboard=True,
)
AUTO_TEST_ID_INPUT_MARKUP = ReplyKeyboardMarkup([[ADMIN_MENU_BACK]], resize_keyboard=True)

ADMIN_MANAGE_SYNC = "📂 Sync Users Groups"
ADMIN_MANAGE_BACK = "⬅️ Back to Admin"
ADMIN_MANAGE_KEYBOARD = [[ADMIN_MANAGE_SYNC], [ADMIN_MANAGE_BACK]]
ADMIN_MANAGE_MARKUP = ReplyKeyboardMarkup(ADMIN_MANAGE_KEYBOARD, resize_keyboard=True)

MENU_CREATE_USERBOT = "🧙‍♂️ Buat Userbot"
MENU_TOKEN_LOGIN = "🪄 Token Login"
MENU_MANAGE_USERBOT = "🛠️ Kelola Userbot"
MENU_ADMIN_SETTING = "⚙️ Admin Setting"
MENU_HELP = "📚 Bantuan"

MAIN_MENU_KEYBOARD = [
    [MENU_CREATE_USERBOT, MENU_TOKEN_LOGIN],
    [MENU_MANAGE_USERBOT, MENU_ADMIN_SETTING],
    [MENU_HELP],
]
MAIN_MENU_MARKUP = ReplyKeyboardMarkup(MAIN_MENU_KEYBOARD, resize_keyboard=True)

HELP_TEXT = dedent(
    """
    ✨ *Panduan Singkat Little Ghost Wizard*

    • 🧙‍♂️ *Buat Userbot* — login OTP/QR langsung dari wizard untuk menghasilkan string session baru.
    • 🪄 *Token Login* — simpan String Session Telethon yang sudah Anda miliki agar userbot siap dipakai.
    • 🛠️ *Kelola Userbot* — pilih userbot dan jalankan perintah (Auto Reply, Watcher, Broadcast, dll.).
    • ⚙️ *Admin Setting* — jalankan pengujian otomatis untuk memastikan semua perintah berjalan.

    Kirim /menu kapan saja untuk menampilkan keyboard utama.
    """
).strip()

async def _ensure_admin(update: Update) -> bool:
    user = update.effective_user
    if user.id != ADMIN_CHAT_ID:
        message = "Anda tidak diizinkan menggunakan bot ini."
        if update.message:
            await update.message.reply_text(message)
            log_outgoing(user.id, message)
        elif update.callback_query:
            await update.callback_query.answer(message, show_alert=True)
            log_outgoing(user.id, message)
        return False
    return True


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_incoming(update, update.message.text if update.message and update.message.text else "/start")
    if not await _ensure_admin(update):
        return

    response = "🌟 Selamat datang di Little Ghost Wizard! ✨\n\nPilih menu di bawah ini untuk mulai mengelola userbot Anda. 🚀"
    await update.message.reply_text(response, reply_markup=MAIN_MENU_MARKUP)
    log_outgoing(update.effective_user.id, response)


async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_incoming(update, update.message.text if update.message and update.message.text else "/menu")
    if not await _ensure_admin(update):
        return
    response = "📋 Menu utama tampil kembali. Silakan pilih opsi yang Anda inginkan. 😊"
    await update.message.reply_text(response, reply_markup=MAIN_MENU_MARKUP)
    log_outgoing(update.effective_user.id, response)


async def create_userbot_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    log_incoming(update, update.message.text or MENU_CREATE_USERBOT)
    if not await _ensure_admin(update):
        return ConversationHandler.END

    await _cleanup_create_session(context)

    instructions = dedent(
        """
        🧙‍♂️ *Buat Userbot Baru* ✨

        1. 📝 Masukkan nomor telepon akun Telegram (format internasional, contoh `+628123456789`).
        2. 📱 Atau gunakan tombol "Bagikan Nomor Telepon" di bawah ini untuk otomatis mengisi.
        3. 🔑 Setelah kode OTP diterima, kirimkan ke wizard ini.
        4. 🔒 Jika akun memakai sandi 2FA, wizard akan meminta sandi tersebut.

        Ketik /cancel kapan saja untuk membatalkan proses.
        """
    ).strip()

    # Create keyboard with share phone button
    phone_keyboard = [
        [KeyboardButton("📱 Bagikan Nomor Telepon", request_contact=True)]
    ]
    phone_markup = ReplyKeyboardMarkup(phone_keyboard, resize_keyboard=True, one_time_keyboard=True)

    await update.message.reply_text(instructions, reply_markup=phone_markup, parse_mode=ParseMode.MARKDOWN)
    log_outgoing(update.effective_user.id, instructions)
    return CREATE_PHONE


async def create_userbot_receive_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Check if user shared their contact
    if update.message.contact:
        phone = update.message.contact.phone_number
        log_incoming(update, f"<contact shared: {phone}>")
    else:
        phone = update.message.text.strip()
        log_incoming(update, phone)

    if not await _ensure_admin(update):
        return ConversationHandler.END

    # Remove keyboard after getting phone number
    await update.message.reply_text("🔄 Memproses nomor telepon...", reply_markup=ReplyKeyboardRemove())

    # Validate phone number
    if not phone or phone is None:
        response = "❌ Nomor telepon tidak valid. Silakan coba lagi. 📱"
        await update.message.reply_text(response)
        log_outgoing(update.effective_user.id, response)
        return CREATE_PHONE

    # Ensure phone number starts with + for contacts shared through Telegram
    if not phone.startswith('+'):
        phone = '+' + phone

    if not phone.startswith('+') or len(phone) < 5:
        response = "❌ Format nomor telepon harus diawali tanda + dan minimal 5 digit. Silakan coba lagi ya. 📱"
        await update.message.reply_text(response)
        log_outgoing(update.effective_user.id, response)
        return CREATE_PHONE

    client = TelegramClient(StringSession(), API_ID, API_HASH)
    try:
        await client.connect()
        await client.send_code_request(phone)
    except errors.PhoneNumberInvalidError:
        await client.disconnect()
        response = "❌ Nomor telepon tidak valid. Pastikan formatnya benar dan coba lagi. 📞"
        await update.message.reply_text(response)
        log_outgoing(update.effective_user.id, response)
        return CREATE_PHONE
    except errors.PhoneNumberBannedError:
        await client.disconnect()
        response = "❌ Nomor ini diblokir oleh Telegram. Gunakan nomor lain. 🚫"
        await update.message.reply_text(response)
        log_outgoing(update.effective_user.id, response)
        return ConversationHandler.END
    except Exception as exc:
        await client.disconnect()
        response = f"❌ Gagal mengirim kode OTP: {exc}. Silakan coba lagi nanti. ⏰"
        await update.message.reply_text(response)
        log_outgoing(update.effective_user.id, response)
        return ConversationHandler.END

    context.user_data['create_client'] = client
    context.user_data['create_phone'] = phone

    response = "✅ Kode OTP sudah dikirim oleh Telegram. Silakan masukkan 5 digit kodenya di sini.\n\n💡 Tips: Anda bisa mengetik dengan spasi (contoh: 4 5 6 7 8 9) untuk memudahkan."
    await update.message.reply_text(response)
    log_outgoing(update.effective_user.id, response)
    return CREATE_CODE


async def _finalize_userbot_creation(update: Update, context: ContextTypes.DEFAULT_TYPE, client: TelegramClient) -> int:
    user = await client.get_me()
    string_session = client.session.save()

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO userbots (telegram_id, username, string_session, status) VALUES (?, ?, ?, ?)",
                (user.id, user.username, string_session, 'inactive')
            )
            userbot_id = cursor.lastrowid
            conn.commit()
            created_msg = "✅ String session baru berhasil dibuat dan disimpan. 🎉"
        except sqlite3.IntegrityError:
            existing = cursor.execute(
                "SELECT id FROM userbots WHERE telegram_id = ? OR string_session = ?",
                (user.id, string_session)
            ).fetchone()
            if existing:
                cursor.execute(
                    "UPDATE userbots SET string_session = ?, username = ?, status = 'inactive', telegram_id = ? WHERE id = ?",
                    (string_session, user.username, user.id, existing['id'])
                )
                conn.commit()
                userbot_id = existing['id']
                created_msg = "✅ String session diperbarui untuk userbot yang sudah ada. 🔄"
            else:
                conn.rollback()
                raise
    finally:
        conn.close()

    response = (
        f"{created_msg}\n\n🔑 String session:\n`{string_session}`\n\n"
        "Gunakan menu 🛠️ Kelola Userbot untuk menjalankan tugas. 🚀"
    )
    await update.message.reply_text(response, reply_markup=MAIN_MENU_MARKUP, parse_mode=ParseMode.MARKDOWN)
    log_outgoing(update.effective_user.id, response)

    await _cleanup_create_session(context)
    return ConversationHandler.END


async def create_userbot_receive_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    code = update.message.text.strip()
    log_incoming(update, code)

    if not await _ensure_admin(update):
        return ConversationHandler.END

    client: TelegramClient | None = context.user_data.get('create_client')
    phone = context.user_data.get('create_phone')

    if client is None or phone is None:
        response = "❌ Sesi pembuatan userbot tidak ditemukan. Silakan mulai ulang melalui menu. 🔄"
        await update.message.reply_text(response, reply_markup=MAIN_MENU_MARKUP)
        log_outgoing(update.effective_user.id, response)
        return ConversationHandler.END

    # Remove spaces from OTP code if present (e.g., "4 5 6 7 8 9" becomes "456789")
    processed_code = code.replace(" ", "")
    
    try:
        await client.sign_in(phone=phone, code=processed_code)
    except SessionPasswordNeededError:
        context.user_data['create_need_password'] = True
        response = "🔒 Akun ini mengaktifkan sandi 2FA. Silakan masukkan sandi tersebut."
        await update.message.reply_text(response)
        log_outgoing(update.effective_user.id, response)
        return CREATE_PASSWORD
    except errors.PhoneCodeInvalidError:
        response = "❌ Kode OTP salah. Silakan masukkan ulang dengan benar. 🔑"
        await update.message.reply_text(response)
        log_outgoing(update.effective_user.id, response)
        return CREATE_CODE
    except Exception as exc:
        response = f"❌ Gagal memverifikasi kode: {exc}. Silakan coba lagi nanti. ⏰"
        await update.message.reply_text(response, reply_markup=MAIN_MENU_MARKUP)
        log_outgoing(update.effective_user.id, response)
        await _cleanup_create_session(context)
        return ConversationHandler.END

    return await _finalize_userbot_creation(update, context, client)


async def create_userbot_receive_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    password = update.message.text.strip()
    log_incoming(update, "<password redacted>")

    if not await _ensure_admin(update):
        return ConversationHandler.END

    client: TelegramClient | None = context.user_data.get('create_client')
    if client is None:
        response = "❌ Sesi pembuatan userbot tidak ditemukan. Silakan mulai ulang melalui menu. 🔄"
        await update.message.reply_text(response, reply_markup=MAIN_MENU_MARKUP)
        log_outgoing(update.effective_user.id, response)
        return ConversationHandler.END

    try:
        await client.sign_in(password=password)
    except errors.PasswordHashInvalidError:
        response = "❌ Sandi 2FA salah. Silakan coba lagi. 🔒"
        await update.message.reply_text(response)
        log_outgoing(update.effective_user.id, response)
        return CREATE_PASSWORD
    except Exception as exc:
        response = f"❌ Gagal memverifikasi sandi: {exc}. Silakan coba lagi nanti. ⏰"
        await update.message.reply_text(response, reply_markup=MAIN_MENU_MARKUP)
        log_outgoing(update.effective_user.id, response)
        await _cleanup_create_session(context)
        return ConversationHandler.END

    return await _finalize_userbot_creation(update, context, client)


async def show_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_incoming(update, MENU_ADMIN_SETTING)
    if not await _ensure_admin(update):
        return

    context.user_data['admin_active'] = True
    context.user_data['admin_manage_active'] = False
    context.user_data.pop('admin_available_userbots', None)
    _reset_auto_test_context(context)

    message = dedent(
        """
        ⚙️ *Admin Setting*

        • `🧪 Automated Testing` — jalankan alur lengkap (Sync Groups → Auto Reply → Watcher → Broadcast) dalam mode dry-run, pilih cakupan (`Test all groups & channels` atau `Test specific groups/channels`) dan simpan hasilnya ke log.
        • `👷 Manage Userbot (WIP)` — akses utilitas maintenance (sync seluruh grup, pembersihan data, dsb.).
        """
    ).strip()

    await reply_markdown(update.message, message, ADMIN_MENU_MARKUP)
    log_outgoing(update.effective_user.id, message)


def _start_auto_test_task(userbot_id: int, scope: str, targets: list[int] | None) -> tuple[str, int]:
    details = {
        'initiator': 'wizard_auto_test',
        'requested_at': datetime.utcnow().isoformat(),
        'testing_scope': scope,
    }
    if targets is not None:
        details['testing_targets'] = targets
    return enqueue_task(userbot_id, 'auto_test', details)


def _reset_auto_test_context(context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop('admin_auto_test', None)


async def _begin_auto_test_flow(message, context: ContextTypes.DEFAULT_TYPE, selected: dict, user_id: int | None) -> None:
    display_name = _format_userbot_name(selected)
    context.user_data['admin_auto_test'] = {
        'state': 'await_scope',
        'userbot_id': selected['id'],
        'display_name': display_name,
    }
    prompt = (
        "🧪 *Automated Testing*\n"
        f"Pilih cakupan pengujian untuk *{display_name}*.\n"
        "Gunakan tombol di bawah, lalu lanjutkan langkahnya ya."
    )
    await reply_markdown(message, prompt, AUTO_TEST_SCOPE_MARKUP)
    if user_id is not None:
        log_outgoing(user_id, prompt)


async def _handle_admin_auto_test_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    auto_ctx = context.user_data.get('admin_auto_test') or {}
    state = auto_ctx.get('state')
    user_id = update.effective_user.id if update.effective_user else None

    if state == 'await_scope':
        if text == AUTO_TEST_SCOPE_ALL:
            process_id, task_id = _start_auto_test_task(auto_ctx['userbot_id'], 'all', None)
            display_name = auto_ctx.get('display_name', 'Userbot')
            summary = (
                f"Pengujian otomatis dijadwalkan untuk *{display_name}*.\n"
                f"• Task ID: {task_id}\n"
                f"• Process ID: `{process_id}`\n"
                "• Scope: Semua grup & channel yang tersinkron\n"
                "Lihat hasil di `logs/userbot/jobs/auto_test/{process_id}.log`."
            )
            _reset_auto_test_context(context)
            await reply_markdown(update.message, summary, ADMIN_MENU_MARKUP)
            if user_id is not None:
                log_outgoing(user_id, summary)
            return

        if text == AUTO_TEST_SCOPE_CUSTOM:
            auto_ctx['state'] = 'await_targets'
            context.user_data['admin_auto_test'] = auto_ctx
            prompt = (
                "Ketik ID chat yang mau diuji, pisahkan dengan koma.\n"
                "• Boleh pakai format biasa (`12345`) atau lengkap (`-10012345`).\n"
                "• Contoh: `123456789,987654321`"
            )
            await reply_markdown(update.message, prompt, AUTO_TEST_ID_INPUT_MARKUP)
            if user_id is not None:
                log_outgoing(user_id, prompt)
            return

        reminder = "Gunakan tombol yang tersedia untuk memilih cakupan pengujian ya."
        await reply_markdown(update.message, reminder, AUTO_TEST_SCOPE_MARKUP)
        if user_id is not None:
            log_outgoing(user_id, reminder)
        return

    if state == 'await_targets':
        try:
            targets = parse_custom_target_ids(text)
        except ValueError as exc:
            reminder = f"❌ {exc}"
            await reply_markdown(update.message, reminder, AUTO_TEST_ID_INPUT_MARKUP)
            if user_id is not None:
                log_outgoing(user_id, reminder)
            return

        if not targets:
            reminder = "❌ Masukkan minimal satu ID chat untuk diuji."
            await reply_markdown(update.message, reminder, AUTO_TEST_ID_INPUT_MARKUP)
            if user_id is not None:
                log_outgoing(user_id, reminder)
            return

        process_id, task_id = _start_auto_test_task(auto_ctx['userbot_id'], 'custom', targets)
        display_name = auto_ctx.get('display_name', 'Userbot')
        summary = (
            f"Pengujian otomatis dijadwalkan untuk *{display_name}*.\n"
            f"• Task ID: {task_id}\n"
            f"• Process ID: `{process_id}`\n"
            f"• Scope: Custom ({len(targets)} chat)\n"
            "Lihat hasil di `logs/userbot/jobs/auto_test/{process_id}.log`."
        )
        _reset_auto_test_context(context)
        await reply_markdown(update.message, summary, ADMIN_MENU_MARKUP)
        if user_id is not None:
            log_outgoing(user_id, summary)
        return

    reminder = "Sesi automated testing direset. Silakan mulai lagi dari menu Admin."
    _reset_auto_test_context(context)
    await reply_markdown(update.message, reminder, ADMIN_MENU_MARKUP)
    if user_id is not None:
        log_outgoing(user_id, reminder)


async def handle_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    log_incoming(update, text)
    if not await _ensure_admin(update):
        return

    context.user_data['admin_active'] = True

    if context.user_data.get('admin_manage_active'):
        await handle_admin_manage_text(update, context)
        return

    auto_ctx = context.user_data.get('admin_auto_test')

    if text == ADMIN_MENU_BACK:
        if auto_ctx:
            _reset_auto_test_context(context)
            response = "Sesi automated testing dibatalkan. Silakan pilih menu Admin lagi."
            await reply_markdown(update.message, response, ADMIN_MENU_MARKUP)
            log_outgoing(update.effective_user.id, response)
            return
        context.user_data['admin_active'] = False
        response = "Kembali ke menu utama."
        await reply_markdown(update.message, response, MAIN_MENU_MARKUP)
        log_outgoing(update.effective_user.id, response)
        return

    if auto_ctx:
        await _handle_admin_auto_test_flow(update, context, text)
        return

    if text == ADMIN_MENU_MANAGE:
        _reset_auto_test_context(context)
        await show_admin_manage_menu(update, context)
        return

    if text != ADMIN_MENU_TEST:
        reminder = "Gunakan tombol yang tersedia pada menu Admin untuk melanjutkan."
        await reply_markdown(update.message, reminder, ADMIN_MENU_MARKUP)
        log_outgoing(update.effective_user.id, reminder)
        return

    userbots = _fetch_userbots()
    if not userbots:
        response = "Belum ada userbot yang bisa diuji. Tambahkan string session terlebih dahulu."
        await reply_markdown(update.message, response, ADMIN_MENU_MARKUP)
        log_outgoing(update.effective_user.id, response)
        return

    if len(userbots) == 1:
        selected = userbots[0]
        await _begin_auto_test_flow(update.message, context, selected, update.effective_user.id)
        return

    context.user_data['admin_available_userbots'] = userbots
    keyboard = [
        [InlineKeyboardButton(f"🤖 {_format_userbot_name(row)} ({row['status']})", callback_data=f"admin_test_{row['id']}")]
        for row in userbots
    ]

    prompt = "Pilih userbot yang ingin diuji:" 
    await reply_markdown(update.message, prompt, InlineKeyboardMarkup(keyboard))
    log_outgoing(update.effective_user.id, prompt)


async def handle_admin_userbot_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    log_user_event(query.from_user.id, "USER", f"admin_test_select:{query.data}")

    context.user_data['admin_active'] = True

    try:
        userbot_id = int(query.data.split('_')[-1])
    except (IndexError, ValueError):
        await query.edit_message_text("Pilihan tidak valid. Silakan coba lagi.")
        return

    available = context.user_data.get('admin_available_userbots') or _fetch_userbots()
    context.user_data['admin_available_userbots'] = available
    selected = next((item for item in available if item['id'] == userbot_id), None)

    if selected is None:
        await query.edit_message_text("Userbot tidak ditemukan. Muat ulang menu Admin Setting.")
        return

    await query.edit_message_text("Pilih cakupan pengujian melalui tombol di bawah ini.")
    await _begin_auto_test_flow(query.message, context, selected, query.from_user.id)


async def show_admin_manage_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data['admin_manage_active'] = True
    context.user_data.pop('admin_available_userbots', None)

    message = dedent(
        """
        👷 *Manage Userbot (WIP)*

        • `📂 Sync Users Groups` — sinkronkan seluruh grup/kanal dari setiap userbot dan tulis hasilnya ke `logs/admin/sync_<telegram_id>.log`.\n"
        "• Fitur lanjutan lain (clean DB, warn, ambil log, dsb.) akan menyusul.
        """
    ).strip()

    await reply_markdown(update.message, message, ADMIN_MANAGE_MARKUP)
    log_outgoing(update.effective_user.id, message)


async def handle_admin_manage_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text.strip()

    if text == ADMIN_MANAGE_BACK:
        context.user_data['admin_manage_active'] = False
        await show_admin_menu(update, context)
        return

    if text == ADMIN_MANAGE_SYNC:
        await start_sync_users_groups(update, context)
        return

    reminder = "Gunakan tombol pada menu Manage Userbot untuk memilih aksi."
    await reply_markdown(update.message, reminder, ADMIN_MANAGE_MARKUP)
    log_outgoing(update.effective_user.id, reminder)


async def start_sync_users_groups(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    userbots = _fetch_userbots()
    if not userbots:
        message = "Belum ada userbot yang dapat disinkronkan. Tambahkan string session terlebih dahulu."
        await reply_markdown(update.message, message, ADMIN_MANAGE_MARKUP)
        log_outgoing(update.effective_user.id, message)
        return

    enqueued_lines: list[str] = []
    for bot in userbots:
        process_id, task_id = enqueue_task(
            bot['id'],
            'sync_groups',
            {
                'initiator': 'admin_sync_all',
                'requested_at': datetime.utcnow().isoformat(),
            },
        )
        display_name = _format_userbot_name(bot)
        enqueued_lines.append(f"• {display_name} — Task `{task_id}` / Process `{process_id}`")

    summary = (
        "📂 Sinkronisasi grup/kanal dijalankan untuk seluruh userbot.\n"
        "Periksa menu 📊 Job Status atau log `logs/admin/sync_<telegram_id>.log` setelah proses selesai.\n\n"
        + "\n".join(enqueued_lines)
    )

    await reply_markdown(update.message, summary, ADMIN_MANAGE_MARKUP)
    log_outgoing(update.effective_user.id, summary)


async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_incoming(update, update.message.text if update.message and update.message.text else MENU_HELP)
    if not await _ensure_admin(update):
        return
    await update.message.reply_text(HELP_TEXT, reply_markup=MAIN_MENU_MARKUP, parse_mode=ParseMode.MARKDOWN)
    log_outgoing(update.effective_user.id, HELP_TEXT)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    log_incoming(update, update.message.text if update.message and update.message.text else "/cancel")
    await _cleanup_create_session(context)
    context.user_data.pop('active_command_slug', None)
    context.user_data.pop('selected_userbot_id', None)
    context.user_data.pop('manage_userbot_display', None)
    context.user_data.pop('admin_available_userbots', None)
    context.user_data.pop('manage_active', None)
    context.user_data.pop('admin_active', None)
    context.user_data.pop('admin_manage_active', None)
    if update.message:
        message = "❌ Operasi dibatalkan. Kembali ke menu utama. 👋"
        await update.message.reply_text(message, reply_markup=MAIN_MENU_MARKUP)
        log_outgoing(update.effective_user.id, message)
    return ConversationHandler.END


async def handle_unknown_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_incoming(update, update.message.text if update.message and update.message.text else "<unknown>")
    if not await _ensure_admin(update):
        return
    message = "❓ Perintah belum dikenali. Gunakan tombol yang tersedia pada keyboard utama ya. 🙂"
    await update.message.reply_text(message, reply_markup=MAIN_MENU_MARKUP)
    log_outgoing(update.effective_user.id, message)


async def handle_application_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = context.error
    if isinstance(error, Conflict):
        logger.critical("Wizard menerima konflik polling: %s", error)
        await context.application.stop()
        return

    logger.exception("Terjadi error yang belum tertangani: %s", error)


async def handle_menu_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    if text in {MENU_CREATE_USERBOT, MENU_TOKEN_LOGIN}:
        return

    if text == MENU_MANAGE_USERBOT:
        await open_manage_menu(update, context)
        return

    if text == MENU_ADMIN_SETTING:
        await show_admin_menu(update, context)
        return

    if text == MENU_HELP:
        await show_help(update, context)
        return

    if context.user_data.get('active_command_slug'):
        await handle_manage_text(update, context)
        return

    if text in LABEL_TO_COMMAND or text in {CMD_CHOOSE_USERBOT, CMD_BACK_TO_MENU} or context.user_data.get('manage_active'):
        await handle_manage_text(update, context)
        return

    if context.user_data.get('admin_active') or text in {ADMIN_MENU_TEST, ADMIN_MENU_BACK}:
        await handle_admin_text(update, context)
        return

    await handle_unknown_menu(update, context)

async def token_login_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    log_incoming(update, update.message.text if update.message and update.message.text else MENU_TOKEN_LOGIN)
    if not await _ensure_admin(update):
        return ConversationHandler.END

    instructions = dedent(
        """
        🪄 *Token Login*

        Kirim String Session Telethon Anda di sini. Pastikan:
        • Hanya kirim melalui chat ini (bersifat rahasia).
        • Jangan sisipkan spasi tambahan.
        • Ketik /cancel bila ingin membatalkan.
        """
    ).strip()

    await update.message.reply_text(instructions, reply_markup=ReplyKeyboardRemove(), parse_mode=ParseMode.MARKDOWN)
    log_outgoing(update.effective_user.id, instructions)
    return ASK_SESSION_STRING

async def receive_session_string(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    session_string = update.message.text.strip()
    log_incoming(update, "<string session>")

    if session_string.lower() in {"", "batal", "/cancel"}:
        message = "Penyimpanan dibatalkan. Kembali ke menu utama."
        await update.message.reply_text(message, reply_markup=MAIN_MENU_MARKUP)
        log_outgoing(update.effective_user.id, message)
        return ConversationHandler.END

    try:
        conn = get_db_connection()
        conn.execute("INSERT INTO userbots (string_session, status) VALUES (?, ?)", (session_string, 'inactive'))
        conn.commit()
        logger.info("String session baru disimpan lewat wizard.")
        message = "String session berhasil disimpan! 🎉\nGunakan menu 🛠️ Kelola Userbot untuk menjalankan tugas."
        await update.message.reply_text(message, reply_markup=MAIN_MENU_MARKUP)
        log_outgoing(update.effective_user.id, message)
    except sqlite3.IntegrityError:
        message = "Gagal menyimpan: string session ini sudah terdaftar. Coba gunakan string lain."
        await update.message.reply_text(message, reply_markup=MAIN_MENU_MARKUP)
        log_outgoing(update.effective_user.id, message)
    except Exception as e:
        logger.error(f"Error saat menyimpan string session: {e}")
        message = "Terjadi kesalahan saat menyimpan string session. Cek log wizard untuk detailnya."
        await update.message.reply_text(message, reply_markup=MAIN_MENU_MARKUP)
        log_outgoing(update.effective_user.id, message)
    finally:
        if 'conn' in locals(): conn.close()
    return ConversationHandler.END

def _fetch_userbots() -> list[dict]:
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT id, username, status FROM userbots ORDER BY id"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def _format_userbot_name(userbot: dict) -> str:
    username = userbot.get('username')
    return username or f"Userbot #{userbot['id']}"


def _get_selected_userbot(context: ContextTypes.DEFAULT_TYPE) -> dict | None:
    selected_id = context.user_data.get('selected_userbot_id')
    available: list[dict] = context.user_data.get('available_userbots') or []
    return next((bot for bot in available if bot['id'] == selected_id), None)


async def open_manage_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    log_incoming(update, update.message.text if update.message and update.message.text else MENU_MANAGE_USERBOT)
    if not await _ensure_admin(update):
        return

    message = update.effective_message
    if message is None:
        return

    userbots = _fetch_userbots()
    context.user_data['available_userbots'] = userbots
    context.user_data.pop('active_command_slug', None)
    for command in COMMAND_REGISTRY.values():
        command.reset(context)

    if not userbots:
        response = (
            "Belum ada userbot tersimpan. Tambahkan string session melalui menu 🪄 Token Login "
            "atau buat sesi baru lewat menu 🧙‍♂️ Buat Userbot."
        )
        await reply_markdown(message, response, MAIN_MENU_MARKUP)
        log_outgoing(update.effective_user.id, response)
        context.user_data['manage_active'] = False
        return

    selected = _get_selected_userbot(context)
    if not selected and len(userbots) == 1:
        selected = userbots[0]
        context.user_data['selected_userbot_id'] = selected['id']

    header = "🛠️ *Userbot Control*"
    if selected:
        display_name = _format_userbot_name(selected)
        context.user_data['manage_userbot_display'] = display_name
        summary = f"Mengelola: *{display_name}* ({selected['status']})."
    else:
        summary = "Belum ada userbot yang dipilih. Tekan `🤖 Choose Userbot` terlebih dahulu."

    body = (
        "Pilih perintah dari keyboard di bawah atau ketik langsung nama perintahnya.\n"
        "Setiap perintah akan memandu langkah demi langkah."
    )

    response = f"{header}\n{summary}\n\n{body}"
    await reply_markdown(message, response, MANAGE_COMMAND_MARKUP)
    log_outgoing(update.effective_user.id, response)
    context.user_data['manage_active'] = True


async def prompt_choose_userbot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return

    userbots = context.user_data.get('available_userbots') or _fetch_userbots()
    context.user_data['available_userbots'] = userbots

    if not userbots:
        response = "Belum ada userbot yang bisa dipilih. Tambahkan string session terlebih dahulu."
        await reply_markdown(message, response, MANAGE_COMMAND_MARKUP)
        log_outgoing(update.effective_user.id, response)
        return

    keyboard = [
        [InlineKeyboardButton(f"🤖 {_format_userbot_name(bot)} ({bot['status']})", callback_data=f"choose_userbot_{bot['id']}")]
        for bot in userbots
    ]

    prompt = "Pilih userbot yang ingin digunakan:" if len(userbots) > 1 else "Konfirmasi userbot yang akan digunakan:"
    await reply_markdown(message, prompt, ReplyKeyboardRemove())
    selection_prompt = "Tap salah satu userbot di bawah:"
    await message.reply_text(selection_prompt, reply_markup=InlineKeyboardMarkup(keyboard))
    log_outgoing(update.effective_user.id, prompt)
    log_outgoing(update.effective_user.id, selection_prompt)


async def handle_choose_userbot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    log_user_event(query.from_user.id, "USER", f"choose_userbot:{query.data}")

    try:
        userbot_id = int(query.data.split('_')[-1])
    except (IndexError, ValueError):
        await query.edit_message_text("Pilihan userbot tidak valid. Coba lagi dari menu.")
        return

    userbots = context.user_data.get('available_userbots') or _fetch_userbots()
    context.user_data['available_userbots'] = userbots
    selected = next((bot for bot in userbots if bot['id'] == userbot_id), None)

    if selected is None:
        await query.edit_message_text("Userbot tidak ditemukan. Muat ulang menu dan coba kembali.")
        return

    display_name = _format_userbot_name(selected)
    context.user_data['selected_userbot_id'] = selected['id']
    context.user_data['manage_userbot_display'] = display_name
    context.user_data['manage_active'] = True

    for command in COMMAND_REGISTRY.values():
        command.reset(context)
    context.user_data.pop('active_command_slug', None)

    confirmation = f"✅ Userbot *{display_name}* siap digunakan."
    await query.edit_message_text(confirmation, parse_mode=ParseMode.MARKDOWN)
    log_outgoing(query.from_user.id, confirmation)

    await reply_markdown(query.message, "Silakan pilih perintah berikutnya.", MANAGE_COMMAND_MARKUP)
    log_outgoing(query.from_user.id, "Silakan pilih perintah berikutnya.")


async def _handle_command_entry(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    command: WizardCommand,
    userbot_id: int | None,
) -> None:
    message = update.message
    if message is None:
        return

    if command.slug != 'manage_help' and userbot_id is None:
        warning = "Pilih userbot terlebih dahulu melalui `🤖 Choose Userbot`."
        await reply_markdown(message, warning, MANAGE_COMMAND_MARKUP)
        log_outgoing(update.effective_user.id, warning)
        await prompt_choose_userbot(update, context)
        return

    target_userbot_id = userbot_id if userbot_id is not None else 0
    entry_message = await command.entry(update, context, target_userbot_id)
    has_follow_up = bool(command.get_state(context))

    if entry_message:
        markup = ReplyKeyboardRemove() if has_follow_up else MANAGE_COMMAND_MARKUP
        await reply_markdown(message, entry_message, markup)
        log_outgoing(update.effective_user.id, entry_message)

    if has_follow_up:
        context.user_data['active_command_slug'] = command.slug
        context.user_data['manage_active'] = True
    else:
        context.user_data.pop('active_command_slug', None)
        command.reset(context)
        context.user_data['manage_active'] = True


async def handle_manage_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    log_incoming(update, text)

    if not await _ensure_admin(update):
        return

    slug = context.user_data.get('active_command_slug')
    if slug:
        await handle_active_command_message(update, context)
        return

    if text == CMD_BACK_TO_MENU:
        context.user_data['manage_active'] = False
        context.user_data.pop('active_command_slug', None)
        response = "Kembali ke menu utama."
        await reply_markdown(update.message, response, MAIN_MENU_MARKUP)
        log_outgoing(update.effective_user.id, response)
        return

    if text == CMD_CHOOSE_USERBOT:
        await prompt_choose_userbot(update, context)
        return

    if text == CMD_HELP:
        command = COMMAND_BY_SLUG['manage_help']
        await _handle_command_entry(update, context, command, context.user_data.get('selected_userbot_id'))
        return

    command = LABEL_TO_COMMAND.get(text)
    if command:
        userbots = context.user_data.get('available_userbots')
        if not userbots:
            context.user_data['available_userbots'] = _fetch_userbots()
        userbot = _get_selected_userbot(context)
        userbot_id = userbot['id'] if userbot else None
        if not userbot and context.user_data['available_userbots'] and len(context.user_data['available_userbots']) == 1:
            single = context.user_data['available_userbots'][0]
            context.user_data['selected_userbot_id'] = single['id']
            context.user_data['manage_userbot_display'] = _format_userbot_name(single)
            userbot_id = single['id']
        await _handle_command_entry(update, context, command, userbot_id)
        return

    if context.user_data.get('manage_active'):
        reminder = "Gunakan tombol yang tersedia atau ketik salah satu nama perintah yang ada pada keyboard."
        await reply_markdown(update.message, reminder, MANAGE_COMMAND_MARKUP)
        log_outgoing(update.effective_user.id, reminder)


async def handle_active_command_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if message is None or not message.text:
        return

    slug = context.user_data.get('active_command_slug')
    if not slug:
        return

    command = COMMAND_BY_SLUG.get(slug)
    if command is None:
        context.user_data.pop('active_command_slug', None)
        reminder = "Sesi perintah berakhir. Pilih perintah baru dari keyboard."
        await reply_markdown(message, reminder, MANAGE_COMMAND_MARKUP)
        log_outgoing(update.effective_user.id, reminder)
        return

    userbot = _get_selected_userbot(context)
    if not userbot:
        warning = "Userbot tidak ditemukan. Mulai ulang dari menu Kelola Userbot."
        await reply_markdown(message, warning, MAIN_MENU_MARKUP)
        log_outgoing(update.effective_user.id, warning)
        context.user_data.pop('active_command_slug', None)
        command.reset(context)
        context.user_data['manage_active'] = False
        return

    completed, response_message = await command.handle_response(update, context, userbot['id'])

    if response_message:
        markup = MANAGE_COMMAND_MARKUP if completed else ReplyKeyboardRemove()
        if completed:
            response_message = f"{response_message}\n\nPilih perintah lain dari keyboard."
        await reply_markdown(message, response_message, markup)
        log_outgoing(update.effective_user.id, response_message)
    elif completed:
        fallback = "Perintah selesai. Pilih perintah lain dari keyboard."
        await reply_markdown(message, fallback, MANAGE_COMMAND_MARKUP)
        log_outgoing(update.effective_user.id, fallback)

    if completed:
        context.user_data.pop('active_command_slug', None)
        command.reset(context)
        context.user_data['manage_active'] = True

def main() -> None:
    # Gunakan PID manager untuk mencegah multiple instance
    with PIDManager("wizard"):
        initialize_database()
        application = Application.builder().token(WIZARD_BOT_TOKEN).build()

        admin_filter = filters.User(user_id=ADMIN_CHAT_ID)
        token_entry_filter = admin_filter & filters.TEXT & filters.Regex(f"^{re.escape(MENU_TOKEN_LOGIN)}$")

        create_userbot_conv = ConversationHandler(
            entry_points=[MessageHandler(admin_filter & filters.TEXT & filters.Regex(f"^{re.escape(MENU_CREATE_USERBOT)}$"), create_userbot_start)],
            states={
                CREATE_PHONE: [MessageHandler(admin_filter & (filters.TEXT | filters.CONTACT) & ~filters.COMMAND, create_userbot_receive_phone)],
                CREATE_CODE: [MessageHandler(admin_filter & filters.TEXT & ~filters.COMMAND, create_userbot_receive_code)],
                CREATE_PASSWORD: [MessageHandler(admin_filter & filters.TEXT & ~filters.COMMAND, create_userbot_receive_password)],
            },
            fallbacks=[CommandHandler("cancel", cancel)],
            conversation_timeout=600,
        )

        token_login_conv = ConversationHandler(
            entry_points=[MessageHandler(token_entry_filter, token_login_start)],
            states={
                ASK_SESSION_STRING: [MessageHandler(admin_filter & filters.TEXT & ~filters.COMMAND, receive_session_string)]
            },
            fallbacks=[CommandHandler("cancel", cancel)],
            conversation_timeout=300,
        )

        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("menu", show_menu))
        application.add_handler(create_userbot_conv)
        application.add_handler(token_login_conv)
        application.add_handler(CallbackQueryHandler(handle_choose_userbot_callback, pattern="^choose_userbot_"))
        application.add_handler(CallbackQueryHandler(handle_admin_userbot_selection, pattern="^admin_test_"))
        application.add_handler(MessageHandler(admin_filter & filters.TEXT & filters.Regex(f"^{re.escape(MENU_HELP)}$"), show_help))
        application.add_handler(MessageHandler(admin_filter & filters.TEXT, handle_menu_selection))
        application.add_error_handler(handle_application_error)

        try:
            application.run_polling(allowed_updates=Update.ALL_TYPES)
        except Conflict:
            sys.exit(1)
        except Exception as err:
            logger.exception("Wizard gagal dijalankan: %s", err)
            sys.exit(1)

if __name__ == "__main__":
    main()
