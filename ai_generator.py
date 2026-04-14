"""
AI Content Generator for Multi-Platform Photo Pipeline
Supports Xiaohongshu, Instagram, and LinkedIn with vision APIs.
"""

import os
import json
import base64
from typing import Dict, List, Optional

from config import PipelineConfig, XIAOHONGSHU_TONES, PLATFORM_CONFIGS


def encode_image_base64(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def get_mime_type(image_path: str) -> str:
    ext = os.path.splitext(image_path)[1].lower()
    mapping = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".heic": "image/heic",
    }
    return mapping.get(ext, "image/jpeg")


def build_multi_platform_prompt(platforms: List[str], tone_key: str, custom_instructions: str = "") -> str:
    tone = XIAOHONGSHU_TONES[tone_key]
    platform_names = ", ".join([PLATFORM_CONFIGS[p]["name"] for p in platforms])
    
    prompt = f"""你是一个顶级社交媒体内容创作者，擅长根据单张图片为多个平台生成差异化内容。

你的写作风格基调是：{tone['name']} — {tone['style_description']}

请分析这张图片，并为以下平台生成内容：{platform_names}

返回严格的 JSON 格式：

{{
  "scene_description": "图片场景描述（1句话）",
  "mood": "图片传达的情绪（1-2个词）",
  "dominant_colors": ["主色调1", "主色调2"],
  "platforms": {{
"""
    
    for platform in platforms:
        config = PLATFORM_CONFIGS[platform]
        if platform == "xiaohongshu":
            prompt += f"""    "xiaohongshu": {{
      "title_options": ["标题1（带emoji，15-25字）", "标题2（带emoji，15-25字）", "标题3（带emoji，15-25字）"],
      "body": "正文内容（{tone['sentence_length']}句，{tone['emoji_density']}emoji密度，亲切自然）",
      "tips": ["实用小贴士1", "小贴士2", "小贴士3"],
      "hashtags": ["#相关标签1", "#相关标签2", "#相关标签3", "#相关标签4", "#相关标签5"],
      "music_suggestion": "适合这篇笔记的背景音乐风格",
      "cover_tip": "封面图优化建议"
    }},
"""
        elif platform == "instagram":
            prompt += f"""    "instagram": {{
      "caption": "Instagram 配文（可中英混合，轻松有氛围感）",
      "alt_text": "图片 alt text 描述",
      "hashtags": ["#hashtag1", "#hashtag2", "#hashtag3", "#hashtag4", "#hashtag5"],
      "location_tag": "建议的 location tag",
      "story_text": "适合发到 Story 的一句话"
    }},
"""
        elif platform == "linkedin":
            prompt += f"""    "linkedin": {{
      "hook": "LinkedIn 开场钩子句（吸引点击）",
      "body": "正文内容（专业但有温度，可以讲故事或分享洞察）",
      "takeaway": "1-2条核心观点/takeaway",
      "hashtags": ["#Hashtag1", "#Hashtag2", "#Hashtag3"],
      "cta": "结尾 call to action"
    }},
"""
    
    prompt += f"""  }},
  "optimal_posting_time": "建议发布时间（如：周二晚8点）",
  "content_angle": "这张照片最适合的内容切入角度"
}}

写作要求：
1. 每个平台的内容要符合该平台用户习惯和语言风格
2. 小红书要亲切、有emoji、分段清晰
3. Instagram 要轻松、有氛围感、可中英夹杂
4. LinkedIn 要专业但有故事性，提供价值
5. 所有内容必须基于图片真实内容，不虚构场景
6. 标签要精准、热门、相关

{custom_instructions}

请只返回JSON，不要返回其他内容。"""
    
    return prompt


def generate_with_anthropic(image_base64: str, mime_type: str, prompt: str, api_key: str, model: str) -> Dict:
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": mime_type, "data": image_base64}},
                {"type": "text", "text": prompt},
            ],
        }],
    )
    content = message.content[0].text if message.content else ""
    return extract_json(content)


def generate_with_openai(image_base64: str, mime_type: str, prompt: str, api_key: str, model: str) -> Dict:
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_base64}"}},
            ],
        }],
        max_tokens=4096,
    )
    content = response.choices[0].message.content or ""
    return extract_json(content)


