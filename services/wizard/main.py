import os
import logging
import sqlite3
import uuid
import math
from dotenv import load_dotenv
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

# Muat environment variables dari .env di root proyek
load_dotenv()

# Impor modul proyek (sekarang berfungsi karena dijalankan dari root)
from pkg.logger import setup_logger
from core.infra.database import get_db_connection, initialize_database

# Setup logger
logger = setup_logger('wizard', 'main')

# Ambil konfigurasi dari environment
WIZARD_BOT_TOKEN = os.getenv('WIZARD_BOT_TOKEN')
ADMIN_CHAT_ID = int(os.getenv('ADMIN_CHAT_ID'))

# States untuk ConversationHandlers
(ASK_SESSION_STRING,) = range(1)
SELECT_USERBOT, SELECT_ACTION = range(1, 3)

# Konstanta paginasi
GROUPS_PER_PAGE = 10

# Menu utama
MAIN_MENU_KEYBOARD = [
    ["Buat Userbot", "Token Login"],
    ["Kelola Userbot", "Admin Setting"],
    ["Bantuan"],
]
MAIN_MENU_MARKUP = ReplyKeyboardMarkup(MAIN_MENU_KEYBOARD, one_time_keyboard=True, resize_keyboard=True)

# --- Handlers Utama ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("Anda tidak diizinkan menggunakan bot ini.")
        return
    await update.message.reply_text("Selamat datang di Little Ghost Wizard!", reply_markup=MAIN_MENU_MARKUP)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Operasi dibatalkan.", reply_markup=MAIN_MENU_MARKUP)
    return ConversationHandler.END

# --- Alur Token Login ---

async def token_login_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Silakan masukkan String Session Telethon Anda.", reply_markup=ReplyKeyboardRemove())
    return ASK_SESSION_STRING

