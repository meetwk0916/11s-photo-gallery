#!/usr/bin/env python3
"""Verify prerequisites for the 11去哪玩 local MVP and optional Drive mode."""

import importlib
import os
import shutil
import sys
from pathlib import Path


def has_module(module_name: str) -> bool:
    try:
        importlib.import_module(module_name)
        return True
    except ImportError:
        return False


def check() -> bool:
    print("Checking 11去哪玩 MVP setup")
    print("=" * 50)
    print(f"Python: {sys.version.split()[0]}")

    ok = True

    project_root = Path(__file__).resolve().parent
    if (project_root / ".venv" / "bin" / "python").exists():
        print("✓ Local virtual environment found (.venv)")
    elif Path.home().joinpath(".local/bin/virtualenv").exists() or shutil.which("virtualenv"):
        print("✓ virtualenv helper available for bootstrapping a local .venv")
    else:
        print("⚠ No local .venv found and no virtualenv helper detected")

    hermes_home = Path.home() / ".hermes"
    token_path = hermes_home / "google_token.json"
    if token_path.exists():
        print("✓ Google OAuth token found (Drive mode available)")
    else:
        print("⚠ Google OAuth token not found - Drive watcher/export are disabled, local upload MVP is still available")

    has_key = False
    for key_name in ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"]:
        if os.environ.get(key_name):
            print(f"✓ {key_name} is set")
            has_key = True

    if not has_key:
        print("⚠ No AI API key set - the app will use the built-in travel fallback generator")

    for module_name, label, required in [
        ("flask", "Flask", True),
        ("flask_socketio", "Flask-SocketIO", True),
        ("google.oauth2", "Google OAuth client", False),
    ]:
        if has_module(module_name):
            print(f"✓ {label} installed")
        else:
            level = "✗" if required else "⚠"
            print(f"{level} {label} missing")
            ok = ok and not required

    print("\n" + "=" * 50)
    if ok:
        print("Setup is sufficient for the local MVP. Run ./run.sh foreground or ./run.sh start")
    else:
        print("Missing required dependencies. Create .venv and install requirements.txt first.")

    return ok


if __name__ == "__main__":
    raise SystemExit(0 if check() else 1)
