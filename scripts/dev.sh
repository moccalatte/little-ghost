#!/bin/bash

# Script untuk menjalankan lingkungan pengembangan Little Ghost

# Hentikan semua proses python yang sedang berjalan saat skrip dihentikan
trap "trap - SIGTERM && kill -- -$$" SIGINT SIGTERM EXIT

# 1. Instal dependensi
echo "Menginstal dependensi dari requirements.txt..."
pip install --upgrade pip > /dev/null 2>&1
pip install -r requirements.txt > /dev/null 2>&1
echo "Instalasi selesai."
echo ""

# 2. Jalankan Wizard Bot di background
echo "Menjalankan Wizard Bot..."
python -m services.wizard.main > logs/wizard.log 2>&1 &
WIZARD_PID=$!
echo "Wizard Bot berjalan dengan PID: $WIZARD_PID"
echo ""

# 3. Jalankan Userbot di background
# Tambahkan jeda singkat untuk memastikan wizard siap terlebih dahulu jika diperlukan
sleep 2
echo "Menjalankan Userbot Service..."
python -m services.userbot.main > logs/userbot.log 2>&1 &
USERBOT_PID=$!
echo "Userbot Service berjalan dengan PID: $USERBOT_PID"
echo ""

# 4. Tampilkan log secara real-time
echo "Setup selesai. Menampilkan log gabungan (tekan Ctrl+C untuk berhenti):"
echo "----------------------------------------------------"
# Buat direktori log terlebih dahulu jika belum ada
mkdir -p logs
touch logs/wizard.log logs/userbot.log
tail -f logs/wizard.log logs/userbot.log