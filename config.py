"""Configuration for the Multi-Platform Photo Pipeline."""

import os
from dataclasses import dataclass
from typing import Optional

@dataclass
class PipelineConfig:
    # LLM Provider
    llm_provider: str = "anthropic"
    
    # API Keys
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    
    # Models
    openai_model: str = "gpt-4o"
    anthropic_model: str = "claude-sonnet-4-5"
    gemini_model: str = "gemini-2.5-flash"
    
    # Pipeline settings
    drive_root_folder: str = "Photo Content"
    check_interval_seconds: int = 30
    max_photos_per_batch: int = 10
    
    # Default platform settings
    default_platforms: list = None
    default_tone: str = "warm_friend"
    include_emoji: bool = True
    
    # Author settings
    author_name: str = "Your Name"
    author_handle: str = "your.handle"
    author_avatar: Optional[str] = None
    author_followers: str = "5.2k"
    author_headline: str = "Content Creator | Visual Storyteller"

    # Dummy Engagement Statistics
    dummy_likes_xhs: str = "1.2k"
    dummy_saves_xhs: str = "856"
    dummy_comments_xhs: str = "128"
    dummy_likes_ig: str = "2.4k"
    dummy_comments_ig: str = "42"
    dummy_likes_li: str = "328"
    dummy_comments_li: str = "18"
    dummy_reposts_li: str = "24"

    def __post_init__(self):
        self.openai_api_key = os.environ.get("OPENAI_API_KEY", self.openai_api_key)
        self.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", self.anthropic_api_key)
        self.gemini_api_key = os.environ.get("GEMINI_API_KEY", self.gemini_api_key)
        self.author_name = os.environ.get("AUTHOR_NAME", self.author_name)
        self.author_handle = os.environ.get("AUTHOR_HANDLE", self.author_handle)
        self.author_avatar = os.environ.get("AUTHOR_AVATAR", self.author_avatar)
        self.author_followers = os.environ.get("AUTHOR_FOLLOWERS", self.author_followers)
        self.author_headline = os.environ.get("AUTHOR_HEADLINE", self.author_headline)
        if self.default_platforms is None:
            self.default_platforms = ["xiaohongshu", "instagram"]
    
    @property
    def active_api_key(self) -> Optional[str]:
        if self.llm_provider == "openai":
            return self.openai_api_key
        elif self.llm_provider == "anthropic":
            return self.anthropic_api_key
        elif self.llm_provider == "gemini":
            return self.gemini_api_key
        return None
    
    @property
    def active_model(self) -> str:
        if self.llm_provider == "openai":
            return self.openai_model
        elif self.llm_provider == "anthropic":
            return self.anthropic_model
        elif self.llm_provider == "gemini":
            return self.gemini_model
        return ""


# Writing tones
XIAOHONGSHU_TONES = {
    "warm_friend": {
        "name": "温暖闺蜜",
        "style_description": "像最好的朋友在分享日常，语气亲切自然，多用'姐妹''宝子'",
        "emoji_density": "high",
        "sentence_length": "short",
    },
    "trendy_sister": {
        "name": "潮流辣妹",
        "style_description": "时尚前卫，自信张扬，带点酷感和态度",
        "emoji_density": "high",
        "sentence_length": "short",
    },
    "lifestyle_blogger": {
        "name": "生活博主",
        "style_description": "温和知性，注重品质和生活美学，分享干货和心得",
        "emoji_density": "medium",
        "sentence_length": "medium",
    },
    "luxury_minimal": {
        "name": "高级简约",
        "style_description": "克制优雅，少即是多，强调质感和品味",
        "emoji_density": "low",
        "sentence_length": "medium",
    }
}

# Platform configurations
PLATFORM_CONFIGS = {
    "xiaohongshu": {
        "name": "小红书",
        "icon": "📕",
        "max_title_length": 25,
        "max_body_length": 1000,
        "optimal_posting_times": ["08:00", "12:00", "18:00", "20:00", "22:00"],
        "tone_key": "warm_friend",
    },
    "instagram": {
        "name": "Instagram",
        "icon": "📷",
        "max_title_length": 100,
        "max_body_length": 2200,
        "optimal_posting_times": ["07:00", "11:00", "13:00", "19:00", "21:00"],
        "tone_key": "lifestyle_blogger",
    },
    "linkedin": {
        "name": "LinkedIn",
        "icon": "💼",
        "max_title_length": 200,
        "max_body_length": 3000,
        "optimal_posting_times": ["08:00", "12:00", "17:00"],
        "tone_key": "lifestyle_blogger",
    }
}

# Scheduling defaults
SCHEDULING_CONFIG = {
    "timezone": "Asia/Shanghai",
    "xiaohongshu_best_days": ["周二", "周四", "周五", "周六", "周日"],
    "instagram_best_days": ["周二", "周三", "周四", "周五"],
    "linkedin_best_days": ["周二", "周三", "周四"],
}
