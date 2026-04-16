import pytest
from unittest.mock import MagicMock, patch

# Mock dependencies before importing app
import sys

# Create mocks for google.auth and googleapiclient
sys.modules['google.auth'] = MagicMock()
sys.modules['google.auth.transport.requests'] = MagicMock()
sys.modules['google.oauth2.credentials'] = MagicMock()
sys.modules['googleapiclient.discovery'] = MagicMock()
sys.modules['googleapiclient.http'] = MagicMock()

import app
from app import PhotoPost, build_xiaohongshu_preview, build_instagram_preview, build_linkedin_preview
from config import PipelineConfig

@pytest.fixture
def dummy_post():
    return PhotoPost(
        id="test_post",
        file_name="test.jpg",
        drive_id="test_drive_id",
        local_path=None,
        image_base64="dummy_base64",
        vision_analysis={},
        generated_content={},
        platform_previews={},
        status="ready",
        tone_key="warm_friend",
        platforms=["xiaohongshu", "instagram", "linkedin"],
        scheduled_at=None,
        created_at="now",
        updated_at="now"
    )

def test_build_xiaohongshu_preview(dummy_post, monkeypatch):
    # Set a config mock
    mock_config = PipelineConfig()
    mock_config.author_name = "XHS User"
    mock_config.dummy_likes_xhs = "999"
    monkeypatch.setattr(app.state, 'config', mock_config)

    content = {
        "platforms": {
            "xiaohongshu": {
                "title_options": ["My XHS Title"],
                "body": "This is XHS body.",
                "hashtags": ["#xhs"]
            }
        }
    }

    preview = build_xiaohongshu_preview(dummy_post, content)

    assert preview["title"] == "My XHS Title"
    assert preview["body"] == "This is XHS body."
    assert preview["likes"] == "999"
    assert preview["author"]["name"] == "XHS User"

def test_build_instagram_preview(dummy_post, monkeypatch):
    mock_config = PipelineConfig()
    mock_config.author_handle = "ig_user"
    mock_config.dummy_likes_ig = "888"
    monkeypatch.setattr(app.state, 'config', mock_config)

    content = {
        "platforms": {
            "instagram": {
                "caption": "My IG Caption",
                "hashtags": ["#ig"]
            }
        }
    }

    preview = build_instagram_preview(dummy_post, content)

    assert preview["caption"] == "My IG Caption"
    assert preview["likes"] == "888"
    assert preview["username"] == "ig_user"

def test_build_linkedin_preview(dummy_post, monkeypatch):
    mock_config = PipelineConfig()
    mock_config.author_name = "LI User"
    mock_config.dummy_likes_li = "777"
    mock_config.author_headline = "LI Headline"
    monkeypatch.setattr(app.state, 'config', mock_config)

    content = {
        "platforms": {
            "linkedin": {
                "hook": "My LI Hook",
                "body": "My LI Body"
            }
        }
    }

    preview = build_linkedin_preview(dummy_post, content)

    assert preview["hook"] == "My LI Hook"
    assert preview["body"] == "My LI Body"
    assert preview["likes"] == "777"
    assert preview["author_name"] == "LI User"
    assert preview["author_headline"] == "LI Headline"
