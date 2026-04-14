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
import zipfile
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
from collections import deque

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

from config import PipelineConfig, PLATFORM_CONFIGS, SCHEDULING_CONFIG
from ai_generator import generate_multi_platform_content

HERMES_HOME = os.path.expanduser("~/.hermes")
TOKEN_PATH = os.path.join(HERMES_HOME, "google_token.json")

app = Flask(__name__)
app.config['SECRET_KEY'] = 'multi-platform-pipeline-secret'
socketio = SocketIO(app, cors_allowed_origins="*")

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
    scheduled_at: Optional[str]
    created_at: str
    updated_at: str


# ==================== Google Drive ====================

def get_drive_service():
    if state.drive_service:
        return state.drive_service
    creds = Credentials.from_authorized_user_file(TOKEN_PATH)
    if not creds.valid and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
    state.drive_service = build("drive", "v3", credentials=creds)
    return state.drive_service


def ensure_folder_structure(service, root_name="Photo Content"):
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
    
    state.folder_ids["root"] = root_id
    
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
    state.folder_ids["draft"] = sub(photos, "draft")
    state.folder_ids["selected"] = sub(photos, "selected")
    state.folder_ids["processed"] = sub(photos, "processed")
    state.folder_ids["takeout"] = sub(photos, "google-photos-takeout")
    
    output = sub(root_id, "Content-Output")
    for platform in ["xiaohongshu", "instagram", "linkedin"]:
        state.folder_ids[f"{platform}_posts"] = sub(output, f"{platform}-posts")
    
    state.folder_ids["scheduled"] = sub(output, "scheduled-posts")
    
    return state.folder_ids


def list_photos_in_folder(service, folder_id: str) -> List[Dict]:
    q = f"'{folder_id}' in parents and trashed=false"
    r = service.files().list(q=q, spaces="drive", fields="files(id, name, mimeType, modifiedTime, webViewLink)", pageSize=100).execute()
    return [f for f in r.get("files", []) if f.get("mimeType") in PHOTO_MIMETYPES]


def download_photo(service, file_id: str) -> bytes:
    from io import BytesIO
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
    meta = {"name": name, "parents": [parent_id]}
    media = MediaIoBaseUpload(BytesIO(content), mimetype=mimetype)
    f = service.files().create(body=meta, media_body=media, fields="id").execute()
    return f["id"]


def upload_text(service, parent_id: str, name: str, content: str) -> str:
    return upload_file(service, parent_id, name, content.encode("utf-8"))


# ==================== Watcher ====================

def watch_drive_folder():
    while state.is_watching:
        try:
            service = get_drive_service()
            if not state.folder_ids:
                ensure_folder_structure(service)
            
            photos = list_photos_in_folder(service, state.folder_ids["selected"])
            
            for photo in photos:
                pid = photo["id"]
                if any(p.drive_id == pid for p in list(state.photos_queue) + state.processed_posts + state.scheduled_posts):
                    continue
                
                print(f"New photo: {photo['name']}")
                img_data = download_photo(service, pid)
                img_b64 = base64.b64encode(img_data).decode("utf-8")
                
                post = PhotoPost(
                    id=f"post_{datetime.now().strftime('%Y%m%d%H%M%S')}_{pid[:8]}",
                    file_name=photo["name"],
                    drive_id=pid,
                    local_path=None,
                    image_base64=img_b64,
                    vision_analysis={},
                    generated_content={},
                    platform_previews={},
                    status="pending",
                    tone_key=state.config.default_tone,
                    platforms=state.config.default_platforms.copy(),
                    scheduled_at=None,
                    created_at=datetime.now().isoformat(),
                    updated_at=datetime.now().isoformat()
                )
                
                state.photos_queue.append(post)
                socketio.emit('new_photo_detected', {
                    'photo_id': post.id,
                    'file_name': post.file_name,
                    'thumbnail': f"data:image/jpeg;base64,{img_b64}"
                })
                move_file(service, pid, state.folder_ids["processed"], state.folder_ids["selected"])
            
            state.last_check = datetime.now().isoformat()
            socketio.emit('status_update', {
                'last_check': state.last_check,
                'queue_size': len(state.photos_queue),
                'processed_count': len(state.processed_posts),
                'scheduled_count': len(state.scheduled_posts)
            })
        except Exception as e:
            print(f"Watcher error: {e}")
        
        time.sleep(state.config.check_interval_seconds)


# ==================== Preview Builders ====================

def build_xiaohongshu_preview(post: PhotoPost, content: Dict) -> Dict:
    xhs = content.get("xiaohongshu", {})
    return {
        "cover_image": f"data:image/jpeg;base64,{post.image_base64}" if post.image_base64 else None,
        "title": xhs.get("title_options", [""])[0] if xhs.get("title_options") else "",
        "body": xhs.get("body", ""),
        "hashtags": xhs.get("hashtags", []),
        "likes": "1.2k", "saves": "856", "comments": "128",
        "author": {"name": "Your Name", "avatar": None, "followers": "5.2k"},
        "location": "📍 发现美好", "post_time": "刚刚",
        "music": xhs.get("music_suggestion", "🎵 原声"),
    }


