#!/usr/bin/env python3
"""
Multi-Platform Photo Content Pipeline - Web UI
===============================================
Supports: Xiaohongshu, Instagram, LinkedIn
Features: batch generation, scheduling, Google Photos Takeout sync
"""

import os
import sys
import json
import base64
import threading
import time
import math
import re
import zipfile
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
from collections import deque
from uuid import uuid4

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit
from werkzeug.utils import secure_filename

from config import PipelineConfig, PLATFORM_CONFIGS, SCHEDULING_CONFIG, XIAOHONGSHU_TONES
from ai_generator import generate_multi_platform_content

HERMES_HOME = os.path.expanduser("~/.hermes")
TOKEN_PATH = os.path.join(HERMES_HOME, "google_token.json")
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOCAL_UPLOAD_DIR = DATA_DIR / "uploads"
LOCAL_EXPORT_DIR = DATA_DIR / "exports"

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif"}
GPS_INFO_TAG = 34853
EARTH_RADIUS_KM = 6371.0
JOURNEY_MAX_DISTANCE_KM = 45
JOURNEY_MAX_LOCATION_WINDOW_HOURS = 72
JOURNEY_MAX_FALLBACK_WINDOW_HOURS = 18
TRAVEL_THEME_KEYWORDS = {
    "城市漫游": ["city", "citywalk", "street", "bund", "shanghai", "hangzhou", "beijing", "chengdu", "上海", "杭州", "北京", "成都", "外滩", "街头"],
    "山野徒步": ["mountain", "hill", "hike", "trail", "peak", "forest", "camp", "山", "徒步", "森林", "露营"],
    "海边度假": ["beach", "sea", "ocean", "coast", "island", "sanya", "xiamen", "青岛", "三亚", "厦门", "海边", "沙滩"],
    "古镇人文": ["temple", "museum", "oldtown", "heritage", "古镇", "寺", "博物馆", "建筑", "历史"],
    "咖啡美食": ["coffee", "cafe", "brunch", "food", "meal", "latte", "咖啡", "甜品", "美食", "餐厅"],
}

app = Flask(__name__)
app.config['SECRET_KEY'] = 'multi-platform-pipeline-secret'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

class PipelineState:
    def __init__(self):
        self.photos_queue = deque()
        self.processed_posts = []
        self.scheduled_posts = []
        self.is_watching = False
        self.last_check = None
        self.drive_service = None
        self.folder_ids = {}
        self.config = PipelineConfig()
        
state = PipelineState()
state_lock = threading.Lock()

PHOTO_MIMETYPES = {
    "image/jpeg", "image/jpg", "image/png", "image/gif",
    "image/webp", "image/heic", "image/heif"
}

@dataclass
class PhotoPost:
    id: str
    file_name: str
    drive_id: str
    local_path: Optional[str]
    image_base64: Optional[str]
    vision_analysis: Dict
    generated_content: Dict
    platform_previews: Dict
    status: str
    tone_key: str
    platforms: List[str]
    source: str
    journey_label: str
    journey_theme: str
    journey_location: str
    journey_window: str
    photo_count: int
    gallery: List[Dict]
    scheduled_at: Optional[str]
    created_at: str
    updated_at: str


# ==================== Google Drive ====================

def get_drive_service():
    if state.drive_service:
        return state.drive_service

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as error:
        raise RuntimeError(
            "Google Drive dependencies are not installed. Install requirements.txt to enable Drive mode."
        ) from error

    if not os.path.exists(TOKEN_PATH):
        raise FileNotFoundError(f"Google token not found at {TOKEN_PATH}. Run OAuth setup first.")
    creds = Credentials.from_authorized_user_file(TOKEN_PATH)
    if not creds.valid and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
    with state_lock:
        state.drive_service = build("drive", "v3", credentials=creds)
    return state.drive_service


