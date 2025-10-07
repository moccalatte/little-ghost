# Little Ghost — Telegram Userbot

Little Ghost adalah sistem userbot Telegram yang kuat dan modular, dibangun dengan Python, Telethon, dan `python-telegram-bot`. Proyek ini memungkinkan Anda untuk mengotomatiskan tindakan di akun Telegram Anda melalui antarmuka bot yang aman dan mudah digunakan.

Sistem ini terdiri dari dua komponen utama:
1.  **Wizard Bot**: Bot Telegram (`python-telegram-bot`) yang berfungsi sebagai antarmuka aman untuk mengelola userbot Anda. Hanya admin yang dapat mengaksesnya.
2.  **Userbot Service**: Layanan latar belakang (`Telethon`) yang menjalankan tugas-tugas otomatis seperti mengambil data, membalas pesan, atau menyiarkan pesan.

## Fitur Utama
- **Manajemen Berbasis Wizard**: Kontrol semua userbot Anda dari satu bot wizard yang aman.
- **Dukungan Multi-Akun**: Kelola beberapa akun userbot secara bersamaan.
- **Arsitektur Berbasis Tugas**: Wizard mendelegasikan tugas ke layanan userbot, yang menjalankannya secara asinkron.
- **Generator String Session**: Buat string session Telethon langsung dari wizard lewat OTP/QR tanpa keluar dari aplikasi.
- **Ambil Grup & Channel**: Dapatkan daftar lengkap semua grup dan channel yang diikuti oleh userbot Anda.
- **Penyimpanan Lokal**: Semua data (sesi, tugas, konfigurasi) disimpan secara lokal dalam database SQLite.
- **Logging Terperinci**: Aktivitas dicatat ke dalam file log untuk kemudahan debugging.
- **Log Percakapan per Admin**: Setiap interaksi wizard disimpan di `logs/wizard/users/{telegram_id}.log` agar mudah ditinjau.
- **Automated QA**: Menu Admin menyediakan pengujian otomatis berurutan untuk memastikan seluruh perintah userbot tetap berjalan setelah perubahan.

---

## Penyiapan & Instalasi

### 1. Prasyarat
- Python 3.12 (atau versi stabil terbaru yang didukung `python-telegram-bot` dan `Telethon`).
- Paket `python3-venv` untuk membuat virtual environment.
- Akun Telegram dengan akses API.

### 2. Dapatkan Kredensial yang Diperlukan

Anda memerlukan empat kredensial utama untuk dimasukkan ke dalam file `.env`:

