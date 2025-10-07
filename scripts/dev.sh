#!/bin/bash

# Script untuk menjalankan lingkungan pengembangan Little Ghost

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

TAIL_FOLLOW=true
TAIL_LINES=40
TAIL_DURATION=20
DETACH=false
TAIL_PID=""

for arg in "$@"; do
  case "$arg" in
    --no-tail)
      TAIL_FOLLOW=false
      ;;
    --tail-lines=*)
      TAIL_LINES="${arg#*=}"
      ;;
    --tail-duration=*)
      TAIL_DURATION="${arg#*=}"
      ;;
    --follow-logs)
      TAIL_DURATION=0
      ;;
    --detach)
      DETACH=true
      TAIL_FOLLOW=false
      ;;
    *)
      echo "Peringatan: argumen tidak dikenali '$arg' diabaikan." >&2
      ;;
  esac
done

case "$TAIL_LINES" in
  ''|*[!0-9]*)
    echo "Nilai untuk --tail-lines harus berupa angka >= 0." >&2
    exit 1
    ;;
esac

case "$TAIL_DURATION" in
  ''|*[!0-9]*)
    echo "Nilai untuk --tail-duration harus berupa angka >= 0." >&2
    exit 1
    ;;
esac

PYTHON_BIN=${PYTHON_BIN:-python3}

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Gagal menemukan interpreter: $PYTHON_BIN"
  exit 1
fi

VENV_DIR=".venv"

if [ ! -d "$VENV_DIR" ] || [ ! -x "$VENV_DIR/bin/python" ]; then
  echo "Menyiapkan virtual environment di $VENV_DIR..."
  if ! "$PYTHON_BIN" -m venv --without-pip "$VENV_DIR" >/dev/null 2>&1; then
    echo "Gagal membuat virtual environment. Pastikan paket python3-venv sudah terpasang."
    exit 1
  fi
fi

PYTHON_BIN="$VENV_DIR/bin/python"

if [ ! -x "$PYTHON_BIN" ]; then
  echo "Virtual environment tidak valid: $VENV_DIR"
  exit 1
fi

if [ ! -x "$VENV_DIR/bin/pip" ]; then
  echo "Menyiapkan pip di dalam virtual environment..."
  GET_PIP_PATH="$VENV_DIR/get-pip.py"
  if command -v curl >/dev/null 2>&1; then
    if ! curl -fsSL https://bootstrap.pypa.io/get-pip.py -o "$GET_PIP_PATH"; then
      echo "Gagal mengunduh get-pip.py. Periksa koneksi internet Anda."
      exit 1
    fi
  elif command -v wget >/dev/null 2>&1; then
    if ! wget -q -O "$GET_PIP_PATH" https://bootstrap.pypa.io/get-pip.py; then
      echo "Gagal mengunduh get-pip.py. Periksa koneksi internet Anda."
      exit 1
    fi
  else
    echo "Tidak menemukan curl maupun wget untuk mengunduh pip. Unduh get-pip.py secara manual ke $GET_PIP_PATH."
    exit 1
  fi

  if ! "$PYTHON_BIN" "$GET_PIP_PATH"; then
    echo "Gagal menjalankan get-pip.py di virtual environment."
    exit 1
  fi

  rm -f "$GET_PIP_PATH"
fi

PIP_BASE=("$PYTHON_BIN" -m pip)

cleanup() {
  trap - SIGINT SIGTERM EXIT
  if [ "$DETACH" = true ]; then
    return
  fi
  if [ -n "${WIZARD_PID:-}" ]; then
    kill "$WIZARD_PID" 2>/dev/null || true
  fi
  if [ -n "${USERBOT_PID:-}" ]; then
    kill "$USERBOT_PID" 2>/dev/null || true
  fi
  if [ -n "${TAIL_PID:-}" ]; then
    kill "$TAIL_PID" 2>/dev/null || true
  fi
}

trap cleanup SIGINT SIGTERM EXIT

# 1. Instal dependensi
print_color $CYAN "🔧 Menginstal dependensi dari requirements.txt..."
if ! "${PIP_BASE[@]}" install --upgrade pip; then
    print_color $RED "❌ Gagal memperbarui pip di dalam virtual environment."
    exit 1
fi

