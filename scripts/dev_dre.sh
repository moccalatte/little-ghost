#!/bin/bash
# Wrapper dev script khusus Dre dengan timeout dan duration.
# Memastikan hanya berjalan pada sesi terminal interaktif milik user.

set -euo pipefail

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
TIMEOUT_DURATION=${TIMEOUT_DURATION:-7200}  # Default 2 jam untuk mode Dre

if [ ! -t 0 ]; then
  print_color $RED "❌ Script ini hanya boleh dijalankan langsung dari terminal user." >&2
  exit 1
fi

print_color $BOLD $PURPLE "🎭 Script pengembangan Little Ghost (mode Dre)."
read -r -p "$(print_color $CYAN "Ketik 'dre' untuk melanjutkan: ")" confirm
if [ "$confirm" != "dre" ]; then
    print_color $RED "❌ Dibatalkan."
    exit 1
fi

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# Jalankan dengan timeout dan follow-logs
timeout "$TIMEOUT_DURATION" "$SCRIPT_DIR/dev.sh" --follow-logs "$@"
EXIT_CODE=$?

if [ "$EXIT_CODE" -eq 124 ]; then
    print_color $YELLOW "⏱️  Script dihentikan setelah $TIMEOUT_DURATION detik (timeout)."
elif [ "$EXIT_CODE" -ne 0 ]; then
    print_color $RED "❌ Script berhenti dengan kode error: $EXIT_CODE"
fi
