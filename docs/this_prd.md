# Little Ghost — Telegram Userbot (Python/Telethon + SQLite)

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
│  │  └─ commands/      # alur percakapan per perintah wizard
│  └─ userbot/          # eksekutor otomatis (Telethon)
│     └─ commands/      # handler task userbot per perintah
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

**Menu utama (ReplyKeyboardMarkup horizontal):**
```
[ Buat Userbot | Token Login ]
[ Kelola Userbot | Admin Setting ]
[ Bantuan ]
```

#### 4.1.1 Buat Userbot
- Wizard memandu proses login baru menggunakan **OTP / QR login** langsung dari antarmuka percakapan.
- Pengguna dapat memasukkan nomor telepon secara manual atau menggunakan tombol **"📱 Bagikan Nomor Telepon"** (dengan `KeyboardButton(request_contact=True)`) untuk berbagi nomor secara otomatis.
- Jika akun memiliki **verifikasi dua langkah (2FA)**, wizard akan meminta kode sandi tambahan.
- Saat memasukkan kode OTP, pengguna dapat mengetik dengan spasi (contoh: 4 5 6 7 8 9) untuk memudahkan, dan wizard akan memprosesnya sebagai 456789 di background.
- Nilai `API_ID` dan `API_HASH` diambil dari variabel environment `.env`.
- Setelah proses login berhasil, wizard menampilkan dan menyimpan **string session** yang dihasilkan ke SQLite.
- String session ini otomatis tercatat dan bisa digunakan ulang lewat menu "Token Login".

#### 4.1.2 Token Login
- Digunakan untuk login dengan **string session** yang sudah ada.  
- Wizard akan meminta pengguna memasukkan session string, lalu menjalankan userbot berdasarkan itu.  
- Setelah berhasil, userbot aktif dan siap menerima perintah dari Wizard atau sistem task-nya.

#### 4.1.3 Kelola Userbot
- Menu ini menampilkan daftar perintah userbot aktif melalui `ReplyKeyboardMarkup`. Setiap tombol membuka percakapan singkat yang menjelaskan langkah berikutnya (pilih cakupan, isi keyword, dsb) agar ramah bagi pengguna pemula.
- Tombol yang tersedia:
  - `🤖 Auto Reply`
  - `👀 Watcher`
  - `📢 Broadcast`
  - `📊 Job Status`
  - `⛔ Stop Jobs`
  - `🆘 Help`
  - `🤖 Choose Userbot`
  - `⬅️ Back`
- Wizard membuat task baru di SQLite untuk setiap instruksi dan Userbot Service akan menjalankannya secara asinkron.
- Status terbaru per task dapat dipantau lewat `📊 Job Status`, sedangkan `⛔ Stop Jobs` menandai task berjalan agar worker menghentikannya dengan aman.
- Setiap percakapan selalu menampilkan tombol `⬅️ Back` sehingga admin dapat sewaktu-waktu kembali ke menu tanpa mengetik perintah manual.

#### 4.1.4 Admin Setting
- Menyediakan utilitas lanjutan, saat ini terdiri dari:
  - `🧪 Automated Testing` — wizard meminta userbot yang akan diuji, lalu men-trigger task `auto_test`.
    - Task menjalankan seluruh perintah utama secara terurut (Sync Groups → Auto Reply → Watcher → Broadcast) dalam mode aman/dry-run.
    - Semua langkah, hasil, dan snapshot task tercatat di `logs/userbot/jobs/auto_test/<process_id>.log` serta `tasks.details.auto_test`.
  - `👷 Manage Userbot (WIP)` — sub-menu maintenance.
    - Saat ini tersedia `📂 Sync Users Groups`: wizard mengantrikan task sinkronisasi untuk seluruh userbot. Userbot Service memperbarui tabel `groups` (lengkap dengan `group_type` dan `username`) dan menulis log incremental `logs/admin/sync_<telegram_userid>.log` (hanya entri baru berdasarkan `telegram_group_id`).
    - Menu ini akan menjadi pusat fitur lanjutan seperti clean DB per userbot, penarikan log granular, pemberian warning, dsb.
- Menu admin selalu menampilkan keyboard khusus agar admin cepat berpindah antar utilitas atau kembali ke menu utama.

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

### 6.1 🤖 Auto Reply
- Wizard memandu admin memilih cakupan target melalui tombol: `🌐 All Groups`, `📡 All Channels`, atau `🎯 Specific Targets` (memasukkan ID chat tanpa prefiks `-100`, disertai tutor singkat cara mengambil ID).
- Setelah itu admin mengisi kata kunci pemicu. Format seperti `need tanpa nut` otomatis menambahkan pengecualian. Wizard juga menyediakan tombol untuk menambah pengecualian secara manual atau melewatinya.
- Langkah terakhir adalah menuliskan pesan balasan. Tombol `⬅️ Back` selalu tampil sehingga admin bisa kembali ke menu kapan saja.
- Userbot memasang handler `Telethon.events.NewMessage` per target, mencatat setiap hit di `details.replied_count`, dan menyimpan log di `logs/userbot/jobs/auto_reply/<process_id>.log`.