async def receive_session_string(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    session_string = update.message.text.strip()
    try:
        conn = get_db_connection()
        conn.execute("INSERT INTO userbots (string_session, status) VALUES (?, ?)", (session_string, 'inactive'))
        conn.commit()
        await update.message.reply_text("String session berhasil disimpan!", reply_markup=MAIN_MENU_MARKUP)
    except sqlite3.IntegrityError:
        await update.message.reply_text("Gagal: String session ini sudah ada di database.", reply_markup=MAIN_MENU_MARKUP)
    except Exception as e:
        logger.error(f"Error saat menyimpan string session: {e}")
        await update.message.reply_text("Terjadi kesalahan.", reply_markup=MAIN_MENU_MARKUP)
    finally:
        if 'conn' in locals(): conn.close()
    return ConversationHandler.END

# --- Alur Kelola Userbot ---

async def manage_userbot_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    conn = get_db_connection()
    userbots = conn.execute("SELECT id, username, status FROM userbots ORDER BY id").fetchall()
    conn.close()

    if not userbots:
        await update.message.reply_text("Tidak ada userbot terdaftar.", reply_markup=MAIN_MENU_MARKUP)
        return ConversationHandler.END

    keyboard = [[InlineKeyboardButton(f"{b['username'] or f'Userbot #{b['id']}'} ({b['status']})", callback_data=f"manage_{b['id']}")] for b in userbots]
    await update.message.reply_text("Pilih userbot untuk dikelola:", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT_USERBOT

async def select_userbot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    userbot_id = int(query.data.split('_')[1])
    context.user_data['selected_userbot_id'] = userbot_id

    keyboard = [
        [InlineKeyboardButton("Dapatkan Grup/Channel", callback_data="action_get_groups")],
        [InlineKeyboardButton("Lihat Grup Tersimpan", callback_data="action_view_groups_0")], # 0 = halaman awal
        [InlineKeyboardButton("Kembali ke Daftar", callback_data="action_back_to_list")],
    ]
    await query.edit_message_text(text=f"Mengelola Userbot #{userbot_id}. Pilih aksi:", reply_markup=InlineKeyboardMarkup(keyboard))
    return SELECT_ACTION

async def select_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    action = query.data
    userbot_id = context.user_data.get('selected_userbot_id')

    if action == 'action_get_groups':
        process_id = str(uuid.uuid4())
        conn = get_db_connection()
        try:
            conn.execute("INSERT INTO tasks (userbot_id, process_id, command, status) VALUES (?, ?, ?, ?)", (userbot_id, process_id, 'get_groups', 'pending'))
            conn.commit()
            await query.edit_message_text("Permintaan mendapatkan grup telah dikirim.")
        except Exception as e:
            logger.error(f"Gagal membuat task 'get_groups': {e}")
            await query.edit_message_text("Gagal membuat permintaan.")
        finally:
            conn.close()
        await query.message.reply_text("Kembali ke menu utama.", reply_markup=MAIN_MENU_MARKUP)
        return ConversationHandler.END

    elif action.startswith('action_view_groups_'):
        page = int(action.split('_')[-1])
        await view_groups_paginated(query, userbot_id, page)
        return SELECT_ACTION

    elif action == 'action_back_to_list':
        # Hapus pesan saat ini dan tampilkan kembali daftar userbot
        await query.message.delete()
        # Perlu objek 'update' palsu karena `manage_userbot_start` mengharapkan `update.message`
        class FakeUpdate:
            def __init__(self, message):
                self.message = message
        return await manage_userbot_start(FakeUpdate(query.message), context)

async def view_groups_paginated(query, userbot_id, page=0):
    conn = get_db_connection()
    groups = conn.execute("SELECT group_name, telegram_group_id FROM groups WHERE userbot_id = ? ORDER BY group_name", (userbot_id,)).fetchall()
    conn.close()

    if not groups:
        await query.edit_message_text("Tidak ada grup tersimpan untuk userbot ini.", reply_markup=None)
        return

    total_pages = math.ceil(len(groups) / GROUPS_PER_PAGE)
    start_index = page * GROUPS_PER_PAGE
    end_index = start_index + GROUPS_PER_PAGE

    message_text = "Daftar Grup/Channel:\n\n"
    for group in groups[start_index:end_index]:
        message_text += f"- `{group['group_name']}` (ID: `{group['telegram_group_id']}`)\n"

    message_text += f"\nHalaman {page + 1} dari {total_pages}"

    pagination_keyboard = []
    row = []
    if page > 0:
        row.append(InlineKeyboardButton("<< Sebelumnya", callback_data=f"action_view_groups_{page - 1}"))
    if page < total_pages - 1:
        row.append(InlineKeyboardButton("Berikutnya >>", callback_data=f"action_view_groups_{page + 1}"))
    if row:
        pagination_keyboard.append(row)

    # Tombol kembali ke menu aksi utama untuk userbot ini
    keyboard_back_to_actions = [InlineKeyboardButton("Kembali ke Menu Aksi", callback_data=f"manage_{userbot_id}")]
    pagination_keyboard.append(keyboard_back_to_actions)

    await query.edit_message_text(text=message_text, reply_markup=InlineKeyboardMarkup(pagination_keyboard), parse_mode='Markdown')

def main() -> None:
    initialize_database()
    application = Application.builder().token(WIZARD_BOT_TOKEN).build()

    manage_userbot_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^Kelola Userbot$") & filters.User(user_id=ADMIN_CHAT_ID), manage_userbot_start)],
        states={
            SELECT_USERBOT: [CallbackQueryHandler(select_userbot_callback, pattern="^manage_")],
            SELECT_ACTION: [CallbackQueryHandler(select_action_callback, pattern="^action_")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        conversation_timeout=300,
    )

    token_login_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^Token Login$") & filters.User(user_id=ADMIN_CHAT_ID), token_login_start)],
        states={ASK_SESSION_STRING: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_session_string)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(token_login_conv)
    application.add_handler(manage_userbot_conv)

    application.run_polling()

if __name__ == "__main__":
    if not WIZARD_BOT_TOKEN or not ADMIN_CHAT_ID:
        logger.critical("Variabel WIZARD_BOT_TOKEN dan ADMIN_CHAT_ID wajib diisi!")
    else:
        main()