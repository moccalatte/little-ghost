import sqlite3
import os
import logging

# Siapkan logger untuk modul database
logger = logging.getLogger(__name__)

DB_FILE = os.path.join('data', 'userbots.db')

def get_db_connection():
    """Membuat dan mengembalikan koneksi ke database SQLite."""
    # Pastikan direktori 'data' ada
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def initialize_database():
    """
    Inisialisasi database dan membuat tabel jika belum ada.
    Fungsi ini aman untuk dijalankan beberapa kali.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Tabel untuk menyimpan profil userbot dan string session
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS userbots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE,
            username TEXT,
            string_session TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'inactive', -- 'active', 'inactive', 'error'
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # Tabel untuk melacak semua tugas yang berjalan (Auto Reply, Watcher, dll.)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            userbot_id INTEGER NOT NULL,
            process_id TEXT NOT NULL UNIQUE,
            command TEXT NOT NULL, -- 'auto_reply', 'watcher', 'broadcast'
            status TEXT NOT NULL, -- 'running', 'stopped', 'error'
            start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            details TEXT, -- JSON dengan detail seperti target grup, keywords, dll.
            FOREIGN KEY(userbot_id) REFERENCES userbots(id)
        )
        """)

        # Tabel untuk konfigurasi umum (misalnya, keyword default, dll.)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            userbot_id INTEGER,
            key TEXT NOT NULL,
            value TEXT,
            UNIQUE(userbot_id, key),
            FOREIGN KEY(userbot_id) REFERENCES userbots(id)
        )
        """)

        # Tabel untuk menyimpan daftar grup/channel yang di-cache
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            userbot_id INTEGER NOT NULL,
            telegram_group_id INTEGER NOT NULL,
            group_name TEXT,
            access_hash TEXT, -- Diperlukan untuk beberapa operasi Telethon
            UNIQUE(userbot_id, telegram_group_id),
            FOREIGN KEY(userbot_id) REFERENCES userbots(id)
        )
        """)

        conn.commit()
        logger.info("Database berhasil diinisialisasi. Semua tabel sudah siap.")
    except sqlite3.Error as e:
        logger.error(f"Terjadi kesalahan saat inisialisasi database: {e}")
        raise
    finally:
        if 'conn' in locals() and conn:
            conn.close()

if __name__ == '__main__':
    # Setup basic logging for standalone execution
    logging.basicConfig(level=logging.INFO, format='[%(asctime)s] [%(levelname)s] - %(message)s')
    print("Menjalankan inisialisasi database...")
    initialize_database()
    print("Inisialisasi selesai.")