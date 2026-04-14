#!/bin/bash
# 小红书 Photo Content Pipeline - Startup Script

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"

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

# Run the app
echo "🌐 Starting web server..."
echo "Open: http://localhost:5000"
echo ""
python3 app.py