def build_instagram_preview(post: PhotoPost, content: Dict) -> Dict:
    ig = content.get("instagram", {})
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
    li = content.get("linkedin", {})
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
        "tones": {k: v["name"] for k, v in XIAOHONGSHU_TONES.items()},
        "platforms": {k: {"name": v["name"], "icon": v["icon"]} for k, v in PLATFORM_CONFIGS.items()},
        "scheduling": SCHEDULING_CONFIG,
    })


@app.route('/api/config', methods=['POST'])
def api_update_config():
    data = request.json
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
    all_posts = list(state.photos_queue) + state.processed_posts + state.scheduled_posts
    out = []
    for post in all_posts:
        d = asdict(post)
        if d.get('image_base64'):
            d['image_base64_preview'] = "data:image/jpeg;base64," + d['image_base64'][:50] + "..."
        out.append(d)
    return jsonify(out)


@app.route('/api/generate', methods=['POST'])
def api_generate():
    data = request.json
    post_id = data.get('post_id')
    platforms = data.get('platforms', state.config.default_platforms)
    tone_key = data.get('tone_key', state.config.default_tone)
    custom = data.get('custom_instructions', '')
    
    post = None
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
        ext = os.path.splitext(post.file_name)[1] or ".jpg"
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(base64.b64decode(post.image_base64))
            tmp_path = tmp.name
        
        content = generate_multi_platform_content(
            image_path=tmp_path,
            platforms=platforms,
            tone_key=tone_key,
            custom_instructions=custom,
            config=state.config
        )
        
        os.unlink(tmp_path)
        
        post.generated_content = content
        post.vision_analysis = {
            "scene": content.get("scene_description", ""),
            "mood": content.get("mood", ""),
            "colors": content.get("dominant_colors", []),
            "tone": tone_key,
            "content_angle": content.get("content_angle", "")
        }
        post.platform_previews = build_previews(post)
        post.status = "ready"
        post.updated_at = datetime.now().isoformat()
        
        if post in state.photos_queue:
            state.photos_queue.remove(post)
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
                config=state.config
            )
            os.unlink(tmp_path)
            
            post.generated_content = content
            post.vision_analysis = {
                "scene": content.get("scene_description", ""),
                "mood": content.get("mood", ""),
                "colors": content.get("dominant_colors", []),
                "tone": tone_key
            }
            post.platform_previews = build_previews(post)
            post.status = "ready"
            post.updated_at = datetime.now().isoformat()
            
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
    posts = []
    for post in state.scheduled_posts:
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
    
    for post in state.processed_posts + state.scheduled_posts:
        if post.id == post_id:
            try:
                service = get_drive_service()
                if not state.folder_ids:
                    ensure_folder_structure(service)
                
                preview = post.platform_previews.get(platform, {})
                folder_key = f"{platform}_posts"
                
                if platform == "xiaohongshu":
                    content = f"""# {preview.get('title', '')}

{preview.get('body', '')}

{' '.join(preview.get('hashtags', []))}

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
                fid = upload_text(service, state.folder_ids[folder_key], name, content)
                
                post.status = "published"
                return jsonify({"success": True, "drive_file_id": fid, "file_name": name})
            except Exception as e:
                return jsonify({"error": str(e)}), 500
    
    return jsonify({"error": "Post not found"}), 404


@app.route('/api/takeout-sync', methods=['POST'])
def api_takeout_sync():
    """Sync photos from Google Photos Takeout ZIP files in Drive."""
    data = request.json or {}
    target = data.get('target', 'draft')  # draft or selected
    
    try:
        service = get_drive_service()
        ensure_folder_structure(service)
        takeout_id = state.folder_ids["takeout"]
        
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
                        dest_id = state.folder_ids[target]
                        upload_file(service, dest_id, fname, img_bytes, "image/jpeg")
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
    emit('status', {'message': 'Connected', 'is_watching': state.is_watching})

@socketio.on('start_watching')
def handle_start_watching():
    if not state.is_watching:
        state.is_watching = True
        threading.Thread(target=watch_drive_folder, daemon=True).start()
    emit('status', {'is_watching': True})

@socketio.on('stop_watching')
def handle_stop_watching():
    state.is_watching = False
    emit('status', {'is_watching': False})


# ==================== Main ====================

if __name__ == '__main__':
    print("=" * 60)
    print("Multi-Platform Photo Content Pipeline")
    print("=" * 60)
    print(f"Open: http://localhost:5000")
    print(f"Provider: {state.config.llm_provider}")
    print(f"API Key: {'Yes' if state.config.active_api_key else 'No'}")
    print("=" * 60)
    socketio.run(app, host='0.0.0.0', port=5000, debug=True, use_reloader=False)
