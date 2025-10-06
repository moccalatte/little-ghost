import os
import asyncio
import sqlite3
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import Dialog

# Muat environment variables dari .env di root proyek
load_dotenv()

# Impor modul proyek
from pkg.logger import setup_logger
from core.infra.database import get_db_connection

# Setup logger
logger = setup_logger('userbot', 'task_runner')

# Ambil konfigurasi dari environment
API_ID = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')

async def handle_get_groups(task: sqlite3.Row):
    """Menangani tugas 'get_groups'."""
    task_id = task['id']
    userbot_id = task['userbot_id']
    logger.info(f"Memulai tugas 'get_groups' untuk userbot ID: {userbot_id} (Task ID: {task_id})")

    conn = get_db_connection()
    try:
        userbot_session = conn.execute("SELECT string_session FROM userbots WHERE id = ?", (userbot_id,)).fetchone()

        if not userbot_session:
            raise Exception(f"Tidak dapat menemukan string session untuk userbot ID: {userbot_id}")

        client = TelegramClient(StringSession(userbot_session['string_session']), int(API_ID), API_HASH)

        await client.connect()
        if not await client.is_user_authorized():
            raise Exception("User tidak terotorisasi. String session mungkin tidak valid atau kedaluwarsa.")

        me = await client.get_me()
        logger.info(f"Berhasil terhubung sebagai {me.username} untuk menjalankan tugas.")

        conn.execute("UPDATE userbots SET telegram_id = ?, username = ?, status = 'active' WHERE id = ?", (me.id, me.username, userbot_id))

        dialogs: list[Dialog] = await client.get_dialogs()
        groups_to_save = [(userbot_id, d.id, d.name, d.entity.access_hash) for d in dialogs if d.is_group or d.is_channel]

        if groups_to_save:
            conn.execute("DELETE FROM groups WHERE userbot_id = ?", (userbot_id,))
            conn.executemany(
                "INSERT OR REPLACE INTO groups (userbot_id, telegram_group_id, group_name, access_hash) VALUES (?, ?, ?, ?)",
                groups_to_save
            )
            logger.info(f"Menyimpan {len(groups_to_save)} grup/channel untuk userbot ID: {userbot_id}")

        conn.execute("UPDATE tasks SET status = 'completed' WHERE id = ?", (task_id,))
        conn.commit()
        logger.info(f"Tugas 'get_groups' (Task ID: {task_id}) selesai.")

    except Exception as e:
        logger.error(f"Error saat menjalankan 'get_groups' (Task ID: {task_id}): {e}")
        conn.execute("UPDATE tasks SET status = 'error', details = ? WHERE id = ?", (str(e), task_id))
        conn.commit()
    finally:
        if 'client' in locals() and client.is_connected():
            await client.disconnect()
        if 'conn' in locals():
            conn.close()

async def main_loop():
    """Loop utama untuk memeriksa dan menjalankan tugas dari database."""
    logger.info("Layanan Userbot Task Runner dimulai. Mencari tugas...")
    while True:
        pending_task = None
        conn = get_db_connection()
        try:
            # Cari tugas yang 'pending'
            pending_task = conn.execute("SELECT * FROM tasks WHERE status = 'pending' ORDER BY id LIMIT 1").fetchone()
            if pending_task:
                # Tandai sebagai 'running' untuk mencegah pemrosesan ganda oleh worker lain
                conn.execute("UPDATE tasks SET status = 'running' WHERE id = ?", (pending_task['id'],))
                conn.commit()
        except Exception as e:
            logger.error(f"Gagal mengambil tugas dari database: {e}")
        finally:
            conn.close()

        if pending_task:
            command = pending_task['command']
            if command == 'get_groups':
                await handle_get_groups(pending_task)
            else:
                logger.warning(f"Perintah tidak dikenal: {command}. Menandai sebagai error.")
                conn = get_db_connection()
                try:
                    conn.execute("UPDATE tasks SET status = 'error', details = ? WHERE id = ?", (f"Unknown command: {command}", pending_task['id']))
                    conn.commit()
                finally:
                    conn.close()
        else:
            # Jika tidak ada tugas, tunggu sebelum memeriksa lagi
            await asyncio.sleep(5)

if __name__ == "__main__":
    if not API_ID or not API_HASH:
        logger.critical("Variabel environment API_ID dan API_HASH wajib diisi!")
    else:
        try:
            asyncio.run(main_loop())
        except KeyboardInterrupt:
            logger.info("Layanan Userbot dihentikan secara manual.")