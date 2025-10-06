# Little Ghost — Personal Telegram Userbot

Little Ghost adalah sistem userbot Telegram yang kuat dan modular, dibangun dengan Python, Telethon, dan `python-telegram-bot`. Proyek ini memungkinkan Anda untuk mengotomatiskan tindakan di akun Telegram Anda melalui antarmuka bot yang aman dan mudah digunakan.

Sistem ini terdiri dari dua komponen utama:
1.  **Wizard Bot**: Bot Telegram (`python-telegram-bot`) yang berfungsi sebagai antarmuka aman untuk mengelola userbot Anda. Hanya admin yang dapat mengaksesnya.
2.  **Userbot Service**: Layanan latar belakang (`Telethon`) yang menjalankan tugas-tugas otomatis seperti mengambil data, membalas pesan, atau menyiarkan pesan.

## Fitur Utama
- **Manajemen Berbasis Wizard**: Kontrol semua userbot Anda dari satu bot wizard yang aman.
- **Dukungan Multi-Akun**: Kelola beberapa akun userbot secara bersamaan.
- **Arsitektur Berbasis Tugas**: Wizard mendelegasikan tugas ke layanan userbot, yang menjalankannya secara asinkron.
- **Ambil Grup & Channel**: Dapatkan daftar lengkap semua grup dan channel yang diikuti oleh userbot Anda.
- **Penyimpanan Lokal**: Semua data (sesi, tugas, konfigurasi) disimpan secara lokal dalam database SQLite.
- **Logging Terperinci**: Aktivitas dicatat ke dalam file log untuk kemudahan debugging.

---

## Penyiapan & Instalasi

### 1. Prasyarat
- Python 3.8 atau lebih tinggi.
- Akun Telegram.

### 2. Dapatkan Kredensial yang Diperlukan

Anda memerlukan empat kredensial utama untuk dimasukkan ke dalam file `.env`:

- `WIZARD_BOT_TOKEN`: Token untuk Wizard Bot Anda. Dapatkan dari [@BotFather](https://t.me/BotFather) di Telegram.
- `ADMIN_CHAT_ID`: ID obrolan Telegram Anda. Dapatkan dengan mengirim pesan ke [@userinfobot](https://t.me/userinfobot).
- `API_ID` dan `API_HASH`: Kredensial API Telegram Anda. Dapatkan dari [my.telegram.org](https://my.telegram.org) di bawah "API development tools".

### 3. Konfigurasi Proyek

1.  **Clone repositori ini:**
    ```bash
    git clone <URL_REPOSITORI_ANDA>
    cd little-ghost
    ```

2.  **Buat file `.env`:**
    Salin atau ganti nama `.env.example` (jika ada) menjadi `.env`, atau buat file baru. Isi dengan kredensial yang Anda dapatkan di atas.
    ```env
    # Telegram Wizard Bot Configuration
    WIZARD_BOT_TOKEN="YOUR_WIZARD_BOT_TOKEN"
    ADMIN_CHAT_ID="YOUR_ADMIN_CHAT_ID"

    # Telegram Userbot API Credentials
    API_ID="YOUR_API_ID"
    API_HASH="YOUR_API_HASH"

    # (Opsional) Kunci rahasia untuk enkripsi di masa mendatang
    SESSION_SECRET=""
    ```

3.  **Berikan izin eksekusi pada skrip:**
    ```bash
    chmod +x scripts/dev.sh
    ```

---

## Cara Menjalankan

Proyek ini dirancang untuk dijalankan dengan satu skrip sederhana yang menangani semuanya: instalasi dependensi, menjalankan kedua layanan (Wizard dan Userbot), dan menampilkan log.

**Untuk memulai, jalankan:**
```bash
./scripts/dev.sh
```

Skrip ini akan:
1.  Menginstal semua paket Python yang diperlukan dari `requirements.txt`.
2.  Memulai **Wizard Bot** di latar belakang.
3.  Memulai **Userbot Service** di latar belakang.
4.  Menampilkan log dari kedua layanan secara real-time.

Untuk menghentikan semua layanan, cukup tekan `Ctrl+C` di terminal.

---

## Panduan Penggunaan

### Langkah 1: Mulai Wizard Bot
- Buka obrolan dengan Wizard Bot Anda di Telegram.
- Kirim perintah `/start`. Anda akan disambut dengan menu utama.

### Langkah 2: Tambahkan Userbot Baru
- Anda memerlukan **String Session Telethon** untuk akun yang ingin Anda otomatiskan. Ini adalah string panjang yang berfungsi sebagai token login permanen. Anda bisa mendapatkannya dengan berbagai cara, misalnya dari aplikasi lain yang menggunakan Telethon.
- Di menu utama Wizard Bot, klik **"Token Login"**.
- Kirim string sesi Anda ke bot.
- Wizard akan menyimpan sesi ini dan siap untuk digunakan.

### Langkah 3: Kelola Userbot Anda
1.  Di menu utama, klik **"Kelola Userbot"**.
2.  Bot akan menampilkan daftar semua userbot yang telah Anda tambahkan. Klik salah satu untuk mengelolanya.
3.  Pilih **"Dapatkan Grup/Channel"**. Ini akan mengirimkan tugas ke layanan Userbot untuk mengambil semua grup dan channel yang diikuti oleh akun tersebut.
4.  Setelah beberapa saat, kembali ke menu **"Kelola Userbot"** dan pilih userbot yang sama.
5.  Klik **"Lihat Grup Tersimpan"**. Bot akan menampilkan daftar semua grup dan channel yang berhasil diambil, lengkap dengan ID-nya.

---

## Struktur Proyek
```
little-ghost/
├─ services/       # Kode untuk Wizard Bot dan Userbot Service
│  ├─ wizard/
│  └─ userbot/
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