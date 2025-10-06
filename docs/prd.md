# Little Ghost — Personal Telegram Userbot (Python/Telethon + SQLite)

## 1. Tujuan Produk
**Objective:** Membangun _Little Ghost_, sistem userbot berbasis Python + Telethon dengan dua komponen utama: **Wizard** (bot antarmuka) dan **Userbot** (eksekutor otomatis).  
Seluruh data disimpan di **SQLite** dan **file lokal**, serta dapat diintegrasikan dengan **Google Sheets API** untuk mencatat pesan yang relevan berdasarkan keyword.

**Why Python:**  
- Ekosistem library Telegram matang (`python-telegram-bot`, `Telethon`).  
- Ringan, mudah diatur, dan mendukung async & logging sederhana.  

---

## 2. Arsitektur Umum
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

Wizard bertugas sebagai antarmuka percakapan untuk membuat, mengatur, dan memantau aktivitas userbot.  
Userbot mengeksekusi perintah otomatis seperti **Auto Reply**, **Watcher**, **Broadcast**, dan lainnya.

---

## 3. Directory Layout
```
little-ghost/
├─ services/
│  ├─ wizard/           # bot antarmuka (python-telegram-bot)
│  └─ userbot/          # eksekutor otomatis (Telethon)
├─ core/
│  ├─ domain/           # entitas & aturan domain
│  ├─ usecases/         # logika bisnis (job, auto-reply, watcher, broadcast)
│  └─ infra/            # adapter (telethon, sheets, storage)
├─ pkg/logger.py        # logging utama
├─ data/                # SQLite + konfigurasi runtime
├─ credentials/         # Google API credential
├─ scripts/dev.sh       # jalankan wizard & userbot bersamaan
├─ .env                 # konfigurasi environment
└─ docs/                # dokumentasi
```

---

## 4. Konsep & Fitur Utama

### 4.1 Wizard Bot
- Library: `python-telegram-bot` (polling mode).
- Token dan konfigurasi disimpan di `.env` (`WIZARD_BOT_TOKEN`, `ADMIN_CHAT_ID`).
- Hanya `ADMIN_CHAT_ID` yang dapat mengakses wizard.

**Menu utama (ReplyKeyboardMarkup):**
```
[ Buat Userbot ]
[ Token Login ]
[ Kelola Userbot ]
[ Admin Setting ]
[ Bantuan ]
```

#### 4.1.1 Buat Userbot
- Wizard akan memulai proses login baru menggunakan **OTP / QR login** (tergantung metode yang diminta Telegram).  
- Jika akun memiliki **verifikasi dua langkah (2FA)**, wizard akan meminta kode sandi tambahan.  
- Nilai `API_ID` dan `API_HASH` diambil langsung dari variabel environment `.env`.  
- Setelah proses login berhasil, wizard menampilkan dan menyimpan **string session** yang dihasilkan ke SQLite.  
- String session ini bisa digunakan ulang nanti lewat menu “Token Login”.

#### 4.1.2 Token Login
- Digunakan untuk login dengan **string session** yang sudah ada.  
- Wizard akan meminta pengguna memasukkan session string, lalu menjalankan userbot berdasarkan itu.  
- Setelah berhasil, userbot aktif dan siap menerima perintah dari Wizard atau sistem task-nya.

#### 4.1.3 Kelola Userbot
- Menu ini berisi daftar perintah yang bisa dijalankan terhadap userbot aktif.  
- Menggunakan ReplyKeyboardMarkup untuk navigasi.  
- Submenu utama mencakup:
  ```
  [ Jalankan Auto Reply ]
  [ Jalankan Watcher ]
  [ Broadcast ]
  [ Get Groups/Channels ]
  [ Status & Info ]
  [ Stop Job ]
  [ Help ]
  [ Kembali ]
  ```
- Dari sini wizard dapat memicu task async di userbot (Auto Reply, Watcher, Broadcast, dsb) serta memantau dan menghentikannya.

