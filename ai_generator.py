"""
AI content generator for the 11去哪玩 photo pipeline.

The generator prefers a configured multimodal provider, but it also supports a
deterministic fallback path so the local MVP can run without any external API
keys.
"""

import os
import json
import base64
from typing import Dict, List, Optional

from config import PipelineConfig, XIAOHONGSHU_TONES, PLATFORM_CONFIGS


def build_default_image_sequence(journey_context: Optional[Dict]) -> List[Dict]:
    journey_context = journey_context or {}
    gallery_summary = journey_context.get("gallery_summary", [])

    if not gallery_summary:
        photo_names = journey_context.get("photo_names", [])
        gallery_summary = [
            {"index": index + 1, "file_name": photo_name, "captured_at": "", "location": ""}
            for index, photo_name in enumerate(photo_names)
        ]

    if not gallery_summary:
        gallery_summary = [{"index": 1, "file_name": "photo-1", "captured_at": "", "location": ""}]

    sequence = []
    total = len(gallery_summary)
    for index, item in enumerate(gallery_summary):
        if index == 0:
            role = "封面总览"
            purpose = "第一张用来交代目的地和整体氛围。"
        elif index == total - 1:
            role = "收尾记忆"
            purpose = "最后一张收住情绪，适合放返程、夜景或结束感画面。"
        elif index == 1:
            role = "旅程开场"
            purpose = "第二张补到达后的第一视角，让正文更好切入路线。"
        else:
            role = "路线展开"
            purpose = "中段图片负责展开玩法、细节和氛围。"

        sequence.append({
            "position": item.get("index", index + 1),
            "photo_hint": item.get("file_name", f"photo-{index + 1}"),
            "role": role,
            "story_purpose": purpose,
        })

    return sequence


def build_journey_brief(journey_context: Optional[Dict]) -> str:
    if not journey_context:
        return ""

    photo_names = ", ".join(journey_context.get("photo_names", [])[:6])
    lines = [
        "",
        "这是 11去哪玩 的旅程整理任务，请把内容写成适合旅行分享的真实口吻。",
        f"- 旅程标题: {journey_context.get('journey_label', '11去哪玩')}" ,
        f"- 旅程主题: {journey_context.get('journey_theme', '轻旅行')}" ,
        f"- 时间线索: {journey_context.get('journey_window', '待补充')}" ,
        f"- 照片数量: {journey_context.get('photo_count', 1)} 张",
    ]

    if photo_names:
        lines.append(f"- 照片文件名线索: {photo_names}")

    if journey_context.get("journey_location"):
        lines.append(f"- 旅程位置线索: {journey_context.get('journey_location')}")

    gallery_summary = journey_context.get("gallery_summary", [])
    if gallery_summary:
        lines.append("- 图序线索:")
        for item in gallery_summary[:8]:
            lines.append(
                f"  {item.get('index', 0)}. {item.get('file_name', '')} | {item.get('captured_at', '')} | {item.get('location', '') or '地点待补充'}"
            )

    content_angle = journey_context.get("content_angle")
    if content_angle:
        lines.append(f"- 推荐切入角度: {content_angle}")

    return "\n".join(lines)


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


