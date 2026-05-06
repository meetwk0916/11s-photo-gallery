#!/bin/bash
# 11去哪玩 - startup script
# Usage: ./run.sh [start|stop|status|foreground]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
PIDFILE="$SCRIPT_DIR/app.pid"
LOGFILE="$SCRIPT_DIR/app.log"
USER_VIRTUALENV="$HOME/.local/bin/virtualenv"

COMMAND="${1:-start}"

ensure_env() {
  if [ -x "$VENV_DIR/bin/python" ]; then
    return 0
  fi

  echo "Preparing Python environment..."

  if python3 -m venv "$VENV_DIR" >/dev/null 2>&1; then
    return 0
  fi

  if [ -x "$USER_VIRTUALENV" ]; then
    "$USER_VIRTUALENV" "$VENV_DIR"
    return 0
  fi

  cat <<'EOF'
Unable to create .venv automatically.

Option 1 (recommended):
  sudo apt install python3.12-venv

Option 2 (user-local, no sudo):
  curl -fsSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py
  python3 /tmp/get-pip.py --user --break-system-packages
  ~/.local/bin/pip install --user --break-system-packages virtualenv

Then rerun ./run.sh.
EOF
  exit 1
}

install_deps() {
  source "$VENV_DIR/bin/activate"
  python -m pip install -q -r "$SCRIPT_DIR/requirements.txt"
}

print_runtime_notes() {
  echo "11去哪玩 photo pipeline"
  echo "================================"
  echo "Open: http://localhost:5000"

  if [ -z "$ANTHROPIC_API_KEY" ] && [ -z "$OPENAI_API_KEY" ] && [ -z "$GEMINI_API_KEY" ]; then
    echo "No AI API key detected. The app will use the built-in travel fallback generator."
  fi

  if [ ! -f "$HOME/.hermes/google_token.json" ]; then
    echo "Google OAuth token not found. Drive watcher/export are disabled; local upload mode is still available."
  fi

  echo ""
}

start_background() {
  if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "Server is already running (PID: $(cat "$PIDFILE"))"
    echo "Open: http://localhost:5000"
    exit 0
  fi

  ensure_env
  install_deps
  print_runtime_notes

  nohup "$VENV_DIR/bin/python" "$SCRIPT_DIR/app.py" > "$LOGFILE" 2>&1 &
  echo $! > "$PIDFILE"
  echo "Server started with PID $(cat "$PIDFILE"). Logs: $LOGFILE"
}

start_foreground() {
  ensure_env
  install_deps
  print_runtime_notes
  exec "$VENV_DIR/bin/python" "$SCRIPT_DIR/app.py"
}

case "$COMMAND" in
  start)
    start_background
    ;;

  stop)
    if [ -f "$PIDFILE" ]; then
      PID=$(cat "$PIDFILE")
      if kill -0 "$PID" 2>/dev/null; then
        echo "Stopping server (PID: $PID)..."
        kill "$PID"
        rm -f "$PIDFILE"
        echo "Server stopped."
      else
        echo "PID $PID is not running."
        rm -f "$PIDFILE"
      fi
    else
      echo "Server is not running (no PID file found)."
    fi
    ;;

  status)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "Server is running (PID: $(cat "$PIDFILE"))"
      echo "Open: http://localhost:5000"
    else
      echo "Server is not running"
      rm -f "$PIDFILE" 2>/dev/null
    fi
    ;;

  foreground|fg)
    start_foreground
    ;;

  *)
    echo "Usage: $0 [start|stop|status|foreground]"
    echo "  start      - Start server in background (default)"
    echo "  stop       - Stop background server"
    echo "  status     - Check if server is running"
    echo "  foreground - Start server in foreground"
    ;;
esac