def ensure_folder_structure(service, root_name="Photo Content"):
    # local helper to avoid lock during Drive API calls
    def _ensure():
        query = f"mimeType='application/vnd.google-apps.folder' and name='{root_name}' and trashed=false"
        results = service.files().list(q=query, spaces="drive", fields="files(id, name)").execute()
        files = results.get("files", [])
        
        if files:
            root_id = files[0]["id"]
        else:
            folder = service.files().create(
                body={"name": root_name, "mimeType": "application/vnd.google-apps.folder"},
                fields="id"
            ).execute()
            root_id = folder["id"]
        
        folder_ids = {"root": root_id}
        
        def sub(parent, name):
            q = f"mimeType='application/vnd.google-apps.folder' and name='{name}' and '{parent}' in parents and trashed=false"
            r = service.files().list(q=q, spaces="drive", fields="files(id, name)").execute()
            f = r.get("files", [])
            if f:
                return f[0]["id"]
            folder = service.files().create(
                body={"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent]},
                fields="id"
            ).execute()
            return folder["id"]
        
        photos = sub(root_id, "Photos-to-Process")
        folder_ids["draft"] = sub(photos, "draft")
        folder_ids["selected"] = sub(photos, "selected")
        folder_ids["processed"] = sub(photos, "processed")
        folder_ids["takeout"] = sub(photos, "google-photos-takeout")
        
        output = sub(root_id, "Content-Output")
        for platform in ["xiaohongshu", "instagram", "linkedin"]:
            folder_ids[f"{platform}_posts"] = sub(output, f"{platform}-posts")
        
        folder_ids["scheduled"] = sub(output, "scheduled-posts")
        return folder_ids
    
    folder_ids = _ensure()
    with state_lock:
        state.folder_ids.update(folder_ids)
    return state.folder_ids

def list_photos_in_folder(service, folder_id: str) -> List[Dict]:
    q = f"'{folder_id}' in parents and trashed=false"
    r = service.files().list(q=q, spaces="drive", fields="files(id, name, mimeType, modifiedTime, webViewLink)", pageSize=100).execute()
    return [f for f in r.get("files", []) if f.get("mimeType") in PHOTO_MIMETYPES]


def download_photo(service, file_id: str) -> bytes:
    from io import BytesIO
    from googleapiclient.http import MediaIoBaseDownload

    req = service.files().get_media(fileId=file_id)
    fh = BytesIO()
    dl = MediaIoBaseDownload(fh, req)
    done = False
    while not done:
        _, done = dl.next_chunk()
    fh.seek(0)
    return fh.read()


def move_file(service, file_id: str, new_parent: str, old_parent: str):
    service.files().update(fileId=file_id, addParents=new_parent, removeParents=old_parent, fields="id, parents").execute()


def upload_file(service, parent_id: str, name: str, content: bytes, mimetype: str = "text/plain") -> str:
    from io import BytesIO
    from googleapiclient.http import MediaIoBaseUpload

    meta = {"name": name, "parents": [parent_id]}
    media = MediaIoBaseUpload(BytesIO(content), mimetype=mimetype)
    f = service.files().create(body=meta, media_body=media, fields="id").execute()
    return f["id"]


def upload_text(service, parent_id: str, name: str, content: str) -> str:
    return upload_file(service, parent_id, name, content.encode("utf-8"))


def ensure_local_workspace():
    LOCAL_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    LOCAL_EXPORT_DIR.mkdir(parents=True, exist_ok=True)


def has_drive_token() -> bool:
    return os.path.exists(TOKEN_PATH)


def is_supported_photo(file_name: str) -> bool:
    return Path(file_name).suffix.lower() in SUPPORTED_EXTENSIONS


def decode_image_payload(image_base64_value: str) -> bytes:
    payload = image_base64_value.split(",", 1)[1] if image_base64_value.startswith("data:") else image_base64_value
    return base64.b64decode(payload)


def build_local_asset_path(file_name: str) -> Path:
    ensure_local_workspace()
    suffix = Path(file_name).suffix.lower() or ".jpg"
    safe_stem = secure_filename(Path(file_name).stem) or "photo"
    return LOCAL_UPLOAD_DIR / f"{safe_stem}-{uuid4().hex[:8]}{suffix}"


def normalize_exif_text(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    return str(value or "")


def coerce_datetime(value) -> Optional[datetime]:
    if not value:
        return None

    if isinstance(value, datetime):
        return value.replace(tzinfo=None)

    value_text = normalize_exif_text(value).strip()
    if not value_text:
        return None

    for parser in (
        lambda raw: datetime.strptime(raw, "%Y:%m:%d %H:%M:%S"),
        lambda raw: datetime.fromisoformat(raw.replace("Z", "+00:00")),
    ):
        try:
            parsed = parser(value_text)
            return parsed.replace(tzinfo=None)
        except ValueError:
            continue

    return None


def rational_to_float(value) -> float:
    if value is None:
        return 0.0

    if hasattr(value, "numerator") and hasattr(value, "denominator"):
        return float(value.numerator) / float(value.denominator or 1)

    if isinstance(value, (tuple, list)) and len(value) == 2:
        return float(value[0]) / float(value[1] or 1)

    return float(value)


def dms_to_decimal(values, ref) -> Optional[float]:
    if not values or len(values) < 3:
        return None

    try:
        degrees, minutes, seconds = [rational_to_float(part) for part in values[:3]]
    except (TypeError, ValueError, ZeroDivisionError):
        return None

    decimal = degrees + minutes / 60 + seconds / 3600
    if normalize_exif_text(ref).upper() in {"S", "W"}:
        decimal *= -1

    return round(decimal, 6)


def format_location_label(location: Optional[Dict]) -> str:
    if not location:
        return ""
    return f"GPS {location['latitude']:.3f}, {location['longitude']:.3f}"


def guess_capture_datetime(file_name: str, fallback_iso: Optional[str] = None) -> Optional[datetime]:
    candidates = [Path(file_name).stem]

    if fallback_iso:
        candidates.append(fallback_iso)

    patterns = [
        r"(20\d{2})[-_]?([01]\d)[-_]?([0-3]\d)",
        r"(20\d{2})[-_]?([01]\d)[-_]?([0-3]\d)[-_ ]?([0-2]\d)([0-5]\d)([0-5]\d)",
    ]

    for candidate in candidates:
        if not candidate:
            continue

        for pattern in patterns:
            match = re.search(pattern, candidate)
            if not match:
                continue

            try:
                values = [int(part) for part in match.groups()]
                if len(values) == 3:
                    return datetime(values[0], values[1], values[2])
                return datetime(values[0], values[1], values[2], values[3], values[4], values[5])
            except ValueError:
                continue

        try:
            return datetime.fromisoformat(candidate.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            continue

    return None


def extract_photo_metadata(image_bytes: bytes, file_name: str, fallback_iso: Optional[str] = None) -> Dict:
    captured_at = None
    captured_at_source = ""
    location = None

    try:
        from io import BytesIO
        from PIL import Image

        with Image.open(BytesIO(image_bytes)) as image:
            exif = image.getexif()

            if exif:
                captured_at = (
                    coerce_datetime(exif.get(36867))
                    or coerce_datetime(exif.get(36868))
                    or coerce_datetime(exif.get(306))
                )

                gps_ifd = {}
                try:
                    gps_ifd = exif.get_ifd(GPS_INFO_TAG)
                except Exception:
                    gps_ifd = exif.get(GPS_INFO_TAG) or {}

                if gps_ifd:
                    latitude = dms_to_decimal(gps_ifd.get(2), gps_ifd.get(1))
                    longitude = dms_to_decimal(gps_ifd.get(4), gps_ifd.get(3))
                    if latitude is not None and longitude is not None:
                        location = {
                            "latitude": latitude,
                            "longitude": longitude,
                        }
    except Exception:
        pass

    if captured_at:
        captured_at_source = "exif"
    else:
        captured_at = guess_capture_datetime(file_name, fallback_iso)
        captured_at_source = "filename" if captured_at else "fallback"

    if not captured_at:
        captured_at = datetime.now()
        captured_at_source = "upload_time"

    return {
        "captured_at": captured_at.isoformat(),
        "captured_at_source": captured_at_source,
        "location": location,
        "location_label": format_location_label(location),
    }


def infer_journey_theme(*hints: Optional[str]) -> str:
    haystack = " ".join([hint for hint in hints if hint]).lower()

    for theme, keywords in TRAVEL_THEME_KEYWORDS.items():
        if any(keyword in haystack for keyword in keywords):
            return theme

    return "轻旅行"


def get_asset_capture_datetime(asset: Dict) -> Optional[datetime]:
    return coerce_datetime(asset.get("captured_at")) or guess_capture_datetime(asset.get("file_name", ""))


def get_asset_location(asset: Dict) -> Optional[Dict]:
    location = asset.get("location")
    if not isinstance(location, dict):
        return None
    if "latitude" not in location or "longitude" not in location:
        return None
    return location


def haversine_distance_km(location_a: Dict, location_b: Dict) -> float:
    lat1 = math.radians(location_a["latitude"])
    lon1 = math.radians(location_a["longitude"])
    lat2 = math.radians(location_b["latitude"])
    lon2 = math.radians(location_b["longitude"])

    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    a = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_KM * c


def summarize_journey_location(assets: List[Dict]) -> str:
    valid_locations = [get_asset_location(asset) for asset in assets]
    valid_locations = [location for location in valid_locations if location]

    if not valid_locations:
        return ""

    avg_lat = sum(location["latitude"] for location in valid_locations) / len(valid_locations)
    avg_lon = sum(location["longitude"] for location in valid_locations) / len(valid_locations)
    return format_location_label({"latitude": avg_lat, "longitude": avg_lon})


def dominant_journey_theme(assets: List[Dict]) -> str:
    counts = {}

    for asset in assets:
        theme = asset.get("theme_hint") or infer_journey_theme(asset.get("file_name", ""), asset.get("location_label", ""))
        counts[theme] = counts.get(theme, 0) + 1

    if not counts:
        return "轻旅行"

    return max(counts.items(), key=lambda item: item[1])[0]


def sort_assets_for_story(assets: List[Dict]) -> List[Dict]:
    return sorted(
        assets,
        key=lambda asset: (
            get_asset_capture_datetime(asset) or datetime.max,
            asset.get("file_name", ""),
        ),
    )


def group_location_centroid(assets: List[Dict]) -> Optional[Dict]:
    valid_locations = [get_asset_location(asset) for asset in assets]
    valid_locations = [location for location in valid_locations if location]

    if not valid_locations:
        return None

    return {
        "latitude": sum(location["latitude"] for location in valid_locations) / len(valid_locations),
        "longitude": sum(location["longitude"] for location in valid_locations) / len(valid_locations),
    }


def should_join_journey_group(asset: Dict, current_group: List[Dict]) -> bool:
    if not current_group:
        return True

    asset_dt = get_asset_capture_datetime(asset)
    latest_group_dt = max((get_asset_capture_datetime(item) for item in current_group), default=None)
    asset_location = get_asset_location(asset)
    group_centroid = group_location_centroid(current_group)
    asset_theme = asset.get("theme_hint") or infer_journey_theme(asset.get("file_name", ""))
    group_theme = dominant_journey_theme(current_group)

    if asset_dt and latest_group_dt:
        time_gap = abs(asset_dt - latest_group_dt)

        if asset_location and group_centroid:
            distance = haversine_distance_km(asset_location, group_centroid)
            if distance <= JOURNEY_MAX_DISTANCE_KM and time_gap <= timedelta(hours=JOURNEY_MAX_LOCATION_WINDOW_HOURS):
                return True
            if distance > JOURNEY_MAX_DISTANCE_KM * 2 and time_gap > timedelta(hours=4):
                return False

        if time_gap <= timedelta(hours=JOURNEY_MAX_FALLBACK_WINDOW_HOURS):
            return True

        if time_gap <= timedelta(hours=36) and asset_theme == group_theme:
            return True

        return False

    if asset_location and group_centroid:
        return haversine_distance_km(asset_location, group_centroid) <= JOURNEY_MAX_DISTANCE_KM

    return asset_theme == group_theme


def cluster_assets_into_journeys(assets: List[Dict], manual_name: str = "") -> List[List[Dict]]:
    ordered_assets = sort_assets_for_story(assets)

    if manual_name:
        return [ordered_assets]

    groups = []
    current_group = []

    for asset in ordered_assets:
        if not current_group or should_join_journey_group(asset, current_group):
            current_group.append(asset)
            continue

        groups.append(current_group)
        current_group = [asset]

    if current_group:
        groups.append(current_group)

    return groups


def format_journey_window(assets: List[Dict]) -> str:
    dates = []

    for asset in assets:
        captured_dt = get_asset_capture_datetime(asset)
        if captured_dt:
            dates.append(captured_dt)

    if not dates:
        return "待整理"

    start_at = min(dates)
    end_at = max(dates)

    if start_at.date() == end_at.date():
        return start_at.strftime("%Y-%m-%d")

    return f"{start_at.strftime('%Y-%m-%d')} ~ {end_at.strftime('%Y-%m-%d')}"


def build_journey_label(file_name: str, captured_at: Optional[str], manual_name: str = "", journey_theme: str = "轻旅行") -> str:
    manual_name = manual_name.strip()
    if manual_name:
        return manual_name

    captured_dt = coerce_datetime(captured_at) or guess_capture_datetime(file_name, captured_at)

    if captured_dt:
        return f"11去哪玩 | {captured_dt.strftime('%m/%d')} {journey_theme}"

    return f"11去哪玩 | {journey_theme}"


def build_journey_group_key(file_name: str, captured_at: Optional[str], manual_name: str = "") -> str:
    manual_name = manual_name.strip()
    if manual_name:
        return f"manual::{manual_name}"

    captured_dt = guess_capture_datetime(file_name, captured_at)
    theme = infer_journey_theme(file_name)
    date_key = captured_dt.strftime("%Y-%m-%d") if captured_dt else datetime.now().strftime("%Y-%m-%d")
    return f"{date_key}::{theme}"


def build_story_roles(total: int, index: int) -> Dict:
    if index == 0:
        return {"role": "封面总览", "story_purpose": "第一张先交代目的地和整体氛围，方便读者一眼看懂这趟旅程。"}
    if index == total - 1:
        return {"role": "收尾记忆", "story_purpose": "最后一张放返程、夜景或情绪收束图，让笔记有完整的结束感。"}
    if index == 1:
        return {"role": "旅程开场", "story_purpose": "第二张交代到达后的第一感受，正文可以自然切到路线和玩法。"}
    if total > 3 and index == total - 2:
        return {"role": "细节补充", "story_purpose": "倒数第二张适合放局部细节，增强这段旅程的真实感和收藏价值。"}
    return {"role": "路线展开", "story_purpose": "中间段图片负责展开路线、玩法和氛围，让节奏更顺。"}


def build_xiaohongshu_gallery(post: PhotoPost) -> List[Dict]:
    gallery = sort_assets_for_story(post.gallery)
    items = []

    for index, asset in enumerate(gallery):
        story_role = build_story_roles(len(gallery), index)
        captured_dt = get_asset_capture_datetime(asset)
        image_payload = asset.get("image_base64", "")
        image_url = f"data:image/jpeg;base64,{image_payload}" if image_payload else (f"data:image/jpeg;base64,{post.image_base64}" if index == 0 and post.image_base64 else "")
        items.append({
            "index": index + 1,
            "image": image_url,
            "file_name": asset.get("file_name", ""),
            "captured_at": captured_dt.strftime("%m-%d %H:%M") if captured_dt else "时间未知",
            "location": asset.get("location_label") or post.journey_location,
            "role": story_role["role"],
            "story_purpose": story_role["story_purpose"],
            "is_cover": index == 0,
        })

    return items


def build_generated_image_sequence(xhs_payload: Dict, gallery: List[Dict]) -> List[Dict]:
    generated_sequence = xhs_payload.get("image_sequence")

    if isinstance(generated_sequence, list) and generated_sequence:
        normalized = []
        for index, item in enumerate(generated_sequence[:len(gallery)]):
            if isinstance(item, dict):
                normalized.append({
                    "position": item.get("position", index + 1),
                    "role": item.get("role", gallery[index]["role"]),
                    "photo_hint": item.get("photo_hint", gallery[index]["file_name"]),
                    "story_purpose": item.get("story_purpose", gallery[index]["story_purpose"]),
                })
        if normalized:
            return normalized

    return [
        {
            "position": item["index"],
            "role": item["role"],
            "photo_hint": item["file_name"],
            "story_purpose": item["story_purpose"],
        }
        for item in gallery
    ]


def build_journey_context(post: PhotoPost) -> Dict:
    gallery = sort_assets_for_story(post.gallery)
    return {
        "brand_name": "11去哪玩",
        "journey_label": post.journey_label,
        "journey_theme": post.journey_theme,
        "journey_location": post.journey_location,
        "journey_window": post.journey_window,
        "photo_count": post.photo_count,
        "photo_names": [asset.get("file_name", "") for asset in gallery[:8]],
        "gallery_summary": [
            {
                "index": index + 1,
                "file_name": asset.get("file_name", ""),
                "captured_at": (get_asset_capture_datetime(asset) or datetime.now()).strftime("%Y-%m-%d %H:%M") if get_asset_capture_datetime(asset) else "时间未知",
                "location": asset.get("location_label") or post.journey_location,
            }
            for index, asset in enumerate(gallery[:8])
        ],
        "content_angle": post.vision_analysis.get("content_angle", "旅程玩法整理"),
    }


def make_post_id(prefix: str = "journey") -> str:
    return f"{prefix}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:8]}"


def build_post_from_assets(assets: List[Dict], source: str, manual_name: str = "") -> PhotoPost:
    ordered_assets = sort_assets_for_story(assets)
    cover = ordered_assets[0]
    journey_theme = dominant_journey_theme(ordered_assets)
    journey_label = build_journey_label(cover["file_name"], cover.get("captured_at"), manual_name, journey_theme)
    journey_location = summarize_journey_location(ordered_assets)
    created_at = datetime.now().isoformat()

    return PhotoPost(
        id=make_post_id(),
        file_name=cover["file_name"],
        drive_id=cover.get("drive_id", ""),
        local_path=cover.get("local_path"),
        image_base64=cover["image_base64"],
        vision_analysis={
            "source": source,
            "journey_label": journey_label,
            "journey_theme": journey_theme,
            "captured_at": cover.get("captured_at"),
            "journey_location": journey_location,
        },
        generated_content={},
        platform_previews={},
        status="pending",
        tone_key=state.config.default_tone,
        platforms=state.config.default_platforms.copy(),
        source=source,
        journey_label=journey_label,
        journey_theme=journey_theme,
        journey_location=journey_location,
        journey_window=format_journey_window(ordered_assets),
        photo_count=len(ordered_assets),
        gallery=[
            {
                "file_name": asset["file_name"],
                "captured_at": asset.get("captured_at"),
                "captured_at_source": asset.get("captured_at_source", ""),
                "local_path": asset.get("local_path"),
                "drive_id": asset.get("drive_id", ""),
                "image_base64": asset.get("image_base64", ""),
                "location": asset.get("location"),
                "location_label": asset.get("location_label", ""),
            }
            for asset in ordered_assets
        ],
        scheduled_at=None,
        created_at=created_at,
        updated_at=created_at,
    )


def save_local_export(name: str, content: str) -> str:
    ensure_local_workspace()
    export_path = LOCAL_EXPORT_DIR / name
    export_path.write_text(content, encoding="utf-8")
    return str(export_path)


def create_local_asset(file_storage) -> Dict:
    original_name = file_storage.filename or f"photo-{uuid4().hex[:8]}.jpg"
    if not is_supported_photo(original_name):
        raise ValueError(f"Unsupported file type: {original_name}")

    content = file_storage.read()
    if not content:
        raise ValueError(f"Empty file: {original_name}")

    local_path = build_local_asset_path(original_name)
    local_path.write_bytes(content)
    metadata = extract_photo_metadata(content, original_name)

    return {
        "file_name": original_name,
        "drive_id": "",
        "local_path": str(local_path),
        "image_base64": base64.b64encode(content).decode("utf-8"),
        "captured_at": metadata["captured_at"],
        "captured_at_source": metadata["captured_at_source"],
        "location": metadata["location"],
        "location_label": metadata["location_label"],
        "theme_hint": infer_journey_theme(original_name, metadata["location_label"]),
    }


# ==================== Watcher ====================

def watch_drive_folder():
    while True:
        with state_lock:
            if not state.is_watching:
                break
        try:
            service = get_drive_service()
            with state_lock:
                if not state.folder_ids:
                    ensure_folder_structure(service)
                folder_selected = state.folder_ids.get("selected")
                folder_processed = state.folder_ids.get("processed")
            
            photos = list_photos_in_folder(service, folder_selected)
            discovered_assets = []

            for photo in photos:
                pid = photo["id"]
                with state_lock:
                    known_ids = {p.drive_id for p in list(state.photos_queue) + state.processed_posts + state.scheduled_posts}
                if pid in known_ids:
                    continue
                
                print(f"New photo: {photo['name']}")
                img_data = download_photo(service, pid)
                img_b64 = base64.b64encode(img_data).decode("utf-8")

                metadata = extract_photo_metadata(img_data, photo["name"], photo.get("modifiedTime"))
                discovered_assets.append({
                    "file_name": photo["name"],
                    "drive_id": pid,
                    "local_path": None,
                    "image_base64": img_b64,
                    "captured_at": metadata["captured_at"],
                    "captured_at_source": metadata["captured_at_source"],
                    "location": metadata["location"],
                    "location_label": metadata["location_label"],
                    "theme_hint": infer_journey_theme(photo["name"], metadata["location_label"]),
                })

            if discovered_assets:
                grouped_assets = cluster_assets_into_journeys(discovered_assets)

                with state_lock:
                    for assets in grouped_assets:
                        post = build_post_from_assets(assets, source="google-drive")
                        state.photos_queue.append(post)
                        socketio.emit('new_photo_detected', {
                            'photo_id': post.id,
                            'file_name': post.file_name,
                            'journey_label': post.journey_label,
                            'journey_location': post.journey_location,
                            'photo_count': post.photo_count,
                            'thumbnail': f"data:image/jpeg;base64,{post.image_base64}"
                        })

                    queue_size = len(state.photos_queue)
                    processed_count = len(state.processed_posts)
                    scheduled_count = len(state.scheduled_posts)

                for asset in discovered_assets:
                    move_file(service, asset["drive_id"], folder_processed, folder_selected)
            
            last_check = datetime.now().isoformat()
            with state_lock:
                state.last_check = last_check
            socketio.emit('status_update', {
                'last_check': last_check,
                'queue_size': queue_size if 'queue_size' in dir() else len(list(state.photos_queue)),
                'processed_count': processed_count if 'processed_count' in dir() else len(state.processed_posts),
                'scheduled_count': scheduled_count if 'scheduled_count' in dir() else len(state.scheduled_posts)
            })
        except Exception as e:
            print(f"Watcher error: {e}")
        
        time.sleep(state.config.check_interval_seconds)


# ==================== Preview Builders ====================

def build_xiaohongshu_preview(post: PhotoPost, content: Dict) -> Dict:
    xhs = content.get("platforms", {}).get("xiaohongshu", content.get("xiaohongshu", {}))
    gallery = build_xiaohongshu_gallery(post)
    return {
        "cover_image": gallery[0]["image"] if gallery else (f"data:image/jpeg;base64,{post.image_base64}" if post.image_base64 else None),
        "title": xhs.get("title_options", [""])[0] if xhs.get("title_options") else "",
        "body": xhs.get("body", ""),
        "hashtags": xhs.get("hashtags", []),
        "likes": "1.2k", "saves": "856", "comments": "128",
        "author": {"name": "Your Name", "avatar": None, "followers": "5.2k"},
        "location": f"📍 {post.journey_location or post.journey_label.replace('11去哪玩 | ', '')}", "post_time": post.journey_window,
        "music": xhs.get("music_suggestion", "🎵 原声"),
        "gallery": gallery,
        "image_sequence": build_generated_image_sequence(xhs, gallery),
        "cover_tip": xhs.get("cover_tip", ""),
    }


def build_instagram_preview(post: PhotoPost, content: Dict) -> Dict:
    ig = content.get("platforms", {}).get("instagram", content.get("instagram", {}))
    return {
        "cover_image": f"data:image/jpeg;base64,{post.image_base64}" if post.image_base64 else None,
        "username": "your.handle",
        "avatar": None,
        "likes": "2.4k",
        "caption": ig.get("caption", ""),
        "hashtags": ig.get("hashtags", []),
        "location": ig.get("location_tag", ""),
        "comments_count": "42",
        "post_time": "2 hours ago",
        "story_text": ig.get("story_text", ""),
    }


def build_linkedin_preview(post: PhotoPost, content: Dict) -> Dict:
    li = content.get("platforms", {}).get("linkedin", content.get("linkedin", {}))
    return {
        "cover_image": f"data:image/jpeg;base64,{post.image_base64}" if post.image_base64 else None,
        "author_name": "Your Name",
        "author_headline": "Content Creator | Visual Storyteller",
        "hook": li.get("hook", ""),
        "body": li.get("body", ""),
        "takeaway": li.get("takeaway", ""),
        "hashtags": li.get("hashtags", []),
        "cta": li.get("cta", ""),
        "likes": "328",
        "comments": "18",
        "reposts": "24",
    }


def build_previews(post: PhotoPost) -> Dict:
    content = post.generated_content
    previews = {}
    if "xiaohongshu" in post.platforms:
        previews["xiaohongshu"] = build_xiaohongshu_preview(post, content)
    if "instagram" in post.platforms:
        previews["instagram"] = build_instagram_preview(post, content)
    if "linkedin" in post.platforms:
        previews["linkedin"] = build_linkedin_preview(post, content)
    return previews


# ==================== Routes ====================

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/status')
def api_status():
    with state_lock:
        return jsonify({
            "is_watching": state.is_watching,
            "last_check": state.last_check,
            "queue_size": len(state.photos_queue),
            "processed_count": len(state.processed_posts),
            "scheduled_count": len(state.scheduled_posts),
            "folder_ids": state.folder_ids,
            "config": {
                "provider": state.config.llm_provider,
                "model": state.config.active_model,
                "default_tone": state.config.default_tone,
                "default_platforms": state.config.default_platforms,
                "has_api_key": bool(state.config.active_api_key)
            },
            "mvp": {
                "brand": "11去哪玩",
                "drive_ready": has_drive_token(),
                "local_upload_ready": True,
                "export_destination": "drive" if has_drive_token() else "local"
            },
            "tones": {k: v["name"] for k, v in XIAOHONGSHU_TONES.items()},
            "platforms": {k: {"name": v["name"], "icon": v["icon"]} for k, v in PLATFORM_CONFIGS.items()},
            "scheduling": SCHEDULING_CONFIG,
        })


@app.route('/api/config', methods=['POST'])
def api_update_config():
    data = request.json
    with state_lock:
        if 'provider' in data:
            state.config.llm_provider = data['provider']
        if 'tone' in data:
            state.config.default_tone = data['tone']
        if 'platforms' in data:
            state.config.default_platforms = data['platforms']
        if 'api_key' in data:
            key_name = f"{state.config.llm_provider.upper()}_API_KEY"
            os.environ[key_name] = data['api_key']
            state.config = PipelineConfig()
        return jsonify({"success": True, "config": {
            "provider": state.config.llm_provider,
            "default_tone": state.config.default_tone,
            "default_platforms": state.config.default_platforms,
        }})


@app.route('/api/posts')
def api_posts():
    with state_lock:
        all_posts = list(state.photos_queue) + state.processed_posts + state.scheduled_posts
    out = []
    for post in all_posts:
        d = asdict(post)
        if d.get('image_base64'):
            d['image_base64_preview'] = "data:image/jpeg;base64," + d['image_base64'][:50] + "..."
        out.append(d)
    return jsonify(out)


@app.route('/api/local-photos', methods=['POST'])
def api_local_photos():
    uploaded_files = request.files.getlist('photos')
    manual_name = (request.form.get('journey_name') or '').strip()

    if not uploaded_files:
        return jsonify({"error": "No photos uploaded"}), 400

    try:
        imported_assets = []
        for uploaded_file in uploaded_files:
            if not uploaded_file or not uploaded_file.filename:
                continue

            asset = create_local_asset(uploaded_file)
            imported_assets.append(asset)

        if not imported_assets:
            return jsonify({"error": "No valid photos uploaded"}), 400

        grouped_assets = cluster_assets_into_journeys(imported_assets, manual_name)

        created_posts = []
        with state_lock:
            for assets in grouped_assets:
                post = build_post_from_assets(assets, source="local-upload", manual_name=manual_name)
                state.photos_queue.append(post)
                created_posts.append(asdict(post))

            queue_size = len(state.photos_queue)

        socketio.emit('status_update', {
            'last_check': datetime.now().isoformat(),
            'queue_size': queue_size,
            'processed_count': len(state.processed_posts),
            'scheduled_count': len(state.scheduled_posts)
        })

        return jsonify({
            "success": True,
            "journeys_created": len(created_posts),
            "photos_imported": sum(len(assets) for assets in grouped_assets),
            "posts": created_posts,
        })
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@app.route('/api/generate', methods=['POST'])
def api_generate():
    data = request.json
    post_id = data.get('post_id')
    platforms = data.get('platforms', state.config.default_platforms)
    tone_key = data.get('tone_key', state.config.default_tone)
    custom = data.get('custom_instructions', '')
    
    post = None
    with state_lock:
        for p in list(state.photos_queue):
            if p.id == post_id:
                post = p
                break
        
        if not post:
            for p in state.processed_posts + state.scheduled_posts:
                if p.id == post_id:
                    post = p
                    if p in state.processed_posts:
                        state.processed_posts.remove(p)
                    if p in state.scheduled_posts:
                        state.scheduled_posts.remove(p)
                    state.photos_queue.append(p)
                    break
    
    if not post:
        return jsonify({"error": "Post not found"}), 404
    
    post.status = "analyzing"
    post.platforms = platforms
    post.tone_key = tone_key
    socketio.emit('generation_started', {'post_id': post_id})
    
    try:
        import tempfile
        tmp_path = None
        source_image_path = post.local_path if post.local_path and os.path.exists(post.local_path) else ''

        if source_image_path:
            generation_image_path = source_image_path
        else:
            ext = os.path.splitext(post.file_name)[1] or ".jpg"
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(decode_image_payload(post.image_base64))
                tmp_path = tmp.name
            generation_image_path = tmp_path

        journey_context = build_journey_context(post)
        
        content = generate_multi_platform_content(
            image_path=generation_image_path,
            platforms=platforms,
            tone_key=tone_key,
            custom_instructions=custom,
            config=state.config,
            journey_context=journey_context,
        )

        if tmp_path:
            os.unlink(tmp_path)
        
        post.generated_content = content
        post.vision_analysis = {
            "scene": content.get("scene_description", ""),
            "mood": content.get("mood", ""),
            "colors": content.get("dominant_colors", []),
            "tone": tone_key,
            "content_angle": content.get("content_angle", ""),
            "journey_label": post.journey_label,
            "journey_theme": post.journey_theme,
            "journey_location": post.journey_location,
            "photo_count": post.photo_count,
        }
        post.platform_previews = build_previews(post)
        post.status = "ready"
        post.updated_at = datetime.now().isoformat()
        
        with state_lock:
            if post in state.photos_queue:
                state.photos_queue.remove(post)
            if post not in state.processed_posts:
                state.processed_posts.append(post)
        
        return jsonify({
            "success": True,
            "post": asdict(post),
            "previews": post.platform_previews
        })
    except Exception as e:
        post.status = "pending"
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/batch-generate', methods=['POST'])
def api_batch_generate():
    data = request.json
    post_ids = data.get('post_ids', [])
    platforms = data.get('platforms', state.config.default_platforms)
    tone_key = data.get('tone_key', state.config.default_tone)
    
    results = []
    for post_id in post_ids:
        post = None
        with state_lock:
            for p in list(state.photos_queue):
                if p.id == post_id:
                    post = p
                    break
        if not post:
            continue
        
        post.status = "analyzing"
        post.platforms = platforms
        post.tone_key = tone_key
        socketio.emit('batch_progress', {'current': post_id, 'total': len(post_ids)})
        
        try:
            import tempfile
            ext = os.path.splitext(post.file_name)[1] or ".jpg"
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp.write(base64.b64decode(post.image_base64))
                tmp_path = tmp.name
            
            content = generate_multi_platform_content(
                image_path=tmp_path,
                platforms=platforms,
                tone_key=tone_key,
                config=state.config,
                journey_context=build_journey_context(post)
            )
            os.unlink(tmp_path)
            
            post.generated_content = content
            post.vision_analysis = {
                "scene": content.get("scene_description", ""),
                "mood": content.get("mood", ""),
                "colors": content.get("dominant_colors", []),
                "tone": tone_key,
                "journey_label": post.journey_label,
                "journey_theme": post.journey_theme,
                "journey_location": post.journey_location,
            }
            post.platform_previews = build_previews(post)
            post.status = "ready"
            post.updated_at = datetime.now().isoformat()
            
            with state_lock:
                if post in state.photos_queue:
                    state.photos_queue.remove(post)
                state.processed_posts.append(post)
            results.append({"post_id": post_id, "success": True})
            
        except Exception as e:
            post.status = "pending"
            results.append({"post_id": post_id, "success": False, "error": str(e)})
    
    return jsonify({"success": True, "results": results})


@app.route('/api/schedule', methods=['POST'])
def api_schedule():
    data = request.json
    post_id = data.get('post_id')
    scheduled_at = data.get('scheduled_at')
    platforms = data.get('platforms')
    
    with state_lock:
        for post in state.processed_posts:
            if post.id == post_id:
                post.scheduled_at = scheduled_at
                if platforms:
                    post.platforms = platforms
                if post not in state.scheduled_posts:
                    state.scheduled_posts.append(post)
                return jsonify({"success": True, "scheduled_at": scheduled_at})

    return jsonify({"error": "Post not found"}), 404
    


@app.route('/api/scheduled-posts')
def api_scheduled_posts():
    with state_lock:
        posts_raw = list(state.scheduled_posts)
    posts = []
    for post in posts_raw:
        d = asdict(post)
        if d.get('image_base64'):
            d['image_base64_preview'] = "data:image/jpeg;base64," + d['image_base64'][:50] + "..."
        posts.append(d)
    return jsonify(posts)


@app.route('/api/update-content', methods=['POST'])
def api_update_content():
    data = request.json
    post_id = data.get('post_id')
    platform = data.get('platform')
    updates = data.get('updates', {})
    
    with state_lock:
        for post in state.processed_posts + state.scheduled_posts:
            if post.id == post_id:
                plat = post.generated_content.get("platforms", {})
                if platform in plat:
                    if 'title' in updates and plat[platform].get('title_options'):
                        plat[platform]['title_options'][0] = updates['title']
                    if 'body' in updates or 'caption' in updates:
                        for key in ['body', 'caption', 'hook']:
                            if key in plat[platform]:
                                plat[platform][key] = updates.get('body', updates.get('caption', updates.get('hook', '')))
                    if 'hashtags' in updates:
                        plat[platform]['hashtags'] = updates['hashtags']
                
                post.updated_at = datetime.now().isoformat()
                post.platform_previews = build_previews(post)
                return jsonify({"success": True, "previews": post.platform_previews})
    
    return jsonify({"error": "Not found"}), 404


@app.route('/api/export/<post_id>', methods=['POST'])
def api_export(post_id):
    data = request.json or {}
    platform = data.get('platform', 'xiaohongshu')
    
    target_post = None
    with state_lock:
        for post in state.processed_posts + state.scheduled_posts:
            if post.id == post_id:
                target_post = post
                break
    if target_post is None:
        return jsonify({"error": "Post not found"}), 404
    
    post = target_post
    try:
        preview = post.platform_previews.get(platform, {})

        if platform == "xiaohongshu":
            image_sequence = preview.get('image_sequence', [])
            sequence_block = "\n".join([
                f"{item.get('position', index + 1)}. {item.get('role', '')} - {item.get('story_purpose', '')}"
                for index, item in enumerate(image_sequence)
            ])
            content = f"""# {preview.get('title', '')}

{preview.get('body', '')}

{' '.join(preview.get('hashtags', []))}

图序建议:
{sequence_block or '1. 封面总览 - 先用最能代表旅程的一张图开场'}

---
Music: {preview.get('music', '')}
Scheduled: {post.scheduled_at or 'Not scheduled'}
"""
        elif platform == "instagram":
            content = f"""{preview.get('caption', '')}

{' '.join(preview.get('hashtags', []))}

Location: {preview.get('location', '')}
Story: {preview.get('story_text', '')}
"""
        elif platform == "linkedin":
            content = f"""{preview.get('hook', '')}

{preview.get('body', '')}

Takeaway: {preview.get('takeaway', '')}

{preview.get('cta', '')}

{' '.join(preview.get('hashtags', []))}
"""
        else:
            content = json.dumps(preview, ensure_ascii=False, indent=2)

        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        name = f"{platform}_{ts}_{post.file_name}.md"

        if has_drive_token():
            service = get_drive_service()
            if not state.folder_ids:
                ensure_folder_structure(service)

            folder_key = f"{platform}_posts"
            fid = upload_text(service, state.folder_ids[folder_key], name, content)
            post.status = "published"
            return jsonify({"success": True, "drive_file_id": fid, "file_name": name, "destination": "drive"})

        export_path = save_local_export(name, content)
        post.status = "published"
        return jsonify({"success": True, "file_name": name, "destination": "local", "local_path": export_path})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/takeout-sync', methods=['POST'])
def api_takeout_sync():
    """Sync photos from Google Photos Takeout ZIP files in Drive."""
    data = request.json or {}
    target = data.get('target', 'draft')  # draft or selected

    if not has_drive_token():
        return jsonify({
            "error": "Google OAuth token is not configured. Use local photo upload for the MVP, or add ~/.hermes/google_token.json to enable Drive sync."
        }), 400
    
    try:
        service = get_drive_service()
        ensure_folder_structure(service)
        with state_lock:
            takeout_id = state.folder_ids.get("takeout")
            target_id = state.folder_ids.get(target)
        
        # Find ZIP files in takeout folder
        q = f"'{takeout_id}' in parents and trashed=false and mimeType='application/zip'"
        r = service.files().list(q=q, spaces="drive", fields="files(id, name)").execute()
        zips = r.get("files", [])
        
        if not zips:
            return jsonify({"success": True, "message": "No Takeout ZIP files found", "processed": 0})
        
        imported = 0
        for zf in zips:
            zip_data = download_photo(service, zf["id"])
            import tempfile, zipfile, shutil
            
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
                tmp.write(zip_data)
                tmp_path = tmp.name
            
            extract_dir = tempfile.mkdtemp()
            with zipfile.ZipFile(tmp_path, 'r') as z:
                z.extractall(extract_dir)
            
            # Find all photos in extracted Takeout
            for root, dirs, files in os.walk(extract_dir):
                for fname in files:
                    if fname.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp', '.heic')):
                        fpath = os.path.join(root, fname)
                        with open(fpath, 'rb') as img:
                            img_bytes = img.read()
                        
                        # Upload to Drive target folder
                        upload_file(service, target_id, fname, img_bytes, "image/jpeg")
                        imported += 1
            
            os.unlink(tmp_path)
            shutil.rmtree(extract_dir)
            
            # Optionally delete processed ZIP from takeout folder
            if data.get('delete_after_import', False):
                service.files().update(fileId=zf["id"], body={"trashed": True}).execute()
        
        return jsonify({"success": True, "imported": imported, "zip_files": len(zips)})
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/api/suggest-times', methods=['POST'])
def api_suggest_times():
    """Suggest optimal posting times for the next 7 days."""
    data = request.json or {}
    platforms = data.get('platforms', ['xiaohongshu'])
    
    suggestions = {}
    now = datetime.now()
    
    for platform in platforms:
        config = PLATFORM_CONFIGS.get(platform, {})
        times = config.get("optimal_posting_times", ["20:00"])
        best_days = SCHEDULING_CONFIG.get(f"{platform}_best_days", [])
        
        slots = []
        for day_offset in range(1, 8):
            date = now + timedelta(days=day_offset)
            day_name = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][date.weekday()]
            
            if best_days and day_name not in best_days:
                continue
            
            for t in times[:2]:  # top 2 times per day
                dt_str = date.strftime(f"%Y-%m-%d {t}")
                slots.append({
                    "datetime": dt_str,
                    "day": day_name,
                    "time": t,
                    "score": 95 if day_name in best_days else 80
                })
        
        suggestions[platform] = sorted(slots, key=lambda x: x["score"], reverse=True)[:10]
    
    return jsonify({"success": True, "suggestions": suggestions})


# ==================== WebSocket ====================

@socketio.on('connect')
def handle_connect():
    with state_lock:
        is_watching = state.is_watching
    emit('status', {'message': 'Connected', 'is_watching': is_watching})

@socketio.on('start_watching')
def handle_start_watching():
    if not has_drive_token():
        emit('status', {
            'is_watching': False,
            'error': 'Google OAuth token not found. Use local upload mode for the MVP.'
        })
        return

    with state_lock:
        already = state.is_watching
        state.is_watching = True
    if not already:
        socketio.start_background_task(watch_drive_folder)
    emit('status', {'is_watching': True})

@socketio.on('stop_watching')
def handle_stop_watching():
    with state_lock:
        state.is_watching = False
    emit('status', {'is_watching': False})


# ==================== Main ====================

if __name__ == '__main__':
    ensure_local_workspace()
    print("=" * 60)
    print("Multi-Platform Photo Content Pipeline")
    print("=" * 60)
    print(f"Open: http://localhost:5000")
    print(f"Provider: {state.config.llm_provider}")
    print(f"API Key: {'Yes' if state.config.active_api_key else 'No'}")
    print(f"Drive OAuth: {'Yes' if has_drive_token() else 'No'}")
    print("=" * 60)
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)