def build_multi_platform_prompt(
    platforms: List[str],
    tone_key: str,
    custom_instructions: str = "",
    journey_context: Optional[Dict] = None,
) -> str:
    tone = XIAOHONGSHU_TONES[tone_key]
    platform_names = ", ".join([PLATFORM_CONFIGS[p]["name"] for p in platforms])
    journey_brief = build_journey_brief(journey_context)
    
    prompt = f"""你是一个顶级社交媒体内容创作者，擅长根据单张图片为多个平台生成差异化内容。

你的写作风格基调是：{tone['name']} — {tone['style_description']}

请分析这张图片，并为以下平台生成内容：{platform_names}{journey_brief}

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
            "image_sequence": [
                {{"position": 1, "photo_hint": "照片文件名或时间线索", "role": "封面总览", "story_purpose": "解释为什么这张图放在这里"}}
            ],
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
    config: Optional[PipelineConfig] = None,
    journey_context: Optional[Dict] = None,
) -> Dict:
    config = config or PipelineConfig()
    api_key = config.active_api_key

    if not api_key:
        return generate_fallback_content(platforms, tone_key=tone_key, journey_context=journey_context)
    
    image_base64 = encode_image_base64(image_path)
    mime_type = get_mime_type(image_path)
    prompt = build_multi_platform_prompt(platforms, tone_key, custom_instructions, journey_context)
    
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
        return generate_fallback_content(platforms, tone_key=tone_key, journey_context=journey_context)


def generate_fallback_platform_content(platform: str, journey_context: Optional[Dict] = None) -> Dict:
    journey_context = journey_context or {}
    journey_label = journey_context.get("journey_label", "11去哪玩")
    journey_theme = journey_context.get("journey_theme", "城市漫游")
    journey_window = journey_context.get("journey_window", "这次旅程")
    photo_count = journey_context.get("photo_count", 1)
    image_sequence = build_default_image_sequence(journey_context)

    if platform == "xiaohongshu":
        return {
            "title_options": [
                f"{journey_label} 这组照片太适合发小红书了✨",
                f"{journey_window} 的 {journey_theme} 灵感，直接收藏📍",
                f"11去哪玩 | {journey_theme} 旅程照片整理好了💼",
            ],
            "body": (
                f"这次整理了 {photo_count} 张关于 {journey_theme} 的旅程照片。\n\n"
                f"如果你也在找 {journey_theme} 的出片和发帖灵感，这一组真的很适合作为『11去哪玩』的笔记素材。\n\n"
                "我会优先选封面感最强的一张做首图，再用路线、氛围、拍照 tips 把整段旅程串起来。\n\n"
                "小建议：\n• 第一段先写为什么值得去\n• 第二段补路线和时间线\n• 结尾放适合收藏的实用提醒"
            ),
            "tips": ["首图优先选信息量最强的照片", "正文按路线或时间顺序展开", "标签里保留目的地和玩法词"],
            "hashtags": ["#11去哪玩", f"#{journey_theme}", "#旅行攻略", "#小红书旅行", "#周末去哪玩"],
            "image_sequence": image_sequence,
            "music_suggestion": "轻快旅行 vlog",
            "cover_tip": f"用最能代表 {journey_theme} 的一张照片做封面"
        }
    elif platform == "instagram":
        return {
            "caption": (
                f"{journey_label} ✨\n\n"
                f"A {journey_theme.lower()} story told through {photo_count} frames. Save this for your next weekend plan."
            ),
            "alt_text": f"Travel photo set for {journey_theme} from the 11去哪玩 workflow",
            "hashtags": ["#travelreels", "#weekendgetaway", "#visualdiary", "#tripideas", "#11qunaerwan"],
            "location_tag": journey_theme,
            "story_text": f"{journey_theme} moodboard >>"
        }
    elif platform == "linkedin":
        return {
            "hook": f"A strong travel narrative starts with a clear journey theme: {journey_theme}.",
            "body": (
                f"This draft was created from {photo_count} travel photos in the 11去哪玩 pipeline. "
                "Even without a live multimodal model, the workflow still turns a photo set into a usable publishing draft."
            ),
            "takeaway": "A runnable MVP should preserve the core publishing workflow even when external integrations are unavailable.",
            "hashtags": ["#ContentOps", "#TravelMarketing", "#MVP"],
            "cta": "How would you structure a photo-to-content workflow for your team?"
        }
    return {}


def generate_fallback_content(
    platforms: List[str],
    tone_key: str = "warm_friend",
    journey_context: Optional[Dict] = None,
) -> Dict:
    journey_context = journey_context or {}
    journey_theme = journey_context.get("journey_theme", "城市漫游")
    journey_label = journey_context.get("journey_label", "11去哪玩")

    return {
        "scene_description": f"围绕 {journey_theme} 展开的旅程照片集合",
        "mood": "期待",
        "dominant_colors": ["自然色", "旅行感"],
        "journey_label": journey_label,
        "tone_key": tone_key,
        "platforms": {p: generate_fallback_platform_content(p, journey_context) for p in platforms},
        "optimal_posting_time": "周二晚8点",
        "content_angle": f"从 {journey_theme} 切入的路线与出片分享"
    }