- `WIZARD_BOT_TOKEN`: Token untuk Wizard Bot Anda. Dapatkan dari [@BotFather](https://t.me/BotFather) di Telegram.
- `ADMIN_CHAT_ID`: ID obrolan Telegram Anda. Dapatkan dengan mengirim pesan ke [@userinfobot](https://t.me/userinfobot).
- `API_ID` dan `API_HASH`: Kredensial API Telegram Anda. Dapatkan dari [my.telegram.org](https://my.telegram.org) di bawah "API development tools".

### 3. Konfigurasi Proyek

1. **Clone repositori ini:**
   ```bash
   git clone <URL_REPOSITORI_ANDA>
   cd little-ghost
   ```

2. **Siapkan virtual environment (opsional, tetapi direkomendasikan):**
   Skrip `scripts/dev.sh` akan otomatis membuat `.venv` jika belum ada. Jika ingin menyiapkan manual:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   ```

3. **Buat file `.env`:**
   Salin `.env.example` menjadi `.env`, lalu isi kredensial Anda tanpa tanda kutip agar mudah diproses:
   ```env
   WIZARD_BOT_TOKEN=123456789:ABC...
   ADMIN_CHAT_ID=123456789
   API_ID=123456
   API_HASH=abcdef0123456789abcdef0123456789
   # SESSION_SECRET opsional, dapat dikosongkan
   SESSION_SECRET=
   ```
   Gunakan perintah `grep -n '' .env` untuk memastikan file benar-benar tersimpan di disk.

4. **Berikan izin eksekusi pada skrip (sekali saja):**
   ```bash
   chmod +x scripts/dev.sh
   ```

---

## Cara Menjalankan

Proyek ini dirancang untuk dijalankan dengan skrip yang menangani instalasi dependensi, menjalankan layanan (Wizard dan Userbot), dan menampilkan log.

### Jalankan Wizard dan Userbot Bersamaan

**Jalankan lingkungan pengembangan:**
```bash
./scripts/dev.sh
```

Skrip melakukan hal berikut:
1. Membuat `.venv` jika belum ada dan memastikan `pip` tersedia.
2. Menginstal dependensi dari `requirements.txt` ke dalam `.venv`.
3. Memeriksa apakah sudah ada instance yang berjalan menggunakan file PID.
4. Menjalankan **Wizard Bot** dan **Userbot Service** secara paralel dengan PID yang berbeda.
5. Menampilkan log gabungan (`logs/wizard.log`, `logs/userbot.log`) selama 20 detik, kemudian berhenti otomatis sehingga terminal tidak menggantung.

🎨 **Fitur Terminal Interaktif:**
- Output terminal sekarang memiliki warna dan emoji untuk memudahkan identifikasi proses.
- Setiap pesan status memiliki indikator visual yang jelas dengan warna yang berbeda:
  - ✅ Hijau untuk sukses
  - ❌ Merah untuk error
  - ⚠️ Kuning untuk peringatan
  - 🔵 Biru untuk informasi proses

Opsi tambahan:
- `./scripts/dev.sh --follow-logs` supaya `tail -f` berjalan terus hingga Anda menekan `Ctrl+C`.
- `./scripts/dev.sh --tail-duration=60` untuk menyesuaikan lama pemantauan log otomatis (detik).
- `./scripts/dev.sh --no-tail` hanya mencetak potongan log awal tanpa menunggu.
- `./scripts/dev.sh --detach` menjalankan layanan lalu langsung keluar tanpa mematikan proses; hentikan manual dengan `pkill -f services.wizard.main` dan `pkill -f services.userbot.main`.
- `./scripts/dev.sh --tail-lines=80` untuk mengatur jumlah baris log yang ditampilkan.

Tekan `Ctrl+C` kapan saja (selain mode detach) dan skrip akan menghentikan kedua layanan secara bersih.

### Jalankan Wizard dan Userbot Secara Terpisah

Untuk debugging atau pengujian, Anda dapat menjalankan Wizard dan Userbot secara terpisah:

**Jalankan hanya Wizard Bot:**
```bash
./scripts/run_wizard.sh
```

**Jalankan hanya Userbot Service:**
```bash
./scripts/run_userbot.sh
```

Setiap skrip memiliki mekanisme PID management sendiri untuk mencegah multiple instance. Jika Anda mencoba menjalankan instance yang sama dua kali, skrip akan menampilkan pesan error dan meminta Anda untuk menghentikan instance yang sedang berjalan terlebih dahulu.

Opsi tambahan untuk skrip terpisah:
- `./scripts/run_wizard.sh --timeout=1800` untuk menjalankan Wizard Bot dengan timeout 30 menit (1800 detik).
- `./scripts/run_userbot.sh --timeout=3600` untuk menjalankan Userbot Service dengan timeout 1 jam (3600 detik).
- `./scripts/run_wizard.sh --no-tail` untuk menjalankan Wizard Bot tanpa menampilkan log real-time.
- `./scripts/run_userbot.sh --tail-lines=100` untuk menampilkan 100 baris log terakhir saat menjalankan Userbot Service.

### Mode Tanpa Timeout (khusus user)

Jika Anda ingin menempel pada log tanpa batas waktu dan memastikan skrip hanya dijalankan manual, gunakan wrapper berikut:

```bash
./scripts/dev_dre.sh
```

Skrip ini meminta konfirmasi interaktif dan secara otomatis meneruskan opsi `--follow-logs`, sehingga log akan terus mengalir sampai Anda menekan `Ctrl+C`. Skrip ini juga memiliki timeout default 2 jam (7200 detik) untuk mencegah proses berjalan terlalu lama tanpa pengawasan.

### Jalankan Wizard dan Userbot Secara Terpisah

Untuk debugging atau pengujian, Anda dapat menjalankan Wizard dan Userbot secara terpisah:

**Jalankan hanya Wizard Bot:**
```bash
./scripts/run_wizard.sh
```

**Jalankan hanya Userbot Service:**
```bash
./scripts/run_userbot.sh
```

Setiap skrip memiliki mekanisme PID management sendiri untuk mencegah multiple instance. Jika Anda mencoba menjalankan instance yang sama dua kali, skrip akan menampilkan pesan error dan meminta Anda untuk menghentikan instance yang sedang berjalan terlebih dahulu.

### Mode Tanpa Timeout (khusus user)

Jika Anda ingin menempel pada log tanpa batas waktu dan memastikan skrip hanya dijalankan manual, gunakan wrapper berikut:

```bash
./scripts/dev_dre.sh
```

Skrip ini meminta konfirmasi interaktif dan secara otomatis meneruskan opsi `--follow-logs`, sehingga log akan terus mengalir sampai Anda menekan `Ctrl+C`.

---

## Panduan Penggunaan

### Langkah 1: Mulai Wizard Bot
- Buka obrolan dengan Wizard Bot Anda di Telegram.
- Kirim perintah `/start` atau `/menu` kapan saja untuk menampilkan keyboard utama.

### Langkah 2: Buat atau Masukkan Userbot
- **🧙‍♂️ Buat Userbot** — jalani alur OTP/QR langsung dari wizard. Anda dapat memasukkan nomor telepon secara manual atau menggunakan tombol "📱 Bagikan Nomor Telepon" (dengan `KeyboardButton(request_contact=True)`) untuk berbagi nomor secara otomatis. Masukkan kode OTP (dapat dengan spasi seperti 4 5 6 7 8 9), dan wizard akan memprosesnya sebagai 456789 di background. Masukkan juga sandi 2FA (jika ada) untuk menghasilkan string session baru secara otomatis.
- **🪄 Token Login** — kirim String Session Telethon yang sudah Anda miliki. Wizard menyimpan string tersebut ke SQLite dan siap dipakai userbot.

🎨 **Fitur UI Wizard yang Ditingkatkan:**
- Wizard sekarang memiliki antarmuka yang lebih menarik dengan emoji yang relevan di setiap pesan.
- Tombol share nomor telepon sekarang lebih responsif dan otomatis menambahkan prefix "+" jika diperlukan.
- Pesan error dan sukses memiliki indikator visual yang jelas dengan emoji dan warna yang sesuai.
- Format string session sekarang ditampilkan dalam format kode monospace untuk memudahkan penyalinan.

### Langkah 3: Kelola Userbot
1. Pilih **"🛠️ Kelola Userbot"**, kemudian pilih userbot yang ingin dikelola melalui daftar yang muncul.
2. Keyboard balasan menampilkan tombol perintah: `🤖 Auto Reply`, `👀 Watcher`, `📢 Broadcast`, `📊 Job Status`, `⛔ Stop Jobs`, `🆘 Help`, serta opsi `🤖 Choose Userbot` dan `⬅️ Back`.
3. Setiap tombol memulai percakapan singkat sehingga admin diarahkan step-by-step (misal memilih grup, mengisi kata kunci, menentukan jadwal broadcast).
4. Wizard menyimpan instruksi ke tabel `tasks` dan Userbot Service mengeksekusinya secara asinkron. Status terbaru bisa dilihat melalui tombol `📊 Job Status`, sedangkan `⛔ Stop Jobs` menandai task aktif agar worker menghentikannya dengan aman.
5. Gunakan `📜 Watcher Logs` di dalam menu Watcher untuk melihat 8 eksekusi watcher terbaru lengkap dengan status, jumlah hit, serta catatan error (Google Sheets maupun sistem).

**Catatan Google Sheets untuk Watcher**
- Simpan file kredensial service account Google ke `credentials/service_account.json` dan pastikan memberikan akses editor ke alamat email service account yang sama.
- Folder `credentials/` sudah di-ignore oleh git; simpan file asli di sana agar tidak ikut ter-commit.
- Jika nama file kredensial berbeda, cukup letakkan satu file `.json` di folder tersebut atau set env `GOOGLE_SHEETS_CREDENTIAL_FILE=/path/ke/file.json`.
- Saat wizard meminta tujuan pencatatan `📄 Google Sheets`, masukkan URL lengkap atau ID spreadsheet (opsional menyertakan `gid=` untuk memilih tab tertentu). Sistem otomatis membuat header baris pertama bila sheet kosong dan menuliskan setiap kecocokan dengan kolom: `username_pengirim`, `telegram_id_pengirim`, `pesan`, `nama_grup`, `timestamp_utc`, `process_id`, `label`, `id_chat`, `message_id`.
- Jika kredensial tidak ditemukan atau sheet tidak dapat diakses, job akan gagal dengan status error serta catatan di log `logs/userbot/jobs/watcher/<process_id>.log`.

### Menu Tambahan
- **⚙️ Admin Setting** kini menyediakan `🧪 Automated Testing` (dry-run semua perintah utama dan menulis hasil ke `logs/userbot/jobs/auto_test/<process_id>.log`) serta `👷 Manage Userbot (WIP)` dengan utilitas `📂 Sync Users Groups` (sinkronisasi seluruh grup/kanal setiap userbot dan penulisan log incremental `logs/admin/sync_<telegram_id>.log`).
- **📚 Bantuan** merangkum fitur penting dan tautan ke menu utama.

### Tips
- Jika keyboard tidak muncul, kirim `/menu` untuk memunculkannya kembali.
- Pastikan `.env` berisi nilai tanpa tanda kutip agar dapat dikonversi ke tipe numerik (mis. `ADMIN_CHAT_ID`).
- Riwayat percakapan tersimpan di `logs/wizard/users/{telegram_id}.log`; gunakan file tersebut untuk audit interaksi.

---

## Struktur Proyek
```
little-ghost/
├─ services/       # Kode untuk Wizard Bot dan Userbot Service
│  ├─ wizard/
│  │  └─ commands/ # alur percakapan per perintah wizard
│  └─ userbot/
│     └─ commands/ # handler task userbot per perintah
├─ core/           # Logika bisnis inti dan infrastruktur
│  ├─ domain/
│  ├─ usecases/
│  └─ infra/        # Adapter (database, dll.)
├─ pkg/logger.py   # Modul logging terpusat
├─ data/           # Database SQLite dan file sesi
├─ logs/           # File log yang dihasilkan
├─ scripts/dev.sh  # Skrip untuk menjalankan proyek
├─ .env            # File konfigurasi (wajib dibuat)
└─ README.md       # Dokumentasi ini
```

---

## Debug & Troubleshooting

- Jalankan `timeout 20 ./scripts/dev.sh` selama debugging agar skrip tidak menggantung di `tail -f`.
- Cek log layanan di `logs/wizard.log` dan `logs/userbot.log` untuk melihat pesan error.
- Log aktivitas pengguna disimpan di `logs/wizard/users/{telegram_userid}.log` dengan format timestamp dan aktivitas.
- Pastikan `.env` tidak kosong: `ls -al .env` harus menunjukkan ukuran lebih dari 0 byte.
- Jika virtual environment bermasalah, hapus folder `.venv` lalu jalankan kembali `./scripts/dev.sh` untuk membuat ulang.
- Untuk debugging yang lebih lama, gunakan opsi timeout pada skrip terpisah:
  ```bash
  # Jalankan Wizard Bot dengan timeout 1 jam
  ./scripts/run_wizard.sh --timeout=3600
  
  # Jalankan Userbot Service dengan timeout 30 menit
  ./scripts/run_userbot.sh --timeout=1800
  ```
- Jika layanan berhenti secara tak terduga, periksa file PID di `pids/` dan pastikan tidak ada proses yang tersisa:
  ```bash
  # Cek proses yang masih berjalan
  ps aux | grep "services.wizard.main"
  ps aux | grep "services.userbot.main"
  
  # Hentikan proses jika diperlukan
  pkill -f services.wizard.main
  pkill -f services.userbot.main
  ```

### Error Umum dan Solusi

#### Error "ExtBot is not properly initialized"
Jika Anda menemukan error "ExtBot is not properly initialized" di log Wizard, ini biasanya terjadi karena ada masalah dengan inisialisasi bot di python-telegram-bot. Error ini telah diperbaiki dengan menambahkan inisialisasi bot secara eksplisit sebelum menjalankan polling.

#### Error "bytes or str expected, not <class 'NoneType'>" saat mengirim kode OTP
Error ini terjadi ketika pengguna mencoba membagikan kontak melalui tombol "Bagikan Nomor Telepon" tetapi nomor telepon yang diterima adalah None. Error ini telah diperbaiki dengan menambahkan validasi untuk memastikan nomor telepon tidak None sebelum mengirim kode OTP. Selain itu, ConversationHandler juga telah diperbarui untuk menangani pesan kontak dengan benar.

#### Warning "PTBUserWarning: If 'per_message=False'"
Ini adalah warning dari python-telegram-bot tentang ConversationHandler. Warning ini tidak mempengaruhi fungsionalitas bot dan dapat diabaikan.

Rollback cukup dengan mengembalikan perubahan file (`git checkout -- <file>` atau `git restore`), kemudian ulangi langkah di atas.
