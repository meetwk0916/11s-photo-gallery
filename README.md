# 小红书 Photo Content Pipeline 🚀

An AI-powered content generation pipeline that automatically creates Xiaohongshu (小红书) style posts from your Google Drive photos.

![Screenshot Placeholder]

## Features

✨ **Automatic Photo Detection** - Watches your Google Drive "selected" folder  
🤖 **AI-Powered Content Generation** - Uses Claude/GPT-4o/Gemini vision APIs  
📱 **Real-time Preview** - See exactly how your post will look on Xiaohongshu  
✏️ **Interactive Editor** - Fine-tune titles, captions, and hashtags  
💾 **Export to Drive** - Save generated content back to Google Drive  
🎨 **Multiple Writing Styles** - Warm friend, trendy sister, lifestyle blogger, luxury minimal

## Quick Start

### 1. Install & Run

```bash
cd "/Users/walterwan90/Documents/Photo processor/xiaohongshu_pipeline"
chmod +x run.sh
./run.sh
```

Or manually:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 app.py
```

Open http://localhost:5000 in your browser.

### 2. Configure AI Provider

In the web UI or via environment variable:

```bash
# Option 1: Anthropic Claude (recommended)
export ANTHROPIC_API_KEY="sk-..."

# Option 2: OpenAI GPT-4o
export OPENAI_API_KEY="sk-..."

# Option 3: Google Gemini
export GEMINI_API_KEY="..."
```

### 3. Add Photos to Drive

1. Open Google Drive
2. Navigate to `Photo Content/Photos-to-Process/`
3. Upload your photos to `draft/` or directly to `selected/`
4. Click "开始监控" in the web UI
5. Photos in `selected/` will be automatically detected

### 4. Generate Content

1. Select a photo from the queue
2. Choose a writing style (温暖闺蜜, 潮流辣妹, etc.)
3. Click "生成小红书内容"
4. Watch the real-time preview on the phone mockup
5. Edit as needed, then copy or save to Drive

## Folder Structure (Auto-Created in Drive)

```
Photo Content/
├── Photos-to-Process/
│   ├── draft/              # Drop new photos here
│   ├── selected/           # Pipeline watches this folder
│   └── processed/          # Processed photos moved here
├── Content-Output/
│   └── xiaohongshu-posts/  # Generated .md files
└── content-manifest.json   # Tracking file
```

## Writing Styles

| Style | Description | Best For |
|-------|-------------|----------|
| 温暖闺蜜 (warm_friend) | Casual, friendly, uses "姐妹" | Daily life, food, lifestyle |
| 潮流辣妹 (trendy_sister) | Bold, confident, trendy | Fashion, OOTD, nightlife |
| 生活博主 (lifestyle_blogger) | Refined, aesthetic, tips | Travel, home, wellness |
| 高级简约 (luxury_minimal) | Minimal, elegant, English | Art, design, luxury products |

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│ Google Drive │────▶│  Pipeline    │────▶│   AI Vision │
│  (photos)   │     │  (watcher)   │     │   (Claude/  │
└─────────────┘     └──────────────┘     │   GPT/Gemini)│
                                                │
                       ┌─────────────────────────┘
                       ▼
               ┌──────────────┐
               │  Web UI      │
               │  (Vue.js +   │
               │   Flask)     │
               └──────────────┘
                       │
                       ▼
               ┌──────────────┐
               │  Xiaohongshu │
               │  Preview     │
               └──────────────┘
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | Get pipeline status |
| `/api/posts` | GET | List all photos/posts |
| `/api/config` | POST | Update configuration |
| `/api/generate` | POST | Generate content for a photo |
| `/api/preview/<id>` | GET | Get preview data |
| `/api/update-content` | POST | Edit generated content |
| `/api/export/<id>` | POST | Save to Drive |

## Environment Variables

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Claude API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `GEMINI_API_KEY` | Google Gemini API key |
| `DRIVE_ROOT_FOLDER` | Root folder name (default: "Photo Content") |
| `CHECK_INTERVAL` | Seconds between Drive checks (default: 30) |

## Troubleshooting

### "No API key detected"
- Add API key in the web UI Config panel, or
- Set environment variable before running

### "Token not found"
- Make sure you've completed Google OAuth setup
- Check that `~/.hermes/google_token.json` exists

### Photos not appearing
- Verify photos are in `selected/` folder, not `draft/`
- Check that the Drive folder structure was created
- Click "开始监控" to start the watcher

### Content generation fails
- Verify your API key is valid and has credit
- Check the Python console for error details
- Try a different AI provider

## Customization

### Add New Writing Styles

Edit `config.py` and add to `XIAOHONGSHU_TONES`:

```python
"foodie_guru": {
    "name": "美食探店",
    "style_description": "热情推荐，突出食物细节和口感",
    "opening_phrases": ["吃货们看过来！", "这家店绝了！"],
    ...
}
```

### Modify Prompt Templates

Edit `ai_generator.py` - function `build_xiaohongshu_prompt()`

### Change Default Settings

Edit `config.py` - class `PipelineConfig`

## Development

```bash
# Run in debug mode
FLASK_DEBUG=1 python3 app.py

# Install dev dependencies
pip install black flake8 pytest
```

## Roadmap

- [ ] Batch processing multiple photos
- [ ] Integration with Google Photos Picker API
- [ ] Auto-scheduling for optimal posting times
- [ ] Analytics dashboard for post performance
- [ ] Multi-language support (English, Japanese, etc.)
- [ ] Integration with XiaoHongshu API (if available)

## License

MIT License - Feel free to modify and distribute.

## Credits

Built with:
- Flask + SocketIO
- Vue.js 3
- Google Drive API
- Claude / GPT-4o / Gemini Vision
- 小红书 (Xiaohongshu) for the UI inspiration

---

Made with ❤️ for content creators who want to streamline their workflow.