if ! "${PIP_BASE[@]}" install -r requirements.txt; then
    print_color $RED "❌ Gagal menginstal dependensi dari requirements.txt."
    exit 1
fi

print_color $GREEN "✅ Instalasi selesai."
echo ""

mkdir -p logs
mkdir -p pids

# 2. Cek apakah sudah ada instance yang berjalan
if [ -f "pids/wizard.pid" ]; then
    EXISTING_WIZARD_PID=$(cat pids/wizard.pid 2>/dev/null || echo "")
    if [ -n "$EXISTING_WIZARD_PID" ] && kill -0 "$EXISTING_WIZARD_PID" 2>/dev/null; then
        print_color $YELLOW "⚠️  Wizard Bot sudah berjalan dengan PID: $EXISTING_WIZARD_PID"
        print_color $YELLOW "Silakan hentikan terlebih dahulu dengan: kill $EXISTING_WIZARD_PID"
        exit 1
    else
        print_color $BLUE "🔍 Menemukan file PID wizard yang tidak valid, menghapus..."
        rm -f pids/wizard.pid
    fi
fi

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

# 3. Jalankan Wizard Bot di background
print_color $PURPLE "🧙‍♂️ Menjalankan Wizard Bot..."
"$PYTHON_BIN" -m services.wizard.main > logs/wizard.log 2>&1 &
WIZARD_PID=$!
print_color $GREEN "✅ Wizard Bot berjalan dengan PID: $WIZARD_PID"
echo ""

# 4. Jalankan Userbot di background
# Tambahkan jeda singkat untuk memastikan wizard siap terlebih dahulu jika diperlukan
sleep 2
print_color $CYAN "🤖 Menjalankan Userbot Service..."
"$PYTHON_BIN" -m services.userbot.main > logs/userbot.log 2>&1 &
USERBOT_PID=$!
print_color $GREEN "✅ Userbot Service berjalan dengan PID: $USERBOT_PID"
echo ""

# 5. Tunggu sebentar untuk memastikan kedua service berjalan dengan benar
sleep 3

# 6. Verifikasi bahwa kedua service masih berjalan
if ! kill -0 "$WIZARD_PID" 2>/dev/null; then
    print_color $RED "⚠️  WARNING: Wizard Bot tidak berjalan dengan benar. Periksa logs/wizard.log"
fi

if ! kill -0 "$USERBOT_PID" 2>/dev/null; then
    print_color $RED "⚠️  WARNING: Userbot Service tidak berjalan dengan benar. Periksa logs/userbot.log"
fi

# 4. Tampilkan log secara real-time
print_color $BOLD $WHITE "🎉 Setup selesai. Menampilkan log gabungan (tekan Ctrl+C untuk berhenti):"
print_color $BLUE "----------------------------------------------------"
# Buat direktori log terlebih dahulu jika belum ada
mkdir -p logs
touch logs/wizard.log logs/userbot.log

if [ "$TAIL_FOLLOW" = true ] && [ "$DETACH" = false ]; then
  if [ "${TAIL_DURATION}" -gt 0 ] 2>/dev/null; then
    print_color $CYAN "📊 Menampilkan log gabungan selama ${TAIL_DURATION} detik..."
    timeout "$TAIL_DURATION" tail -n "$TAIL_LINES" -f logs/wizard.log logs/userbot.log
    EXIT_CODE=$?
    if [ "$EXIT_CODE" -eq 124 ]; then
      print_color $YELLOW "⏱️  Pemantauan log otomatis dihentikan setelah $TAIL_DURATION detik."
    fi
  else
    tail -n "$TAIL_LINES" -f logs/wizard.log logs/userbot.log &
    TAIL_PID=$!
    wait "$TAIL_PID"
  fi
elif [ "$TAIL_FOLLOW" = false ] && [ "$DETACH" = false ]; then
  tail -n "$TAIL_LINES" logs/wizard.log logs/userbot.log
  print_color $BLUE "ℹ️  Tail log dilewati sesuai opsi --no-tail."
else
  print_color $BLUE "ℹ️  Layanan dijalankan dalam mode detach; tail log dilewati."
fi

if [ "$DETACH" = true ]; then
  print_color $GREEN "✅ Wizard dan Userbot tetap berjalan di latar belakang. Gunakan 'pkill -f services\.wizard\.main' bila ingin menghentikan."
fi
