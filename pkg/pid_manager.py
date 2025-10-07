import os
import sys
import logging
import signal
from pathlib import Path

# Setup logger untuk PID manager
def setup_pid_logger():
    """Setup logger untuk PID manager."""
    logger = logging.getLogger("little_ghost.pid_manager")
    
    # Hindari duplikasi handler
    if logger.hasHandlers():
        return logger
    
    logger.setLevel(logging.INFO)
    
    # Format log
    log_format = logging.Formatter(
        '[%(asctime)s] [%(levelname)s] [%(name)s] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Handler untuk konsol
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(log_format)
    
    # Tambahkan handler
    logger.addHandler(stream_handler)
    
    return logger

logger = setup_pid_logger()

class PIDManager:
    def __init__(self, service_name: str):
        self.service_name = service_name
        self.pid_dir = Path("pids")
        self.pid_dir.mkdir(exist_ok=True)
        self.pid_file = self.pid_dir / f"{service_name}.pid"
        
        # Debug: print path
        print(f"DEBUG: PID file path: {self.pid_file.absolute()}")
        
        # Setup signal handler untuk cleanup
        self._original_signal_handlers = {}
        for sig in (signal.SIGTERM, signal.SIGINT):
            self._original_signal_handlers[sig] = signal.signal(sig, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handler untuk sinyal yang memastikan file PID dibersihkan."""
        logger.info(f"Menerima sinyal {signum}, membersihkan file PID...")
        self.release_lock()
        
        # Panggil handler asli jika ada
        if signum in self._original_signal_handlers and self._original_signal_handlers[signum]:
            self._original_signal_handlers[signum](signum, frame)
        
        # Keluar dengan kode yang sesuai
        sys.exit(0 if signum == signal.SIGTERM else 1)
    
    def acquire_lock(self) -> bool:
        """Mencoba mendapatkan lock untuk mencegah multiple instance.
        
        Returns:
            bool: True jika lock berhasil diperoleh, False jika sudah ada instance lain
        """
        try:
            # Cek apakah file PID sudah ada
            if self.pid_file.exists():
                with open(self.pid_file, 'r') as f:
                    existing_pid = f.read().strip()
                
                # Cek apakah proses dengan PID tersebut masih berjalan
                if existing_pid and existing_pid.isdigit():
                    try:
                        # Kirim signal 0 untuk cek apakah proses masih ada
                        os.kill(int(existing_pid), 0)
                        logger.warning(f"{self.service_name} sudah berjalan dengan PID {existing_pid}")
                        return False
                    except OSError:
                        # Proses tidak ada, hapus file PID lama
                        logger.info(f"Menemukan file PID {self.service_name} untuk proses yang tidak ada, menghapus...")
                        self.pid_file.unlink()
            
            # Tulis PID ke file baru
            try:
                logger.info(f"Mencoba membuat file PID di: {self.pid_file.absolute()}")
                with open(self.pid_file, 'w') as f:
                    f.write(str(os.getpid()))
                    f.flush()  # Pastikan data ditulis ke disk
                    os.fsync(f.fileno())  # Force write to disk
                
                # Verifikasi file berhasil dibuat
                logger.info(f"Memeriksa apakah file PID ada di: {self.pid_file.absolute()}")
                if self.pid_file.exists():
                    with open(self.pid_file, 'r') as f:
                        content = f.read().strip()
                    logger.info(f"Lock diperoleh untuk {self.service_name} dengan PID {os.getpid()}")
                    logger.info(f"File PID dibuat di: {self.pid_file} dengan isi: {content}")
                    
                    # List directory contents
                    try:
                        files = os.listdir(self.pid_dir)
                        logger.info(f"Isi direktori {self.pid_dir}: {files}")
                    except Exception as e:
                        logger.error(f"Gagal membaca direktori {self.pid_dir}: {e}")
                    
                    return True
                else:
                    logger.error(f"Gagal membuat file PID di: {self.pid_file}")
                    return False
            except Exception as e:
                logger.error(f"Error saat membuat file PID: {e}")
                return False
            
        except Exception as e:
            logger.error(f"Gagal mendapatkan lock untuk {self.service_name}: {e}")
            return False
    
    def release_lock(self):
        """Melepaskan lock dan menghapus file PID."""
        try:
            # Hapus file PID hanya jika proses berakhir dengan normal
            # File PID akan tetap ada untuk mencegah multiple instance
            # dan akan dihapus hanya saat proses dimatikan secara manual
            if self.pid_file.exists():
                # Baca PID dari file
                with open(self.pid_file, 'r') as f:
                    pid_from_file = f.read().strip()
                
                # Hapus file PID hanya jika PID di file sama dengan PID proses saat ini
                if pid_from_file == str(os.getpid()):
                    self.pid_file.unlink()
                    logger.info(f"File PID dihapus untuk {self.service_name}")
                else:
                    logger.info(f"File PID tidak dihapus karena PID berbeda (file: {pid_from_file}, current: {os.getpid()})")
            
            logger.info(f"Lock dilepaskan untuk {self.service_name}")
        except Exception as e:
            logger.error(f"Gagal melepaskan lock untuk {self.service_name}: {e}")
    
    def __enter__(self):
        """Context manager entry."""
        if not self.acquire_lock():
            logger.error(f"Gagal memulai {self.service_name}: instance lain sudah berjalan")
            sys.exit(1)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.release_lock()