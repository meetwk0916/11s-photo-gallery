#!/bin/bash
# 小红书 Photo Content Pipeline - Startup Script
# Usage: ./run.sh [start|stop|status|foreground]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"
PIDFILE="$SCRIPT_DIR/app.pid"
LOGFILE="$SCRIPT_DIR/app.log"

COMMAND="${1:-start}"

case "$COMMAND" in
  start)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "🚀 Server is already running (PID: $(cat "$PIDFILE"))"
      echo "   Open: http://localhost:5000"
      exit 0
    fi

    echo "🚀 小红书 Photo Content Pipeline"
    echo "================================"

    # Check if virtual environment exists
    if [ ! -d "$VENV_DIR" ]; then
      echo "📦 Creating virtual environment..."
      python3 -m venv "$VENV_DIR"
    fi

    # Activate virtual environment
    source "$VENV_DIR/bin/activate"

    # Install/update dependencies
    echo "📥 Installing dependencies..."
    pip install -q -r requirements.txt

    # Check for API key
    if [ -z "$ANTHROPIC_API_KEY" ] && [ -z "$OPENAI_API_KEY" ] && [ -z "$GEMINI_API_KEY" ]; then
      echo ""
      echo "⚠️  Warning: No AI API key detected!"
      echo "Set one of these environment variables:"
      echo "  - ANTHROPIC_API_KEY (for Claude)"
      echo "  - OPENAI_API_KEY (for GPT-4o)"
      echo "  - GEMINI_API_KEY (for Gemini)"
      echo ""
      echo "You can also add it in the web UI after starting."
      echo ""
    fi

    # Run the app in background
    echo "🌐 Starting web server in background (Gunicorn + Eventlet)..."
    echo "Open: http://localhost:5000"
    echo ""
    nohup gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:5000 app:app > "$LOGFILE" 2>&1 &
    echo $! > "$PIDFILE"
    echo "Server started with PID $(cat "$PIDFILE"). Logs: $LOGFILE"
    ;;

  stop)
    if [ -f "$PIDFILE" ]; then
      PID=$(cat "$PIDFILE")
      if kill -0 "$PID" 2>/dev/null; then
        echo "🛑 Stopping server (PID: $PID)..."
        kill "$PID"
        rm -f "$PIDFILE"
        echo "Server stopped."
      else
        echo "⚠️ PID $PID is not running."
        rm -f "$PIDFILE"
      fi
    else
      echo "⚠️ Server is not running (no PID file found)."
    fi
    ;;

  status)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "🟢 Server is running (PID: $(cat "$PIDFILE"))"
      echo "   Open: http://localhost:5000"
    else
      echo "🔴 Server is not running"
      rm -f "$PIDFILE" 2>/dev/null
    fi
    ;;

  foreground|fg)
    echo "🌐 Starting web server in foreground (Gunicorn + Eventlet)..."
    echo "Open: http://localhost:5000"
    echo ""
    source "$VENV_DIR/bin/activate"
    gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:5000 app:app
    ;;

  *)
    echo "Usage: $0 [start|stop|status|foreground]"
    echo "  start      - Start server in background (default)"
    echo "  stop       - Stop background server"
    echo "  status     - Check if server is running"
    echo "  foreground - Start server in foreground (old behavior)"
    ;;
esac