#### 4.1.4 Admin Setting
- Menu khusus untuk pengaturan tingkat lanjut (akan dirinci kemudian).  
- Fitur potensial mencakup: pengaturan default keyword, pengaturan Google Sheets, backup database otomatis, atau reset log.

---

### 4.2 Userbot
- Library: `Telethon`.
- Menangani task-task async secara paralel: Auto Reply, Watcher, Broadcast, Get Groups/Channels.  
- Setiap task memiliki `process_id` unik untuk monitoring dan kontrol melalui Wizard.  
- Data status job disimpan di SQLite (`data/userbots.db`).

---

## 5. Storage & Data
- **Database:** `data/userbots.db`  
  Berisi tabel:
  - `userbots`: profil userbot (username, string_session, status)
  - `tasks`: daftar task aktif (process_id, command, status, waktu mulai)
  - `config`: keyword, daftar target, pengaturan default
  - `groups`: daftar grup/channel yang terhubung
- **Checkpoint:** `data/state.json` untuk menghindari duplikasi pesan.  
- **Logs:** `logs/{service}/{context}/{date}.log` mencatat semua aktivitas dan error (termasuk FloodWait / rate limit).  

---

## 6. Command & Workflow

### 6.1 Auto Reply
- Membalas pesan di grup/channel berdasarkan keyword tertentu.  
- Mendukung keyword positif dan negatif.  
- Bisa dijalankan bersamaan di beberapa grup.  
- Setiap job menghasilkan `process_id` unik.  

### 6.2 Watcher
- Memantau pesan yang sesuai dengan keyword, lalu mencatat hasilnya ke **Google Sheets**.  
- Setiap rule Watcher menghasilkan `process_id` sendiri.  
- Dapat berjalan paralel dengan fitur lain.  

### 6.3 Broadcast
- Mengirim pesan ke semua grup atau grup tertentu berdasarkan ID.  
- Dapat dijadwalkan (cronjob) dengan interval tertentu (mis. 1 menit).  
- Mencatat hasil di log (berhasil/gagal).  

### 6.4 Get Groups/Channels
- Menampilkan daftar grup dan channel yang userbot ikuti.  
- Menampilkan ID dan nama grup/channel.  

### 6.5 Info
- Menampilkan semua task aktif (Auto Reply, Watcher, Broadcast).  
- Menampilkan `process_id`, status, dan target.  

### 6.6 Help
- Menampilkan panduan lengkap penggunaan userbot dan semua command, dalam bahasa Indonesia.  

---

## 7. Logging & Audit
- Semua aktivitas wizard dan userbot tercatat.  
- Error FloodWait, Timeout, dan Limit dicatat di `logs/userbot/errors/{telegram_id}-{tanggal}.log`.  
- Log terminal dan background process juga tersimpan otomatis.  
- Format: `[timestamp] [level] [service] [context] message`.

---

## 8. Security & Privacy
- Akses wizard dibatasi oleh `ADMIN_CHAT_ID`.  
- String session bisa dienkripsi dengan `SESSION_SECRET`.  
- Data sensitif tidak pernah dikirim keluar selain ke Google Sheets API.

---

## 9. Reliability & Job Handling
- Job async bisa dihentikan dengan aman.  
- FloodWait dan rate limit ditangani dengan retry backoff.  
- Task management berbasis SQLite untuk sinkronisasi.

---

## 10. Ringkasan Menu Wizard

| Menu Utama | Fungsi |
|-------------|---------|
| **Buat Userbot** | Login via OTP/QR, menghasilkan string session baru |
| **Token Login** | Login menggunakan string session yang sudah ada |
| **Kelola Userbot** | Menampilkan dan mengelola seluruh command userbot |
| **Admin Setting** | Pengaturan lanjutan (detail menyusul) |
| **Bantuan** | Panduan lengkap penggunaan Little Ghost |

---

_“Little Ghost” adalah userbot yang fleksibel, tenang, dan tangguh — siap bekerja di balik layar tanpa perlu pengawasan terus-menerus._
