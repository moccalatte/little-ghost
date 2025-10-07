#!/bin/bash

# Script to run the Little Ghost development environment

set -u -o pipefail

# Colors for terminal output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
WHITE='\033[0;37m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Function to print text with color
print_color() {
    local color=$1
    local text=$2
    echo -e "${color}${text}${NC}"
}

# --- Argument Parsing ---
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
      print_color $YELLOW "Warning: unrecognized argument '$arg' ignored." >&2
      ;;
  esac
done

case "$TAIL_LINES" in
  ''|*[!0-9]*)
    print_color $RED "Value for --tail-lines must be a number >= 0." >&2
    exit 1
    ;;
esac

case "$TAIL_DURATION" in
  ''|*[!0-9]*)
    print_color $RED "Value for --tail-duration must be a number >= 0." >&2
    exit 1
    ;;
esac

# --- Cleanup Function ---
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

# --- Pre-run Checks ---
print_color $BLUE "🔎 Performing pre-run checks..."

# 1. Check for .env file
if [ ! -f ".env" ]; then
    print_color $RED "❌ .env file not found."
    print_color $YELLOW "Please copy .env.example to .env and fill in your credentials."
    exit 1
fi

# 2. Check for requirements.txt
if [ ! -f "requirements.txt" ]; then
    print_color $RED "❌ requirements.txt not found. Cannot install dependencies."
    exit 1
fi

# 3. Create necessary directories
print_color $BLUE "🔧 Creating required directories (data, logs, pids)..."
mkdir -p data logs pids
print_color $GREEN "✅ Checks complete."
echo ""

# --- Virtual Environment Setup ---
PYTHON_BIN=${PYTHON_BIN:-python3}

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  print_color $RED "Failed to find interpreter: $PYTHON_BIN"
  exit 1
fi

VENV_DIR=".venv"

if [ ! -d "$VENV_DIR" ] || [ ! -x "$VENV_DIR/bin/python" ]; then
  print_color $YELLOW "Setting up virtual environment in $VENV_DIR..."
  if ! "$PYTHON_BIN" -m venv "$VENV_DIR" >/dev/null 2>&1; then
    print_color $RED "Failed to create virtual environment. Make sure the python3-venv package is installed."
    exit 1
  fi
fi

PYTHON_BIN="$VENV_DIR/bin/python"
PIP_BIN="$VENV_DIR/bin/pip"

if [ ! -x "$PYTHON_BIN" ]; then
  print_color $RED "Invalid virtual environment: $VENV_DIR"
  exit 1
fi

# --- Dependency Installation ---
print_color $CYAN "📦 Installing dependencies from requirements.txt..."
if ! "$PIP_BIN" install --upgrade pip > /dev/null 2>&1; then
    print_color $RED "❌ Failed to upgrade pip in the virtual environment."
    exit 1
fi

if ! "$PIP_BIN" install -r requirements.txt > /dev/null 2>&1; then
    print_color $RED "❌ Failed to install dependencies from requirements.txt."
    exit 1
fi

print_color $GREEN "✅ Installation complete."
echo ""

# --- Process Management ---
# 1. Check for existing running instances
if [ -f "pids/wizard.pid" ]; then
    EXISTING_WIZARD_PID=$(cat pids/wizard.pid 2>/dev/null || echo "")
    if [ -n "$EXISTING_WIZARD_PID" ] && kill -0 "$EXISTING_WIZARD_PID" 2>/dev/null; then
        print_color $YELLOW "⚠️  Wizard Bot is already running with PID: $EXISTING_WIZARD_PID"
        print_color $YELLOW "Please stop it first with: kill $EXISTING_WIZARD_PID"
        exit 1
    else
        print_color $BLUE "🔍 Found an invalid wizard PID file, removing..."
        rm -f pids/wizard.pid
    fi
fi

if [ -f "pids/userbot.pid" ]; then
    EXISTING_USERBOT_PID=$(cat pids/userbot.pid 2>/dev/null || echo "")
    if [ -n "$EXISTING_USERBOT_PID" ] && kill -0 "$EXISTING_USERBOT_PID" 2>/dev/null; then
        print_color $YELLOW "⚠️  Userbot Service is already running with PID: $EXISTING_USERBOT_PID"
        print_color $YELLOW "Please stop it first with: kill $EXISTING_USERBOT_PID"
        exit 1
    else
        print_color $BLUE "🔍 Found an invalid userbot PID file, removing..."
        rm -f pids/userbot.pid
    fi
fi

# 2. Run Wizard Bot in the background
print_color $PURPLE "🧙‍♂️ Starting Wizard Bot..."
"$PYTHON_BIN" -m services.wizard.main > logs/wizard.log 2>&1 &
WIZARD_PID=$!
echo $WIZARD_PID > pids/wizard.pid
print_color $GREEN "✅ Wizard Bot is running with PID: $WIZARD_PID"
echo ""

# 3. Run Userbot in the background
sleep 2
print_color $CYAN "🤖 Starting Userbot Service..."
"$PYTHON_BIN" -m services.userbot.main > logs/userbot.log 2>&1 &
USERBOT_PID=$!
echo $USERBOT_PID > pids/userbot.pid
print_color $GREEN "✅ Userbot Service is running with PID: $USERBOT_PID"
echo ""

sleep 3

# 4. Verify that both services are still running
if ! kill -0 "$WIZARD_PID" 2>/dev/null; then
    print_color $RED "⚠️  WARNING: Wizard Bot did not start correctly. Check logs/wizard.log"
fi

if ! kill -0 "$USERBOT_PID" 2>/dev/null; then
    print_color $RED "⚠️  WARNING: Userbot Service did not start correctly. Check logs/userbot.log"
fi

# --- Log Tailing ---
print_color $BOLD $WHITE "🎉 Setup complete. Displaying combined logs (press Ctrl+C to stop):"
print_color $BLUE "----------------------------------------------------"
touch logs/wizard.log logs/userbot.log

if [ "$TAIL_FOLLOW" = true ] && [ "$DETACH" = false ]; then
  if [ "${TAIL_DURATION}" -gt 0 ] 2>/dev/null; then
    print_color $CYAN "📊 Tailing combined logs for ${TAIL_DURATION} seconds..."
    timeout "$TAIL_DURATION" tail -n "$TAIL_LINES" -f logs/wizard.log logs/userbot.log
    EXIT_CODE=$?
    if [ "$EXIT_CODE" -eq 124 ]; then
      print_color $YELLOW "⏱️  Automatic log monitoring stopped after $TAIL_DURATION seconds."
    fi
  else
    tail -n "$TAIL_LINES" -f logs/wizard.log logs/userbot.log &
    TAIL_PID=$!
    wait "$TAIL_PID"
  fi
elif [ "$TAIL_FOLLOW" = false ] && [ "$DETACH" = false ]; then
  tail -n "$TAIL_LINES" logs/wizard.log logs/userbot.log
  print_color $BLUE "ℹ️  Log tailing skipped as per --no-tail option."
else
  print_color $BLUE "ℹ️  Services started in detach mode; log tailing skipped."
fi

if [ "$DETACH" = true ]; then
  print_color $GREEN "✅ Wizard and Userbot are running in the background. Use 'pkill -f services.wizard.main' and 'pkill -f services.userbot.main' to stop them."
fi