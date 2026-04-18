import sys
from unittest.mock import MagicMock

# Mock out external dependencies
sys.modules['flask'] = MagicMock()
sys.modules['flask_socketio'] = MagicMock()
sys.modules['google.auth.transport.requests'] = MagicMock()
sys.modules['google.oauth2.credentials'] = MagicMock()
sys.modules['googleapiclient.discovery'] = MagicMock()
sys.modules['googleapiclient.http'] = MagicMock()
sys.modules['flask.app'] = MagicMock()
sys.modules['eventlet'] = MagicMock()

# Mock out socketio components that the app imports
mock_socketio = MagicMock()
sys.modules['flask_socketio'].SocketIO = MagicMock(return_value=mock_socketio)
sys.modules['flask_socketio'].emit = MagicMock()

import app

def test_build_xiaohongshu_preview():
    # Setup mock post and content
    post = MagicMock()
    post.image_base64 = "dummy_base64"
    content = {
        "xiaohongshu": {
            "title_options": ["Test Title"],
            "body": "Test Body",
            "hashtags": ["#test"],
            "music_suggestion": "Test Music"
        }
    }

    # Update state config
    app.state.config.author_name = "Test Author Name"
    app.state.config.author_followers = "10k"

    preview = app.build_xiaohongshu_preview(post, content)

    assert preview["author"]["name"] == "Test Author Name"
    assert preview["author"]["followers"] == "10k"

def test_build_instagram_preview():
    post = MagicMock()
    post.image_base64 = "dummy_base64"
    content = {
        "instagram": {
            "caption": "Test Caption",
            "hashtags": ["#igtest"],
            "location_tag": "Test Location",
            "story_text": "Test Story"
        }
    }

    app.state.config.author_handle = "test.handle"

    preview = app.build_instagram_preview(post, content)

    assert preview["username"] == "test.handle"

def test_build_linkedin_preview():
    post = MagicMock()
    post.image_base64 = "dummy_base64"
    content = {
        "linkedin": {
            "hook": "Test Hook",
            "body": "Test Body",
            "takeaway": "Test Takeaway",
            "hashtags": ["#linkedin"],
            "cta": "Test CTA"
        }
    }

    app.state.config.author_name = "Test LinkedIn Author"
    app.state.config.author_headline = "Test Headline"

    preview = app.build_linkedin_preview(post, content)

    assert preview["author_name"] == "Test LinkedIn Author"
    assert preview["author_headline"] == "Test Headline"
