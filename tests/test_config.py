import os
import pytest
from config import PipelineConfig

def test_pipeline_config_defaults():
    config = PipelineConfig()
    assert config.author_name == "Your Name"
    assert config.author_followers == "5.2k"
    assert config.dummy_likes_xhs == "1.2k"

def test_pipeline_config_env_overrides(monkeypatch):
    monkeypatch.setenv("AUTHOR_NAME", "Alice")
    monkeypatch.setenv("AUTHOR_FOLLOWERS", "10k")
    monkeypatch.setenv("AUTHOR_HANDLE", "alice.wonderland")

    config = PipelineConfig()

    assert config.author_name == "Alice"
    assert config.author_followers == "10k"
    assert config.author_handle == "alice.wonderland"
