import logging
import os
from logging.handlers import RotatingFileHandler
from datetime import datetime

def setup_logger(service_name: str, context: str, level=logging.INFO):
    """
    Menyiapkan dan mengonfigurasi logger terpusat.

    Args:
        service_name (str): Nama layanan (misalnya, 'wizard', 'userbot').
        context (str): Konteks logging (misalnya, 'main', 'auth', 'errors').
        level (int): Level logging (default: logging.INFO).

    Returns:
        logging.Logger: Instance logger yang sudah dikonfigurasi.
    """
    # Buat nama logger yang unik
    logger_name = f"little_ghost.{service_name}.{context}"
    logger = logging.getLogger(logger_name)

    # Hindari duplikasi handler jika logger sudah ada
    if logger.hasHandlers():
        return logger

    logger.setLevel(level)

    # Tentukan format log
    log_format = logging.Formatter(
        '[%(asctime)s] [%(levelname)s] [%(name)s] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Buat direktori log jika belum ada
    log_dir = os.path.join('logs', service_name, context)
    os.makedirs(log_dir, exist_ok=True)

    # Tentukan path file log dengan tanggal
    date_str = datetime.now().strftime('%Y-%m-%d')
    log_file = os.path.join(log_dir, f'{date_str}.log')

    # Handler untuk menulis log ke file dengan rotasi
    file_handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=2)
    file_handler.setFormatter(log_format)

    # Handler untuk menampilkan log di konsol
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(log_format)

    # Tambahkan handler ke logger
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

    return logger