### 6.2 👀 Watcher
- Menu Watcher kini menawarkan dua aksi: `➕ Buat Watcher` untuk membuat rule baru dan `📜 Watcher Logs` untuk menampilkan ringkasan 8 task watcher terbaru (status, total hit, catatan error Google Sheets maupun sistem).
- Alur pembuatan watcher mirip Auto Reply: pilih cakupan target, tentukan kata kunci, dan opsional menambahkan pengecualian.
- Wizard kemudian meminta tujuan pencatatan (`🗂 Local Log` atau `📄 Google Sheets`) serta label watcher. Jika memilih Sheets admin memasukkan ID/URL sheet; wizard juga menampilkan tutor singkat:
  1. Aktifkan Google Sheets API & buat Service Account.
  2. Simpan kredensial JSON ke `credentials/service_account.json` (ikon di struktur proyek sudah disediakan) — folder ini di-ignore git, jadi aman menaruh file lokal.
  3. Bagikan sheet ke email service account dengan akses editor.
- Bila nama file kredensial berbeda, sistem otomatis memakai satu-satunya file `.json` di folder `credentials/` atau gunakan env `GOOGLE_SHEETS_CREDENTIAL_FILE` untuk menunjuk file tertentu.
- Data konfigurasi (keywords, exclusions, tujuan) tersimpan di kolom `details`; saat mode Sheets aktif backend menambahkan metadata `destination.resolved` dengan judul spreadsheet dan worksheet agar mudah diaudit dari menu log.
- Userbot memantau pesan baru sesuai aturan dan mencatat kecocokan ke log `logs/userbot/jobs/watcher/<process_id>.log` lengkap dengan metadata (chat id, isi pesan).
- Untuk mode Google Sheets, sistem memastikan baris header (`username_pengirim`, `telegram_id_pengirim`, `pesan`, `nama_grup`, `timestamp_utc`, `process_id`, `label`, `id_chat`, `message_id`) dibuat otomatis bila sheet masih kosong. Setiap hit menuliskan data tersebut; bila terjadi kegagalan (kredensial, izin, sheet tidak ditemukan, dll.) status job berubah menjadi error dan kolom `details.last_sheet_error` menyimpan pesan sumber.

### 6.3 📢 Broadcast
- Percakapan broadcast terbagi beberapa tahap terpandu:
  1. Pilih mode konten (`📝 Manual Message` atau `🔁 Forward Message`). Mode manual mendukung teks maupun media (gambar/dokumen + caption); wizard mengunduh file ke `data/uploads/` agar userbot dapat mengirimnya kembali. Mode forward meminta admin me-forward pesan asli yang akan disebarkan.
  2. Tentukan jadwal (`▶️ Send Now`, `⏳ Delay`, `🔁 Interval`). Untuk delay/interval wizard meminta jumlah menit (minimal 1) sambil memperingatkan risiko FloodWait.
  3. Pilih cakupan target (`All Groups`, `All Channels`, atau `Specific Targets` dengan tutor ID tanpa `-100`).
- Detail task menyimpan struktur konten (`text`, `photo`, `document`, `forward`) dan jadwal sehingga userbot dapat menggunakan `send_message`, `send_file`, atau `forward_messages` sesuai kebutuhan. Informasi pengiriman terakhir disimpan di kolom `details` dan log `logs/userbot/jobs/broadcast/<process_id>.log`.

### 6.4 📂 Sync Users Groups (Admin)
- Tersedia di menu `⚙️ Admin Setting` → `👷 Manage Userbot (WIP)`.
- Wizard mengantrikan task `sync_groups` untuk setiap userbot. Userbot Service memindai dialog Telethon dan memperbarui tabel `groups` (menyertakan `group_type`, `username`, `access_hash`).
- Hasil sinkronisasi juga dicatat ke `logs/admin/sync_<telegram_userid>.log` (format JSONL). Saat menjalankan ulang, sistem hanya menambahkan entri baru berdasarkan `telegram_group_id`. Progres ditulis per 50 entri (`⏳ page x/y`) agar mudah dipantau.

### 6.5 📊 Job Status
- Menyajikan ringkasan 15 task terbaru (command, status, process id) langsung dari tabel `tasks`.
- Informasi tambahan seperti jadwal broadcast atau label watcher ditarik dari kolom `details` sehingga admin cepat melihat konfigurasi terakhir.

### 6.6 ⛔ Stop Jobs
- Wizard menandai task (`status = 'stopped'`) berdasarkan pilihan admin; userbot loop utama membaca status ini dan memanggil `command.stop` untuk menghentikan handler/loop terkait.
- Detail task disisipi stempel waktu `stopped_at` untuk audit.

### 6.7 🆘 Help
- Menampilkan ringkasan tombol `Kelola Userbot`, tips mengulang /menu, serta lokasi log percakapan (`logs/wizard/users/<telegram_id>.log`).

### 6.8 Admin Auto Test
- Task `auto_test` menjalankan urutan: Sync Groups → Auto Reply → Watcher → Broadcast dalam mode dry-run. Untuk broadcast, konten dikirim sebagai pesan manual sehingga alur terbaru tetap tervalidasi.
- Setiap langkah dicatat ke `details.auto_test` dan ke file `logs/userbot/jobs/auto_test/<process_id>.log` untuk memudahkan debugging regresi.

---

## 7. Logging & Audit
- Semua aktivitas wizard dan userbot tercatat.
- Setiap percakapan admin dengan wizard disimpan ke `logs/wizard/users/{telegram_userid}-{timestamp}.log`.
- Error FloodWait, Timeout, dan Limit dicatat di `logs/userbot/errors/{telegram_id}-{tanggal}.log`.
- Log terminal dan background process juga tersimpan otomatis.
- Format: `[timestamp] [level] [service] [context] message`.
- Sistem PID management mencegah multiple instance dengan file PID di `pids/{service}.pid`.

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
