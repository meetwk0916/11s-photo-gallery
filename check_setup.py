#!/usr/bin/env python3
"""Verify that all prerequisites are met for the 小红书 Photo Pipeline."""

import os
import sys

def check():
    print("🔍 Checking 小红书 Photo Pipeline Setup")
    print("=" * 50)
    
    # Check Python version
    print(f"\n✓ Python {sys.version.split()[0]}")
    
    # Check for Google token
    hermes_home = os.path.expanduser("~/.hermes")
    token_path = os.path.join(hermes_home, "google_token.json")
    if os.path.exists(token_path):
        print("✓ Google token found")
    else:
        print("✗ Google token NOT found - run OAuth setup first")
        return False
    
    # Check for API keys
    has_key = False
    if os.environ.get("ANTHROPIC_API_KEY"):
        print("✓ ANTHROPIC_API_KEY set")
        has_key = True
    if os.environ.get("OPENAI_API_KEY"):
        print("✓ OPENAI_API_KEY set")
        has_key = True
    if os.environ.get("GEMINI_API_KEY"):
        print("✓ GEMINI_API_KEY set")
        has_key = True
    
    if not has_key:
        print("⚠ No AI API key set - you'll need to add one in the web UI")
    
    # Check dependencies
    try:
        import flask
        print("✓ Flask installed")
    except ImportError:
        print("✗ Flask not installed - run: pip install -r requirements.txt")
        return False
    
    try:
        import google.oauth2
        print("✓ Google API client installed")
    except ImportError:
        print("✗ Google API client not installed - run: pip install -r requirements.txt")
        return False
    
    print("\n" + "=" * 50)
    print("🎉 Setup looks good! Run ./run.sh to start")
    return True

if __name__ == "__main__":
    check()
