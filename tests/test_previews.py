import sys
from unittest.mock import MagicMock

# Mock dependencies
sys.modules["flask"] = MagicMock()
sys.modules["flask_socketio"] = MagicMock()
sys.modules["google.auth.transport.requests"] = MagicMock()
sys.modules["google.oauth2.credentials"] = MagicMock()
sys.modules["googleapiclient.discovery"] = MagicMock()
sys.modules["googleapiclient.http"] = MagicMock()

import pytest
from app import build_xiaohongshu_preview, build_instagram_preview, build_linkedin_preview, PhotoPost, state
from config import PipelineConfig

@pytest.fixture
def mock_post():
    return PhotoPost(
        id="test_post",
        file_name="test.jpg",
        drive_id="drive_123",
        local_path=None,
        image_base64="YmFzZTY0ZGF0YQ==", # "base64data"
        vision_analysis={},
        generated_content={},
        platform_previews={},
        status="ready",
        tone_key="warm_friend",
        platforms=["xiaohongshu", "instagram", "linkedin"],
        scheduled_at=None,
        created_at="2023-01-01T00:00:00",
        updated_at="2023-01-01T00:00:00"
    )

def test_xiaohongshu_preview_uses_config(mock_post):
    state.config = PipelineConfig(
        author_name="Test Author",
        author_followers="10k"
    )
    content = {"xiaohongshu": {"body": "Test Body"}}
    preview = build_xiaohongshu_preview(mock_post, content)

    assert preview["author"]["name"] == "Test Author"
    assert preview["author"]["followers"] == "10k"
    assert preview["likes"] == state.config.dummy_stats["xiaohongshu"]["likes"]

def test_instagram_preview_uses_config(mock_post):
    state.config = PipelineConfig(
        author_handle="test.handle"
    )
    content = {"instagram": {"caption": "Test Caption"}}
    preview = build_instagram_preview(mock_post, content)

    assert preview["username"] == "test.handle"
    assert preview["likes"] == state.config.dummy_stats["instagram"]["likes"]

def test_linkedin_preview_uses_config(mock_post):
    state.config = PipelineConfig(
        author_name="LinkedIn Name",
        author_headline="Expert"
    )
    content = {"linkedin": {"body": "Test Body"}}
    preview = build_linkedin_preview(mock_post, content)

    assert preview["author_name"] == "LinkedIn Name"
    assert preview["author_headline"] == "Expert"
    assert preview["likes"] == state.config.dummy_stats["linkedin"]["likes"]
