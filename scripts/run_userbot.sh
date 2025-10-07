#!/bin/bash

# Script untuk menjalankan hanya Userbot Service

set -u -o pipefail

# Warna untuk output terminal
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
WHITE='\033[0;37m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Fungsi untuk mencetak teks dengan warna
print_color() {
    local color=$1
    local text=$2
    echo -e "${color}${text}${NC}"
}

# Default timeout dan duration
TIMEOUT_DURATION=${TIMEOUT_DURATION:-3600}  # Default 1 jam
TAIL_FOLLOW=${TAIL_FOLLOW:-true}
TAIL_LINES=${TAIL_LINES:-40}

# Parse argumen
for arg in "$@"; do
  case "$arg" in
    --timeout=*)
      TIMEOUT_DURATION="${arg#*=}"
      ;;
    --no-tail)
      TAIL_FOLLOW=false
      ;;
    --tail-lines=*)
      TAIL_LINES="${arg#*=}"
      ;;
    *)
      print_color $YELLOW "⚠️  Peringatan: argumen tidak dikenali '$arg' diabaikan." >&2
      ;;
  esac
done

# Validasi timeout
case "$TIMEOUT_DURATION" in
  ''|*[!0-9]*)
    print_color $RED "❌ Nilai untuk --timeout harus berupa angka >= 0." >&2
    exit 1
    ;;
esac

PYTHON_BIN=${PYTHON_BIN:-python3}

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    print_color $RED "❌ Gagal menemukan interpreter: $PYTHON_BIN"
    exit 1
fi

VENV_DIR=".venv"

if [ ! -d "$VENV_DIR" ] || [ ! -x "$VENV_DIR/bin/python" ]; then
    print_color $RED "❌ Virtual environment tidak ditemukan. Silakan jalankan ./scripts/dev.sh terlebih dahulu."
    exit 1
fi

PYTHON_BIN="$VENV_DIR/bin/python"

# Cek apakah sudah ada instance yang berjalan
if [ -f "pids/userbot.pid" ]; then
    EXISTING_USERBOT_PID=$(cat pids/userbot.pid 2>/dev/null || echo "")
    if [ -n "$EXISTING_USERBOT_PID" ] && kill -0 "$EXISTING_USERBOT_PID" 2>/dev/null; then
        print_color $YELLOW "⚠️  Userbot Service sudah berjalan dengan PID: $EXISTING_USERBOT_PID"
        print_color $YELLOW "Silakan hentikan terlebih dahulu dengan: kill $EXISTING_USERBOT_PID"
        exit 1
    else
        print_color $BLUE "🔍 Menemukan file PID userbot yang tidak valid, menghapus..."
        rm -f pids/userbot.pid
    fi
fi

# Buat direktori yang diperlukan
mkdir -p logs
mkdir -p pids

# Jalankan Userbot Service dengan timeout
print_color $CYAN "🤖 Menjalankan Userbot Service dengan timeout $TIMEOUT_DURATION detik..."
print_color $CYAN "📝 Log akan ditulis ke: logs/userbot.log"
print_color $YELLOW "⚠️  Tekan Ctrl+C untuk menghentikan."

# Jalankan dengan timeout
if [ "$TIMEOUT_DURATION" -gt 0 ]; then
    timeout "$TIMEOUT_DURATION" "$PYTHON_BIN" -m services.userbot.main > logs/userbot.log 2>&1 &
    USERBOT_PID=$!
    print_color $GREEN "✅ Userbot Service berjalan dengan PID: $USERBOT_PID"
    
    # Tunggu proses selesai atau timeout
    wait "$USERBOT_PID"
    EXIT_CODE=$?
    
    if [ "$EXIT_CODE" -eq 124 ]; then
        print_color $YELLOW "⏱️  Userbot Service dihentikan setelah $TIMEOUT_DURATION detik (timeout)."
    elif [ "$EXIT_CODE" -ne 0 ]; then
        print_color $RED "❌ Userbot Service berhenti dengan kode error: $EXIT_CODE"
    fi
else
    # Jika timeout = 0, jalankan tanpa timeout
    "$PYTHON_BIN" -m services.userbot.main > logs/userbot.log 2>&1 &
    USERBOT_PID=$!
    print_color $GREEN "✅ Userbot Service berjalan dengan PID: $USERBOT_PID"
    
    # Tampilkan log jika diminta
    if [ "$TAIL_FOLLOW" = true ]; then
        print_color $CYAN "📊 Menampilkan log real-time (tekan Ctrl+C untuk berhenti):"
        tail -n "$TAIL_LINES" -f logs/userbot.log &
        TAIL_PID=$!
        trap "kill $TAIL_PID 2>/dev/null || true" SIGINT SIGTERM EXIT
        wait "$TAIL_PID"
    else
        # Tunggu proses userbot selesai
        wait "$USERBOT_PID"
    fi
fi