def generate_with_gemini(image_base64: str, mime_type: str, prompt: str, api_key: str, model: str) -> Dict:
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    m = genai.GenerativeModel(model)
    image_data = base64.b64decode(image_base64)
    image = {"mime_type": mime_type, "data": image_data}
    response = m.generate_content([prompt, image])
    content = response.text or ""
    return extract_json(content)


def extract_json(content: str) -> Dict:
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        parts = content.split("```")
        for part in parts:
            p = part.strip()
            if p.startswith("{") or p.startswith("["):
                content = p
                break
    return json.loads(content)


def generate_multi_platform_content(
    image_path: str,
    platforms: List[str],
    tone_key: str = "warm_friend",
    custom_instructions: str = "",
    config: Optional[PipelineConfig] = None
) -> Dict:
    config = config or PipelineConfig()
    api_key = config.active_api_key
    
    if not api_key:
        raise ValueError(f"No API key found for provider '{config.llm_provider}'.")
    
    image_base64 = encode_image_base64(image_path)
    mime_type = get_mime_type(image_path)
    prompt = build_multi_platform_prompt(platforms, tone_key, custom_instructions)
    
    try:
        if config.llm_provider == "anthropic":
            result = generate_with_anthropic(image_base64, mime_type, prompt, api_key, config.anthropic_model)
        elif config.llm_provider == "openai":
            result = generate_with_openai(image_base64, mime_type, prompt, api_key, config.openai_model)
        elif config.llm_provider == "gemini":
            result = generate_with_gemini(image_base64, mime_type, prompt, api_key, config.gemini_model)
        else:
            raise ValueError(f"Unknown provider: {config.llm_provider}")
        
        # Ensure platforms exist
        result.setdefault("platforms", {})
        for platform in platforms:
            if platform not in result["platforms"]:
                result["platforms"][platform] = generate_fallback_platform_content(platform)
        
        return result
        
    except Exception as e:
        print(f"AI generation failed: {e}. Using fallback templates.")
        return generate_fallback_content(platforms)


def generate_fallback_platform_content(platform: str) -> Dict:
    if platform == "xiaohongshu":
        return {
            "title_options": ["这个瞬间真的太治愈了✨", "发现生活中的小美好💖", "谁能拒绝这样的氛围感呢？"],
            "body": "姐妹们！\n\n今天想跟大家分享一个超棒的发现，氛围感直接拉满！\n\n💡 小tips：\n• 最佳拍摄时间是傍晚\n• 记得找好光线角度\n• 后期可以适当提升氛围感\n\n真的是一眼心动的感觉💫",
            "tips": ["找好光线", "注意构图", "后期调色"],
            "hashtags": ["#生活记录", "#治愈系", "#日常碎片", "#氛围感", "#生活方式"],
            "music_suggestion": "温柔治愈系",
            "cover_tip": "3:4竖版，突出主体"
        }
    elif platform == "instagram":
        return {
            "caption": "Chasing light and good vibes ✨\n\nSome moments just hit different.",
            "alt_text": "A beautifully lit scene with warm tones and calm atmosphere",
            "hashtags": ["#photography", "#lifestyle", "#aesthetic", "#moments", "#visualdiary"],
            "location_tag": "Hidden Gem",
            "story_text": "This vibe >>"
        }
    elif platform == "linkedin":
        return {
            "hook": "Sometimes the best ideas come when we slow down and observe.",
            "body": "I captured this moment recently, and it reminded me of the importance of presence in our daily work.\n\nIn a world obsessed with speed, there's value in pausing to appreciate the details.",
            "takeaway": "Presence leads to better decisions. The small moments often carry the biggest insights.",
            "hashtags": ["#Leadership", "#Mindfulness", "#WorkLifeBalance"],
            "cta": "What helps you stay present during busy weeks?"
        }
    return {}


def generate_fallback_content(platforms: List[str]) -> Dict:
    return {
        "scene_description": "一个充满氛围感的精彩瞬间",
        "mood": "治愈",
        "dominant_colors": ["暖色", "自然色"],
        "platforms": {p: generate_fallback_platform_content(p) for p in platforms},
        "optimal_posting_time": "周二晚8点",
        "content_angle": "氛围感生活方式分享"
    }
