import re

# Fix app.py
with open("app.py", "r") as f:
    content = f.read()

# 1. Fix syntax error on line 35
content = content.replace(
    'TOKEN_PATH=os.pat...OME, "google_token.json")',
    'TOKEN_PATH = os.path.join(HERMES_HOME, "google_token.json")'
)

# 2. Add state_lock after state = PipelineState()
content = content.replace(
    "state = PipelineState()",
    "state = PipelineState()\nstate_lock = threading.Lock()"
)

# 3. Fix get_drive_service to check token existence
def old_get_drive_service():
    return '''def get_drive_service():
    if state.drive_service:
        return state.drive_service
    creds = Credentials.from_authorized_user_file(TOKEN_PATH)
    if not creds.valid and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
    state.drive_service = build("drive", "v3", credentials=creds)
    return state.drive_service'''

def new_get_drive_service():
    return '''def get_drive_service():
    if state.drive_service:
        return state.drive_service
    if not os.path.exists(TOKEN_PATH):
        raise FileNotFoundError(f"Google token not found at {TOKEN_PATH}. Run OAuth setup first.")
    creds = Credentials.from_authorized_user_file(TOKEN_PATH)
    if not creds.valid and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
    with state_lock:
        state.drive_service = build("drive", "v3", credentials=creds)
    return state.drive_service'''

content = content.replace(old_get_drive_service(), new_get_drive_service())

# 4. Fix watch_drive_folder to use locks and better exception handling
old_watch = '''def watch_drive_folder():
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
        
        time.sleep(state.config.check_interval_seconds)'''

new_watch = '''def watch_drive_folder():
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
            
            for photo in photos:
                pid = photo["id"]
                with state_lock:
                    known_ids = {p.drive_id for p in list(state.photos_queue) + state.processed_posts + state.scheduled_posts}
                if pid in known_ids:
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
                
                with state_lock:
                    state.photos_queue.append(post)
                    queue_size = len(state.photos_queue)
                    processed_count = len(state.processed_posts)
                    scheduled_count = len(state.scheduled_posts)
                socketio.emit('new_photo_detected', {
                    'photo_id': post.id,
                    'file_name': post.file_name,
                    'thumbnail': f"data:image/jpeg;base64,{img_b64}"
                })
                move_file(service, pid, folder_processed, folder_selected)
            
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
        
        time.sleep(state.config.check_interval_seconds)'''

content = content.replace(old_watch, new_watch)

# 5. Fix WebSocket handlers to use background task and locks
old_ws = '''@socketio.on('connect')
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
    emit('status', {'is_watching': False})'''

new_ws = '''@socketio.on('connect')
def handle_connect():
    with state_lock:
        is_watching = state.is_watching
    emit('status', {'message': 'Connected', 'is_watching': is_watching})

@socketio.on('start_watching')
def handle_start_watching():
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
    emit('status', {'is_watching': False})'''

content = content.replace(old_ws, new_ws)

# 6. Fix api_status to use locks
old_api_status = '''@app.route('/api/status')
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
    })'''

new_api_status = '''@app.route('/api/status')
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
            "tones": {k: v["name"] for k, v in XIAOHONGSHU_TONES.items()},
            "platforms": {k: {"name": v["name"], "icon": v["icon"]} for k, v in PLATFORM_CONFIGS.items()},
            "scheduling": SCHEDULING_CONFIG,
        })'''

content = content.replace(old_api_status, new_api_status)

# 7. Fix ensure_folder_structure to use lock when mutating state.folder_ids
old_ensure = '''def ensure_folder_structure(service, root_name="Photo Content"):'''
new_ensure = '''def ensure_folder_structure(service, root_name="Photo Content"):
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
    return state.folder_ids'''

# For ensure_folder_structure, we need to remove the old body and replace with new one.
# Since it's a large function, let's do a more targeted replacement:
start = content.find('def ensure_folder_structure(service, root_name="Photo Content"):')
end_marker = '\n\ndef list_photos_in_folder'
end = content.find(end_marker)
if start != -1 and end != -1:
    content = content[:start] + new_ensure + content[end:]

# 8. Fix socketio.run debug mode
content = content.replace(
    "socketio.run(app, host='0.0.0.0', port=5000, debug=True, use_reloader=False)",
    "socketio.run(app, host='0.0.0.0', port=5000, debug=False, use_reloader=False)"
)

# 9. Fix api_posts to use lock
old_api_posts = '''@app.route('/api/posts')
def api_posts():
    all_posts = list(state.photos_queue) + state.processed_posts + state.scheduled_posts
    out = []
    for post in all_posts:
        d = asdict(post)
        if d.get('image_base64'):
            d['image_base64_preview'] = "data:image/jpeg;base64," + d['image_base64'][:50] + "..."
        out.append(d)
    return jsonify(out)'''

new_api_posts = '''@app.route('/api/posts')
def api_posts():
    with state_lock:
        all_posts = list(state.photos_queue) + state.processed_posts + state.scheduled_posts
    out = []
    for post in all_posts:
        d = asdict(post)
        if d.get('image_base64'):
            d['image_base64_preview'] = "data:image/jpeg;base64," + d['image_base64'][:50] + "..."
        out.append(d)
    return jsonify(out)'''

content = content.replace(old_api_posts, new_api_posts)

# 10. Fix api_update_config to use lock
old_update_config = '''@app.route('/api/config', methods=['POST'])
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
    }})'''

new_update_config = '''@app.route('/api/config', methods=['POST'])
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
        }})'''

content = content.replace(old_update_config, new_update_config)

# 11. Fix api_generate to use locks where needed
old_generate = '''    post = None
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
                break'''

new_generate = '''    post = None
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
                    break'''

content = content.replace(old_generate, new_generate)

old_generate2 = '''        if post in state.photos_queue:
            state.photos_queue.remove(post)
        state.processed_posts.append(post)'''

new_generate2 = '''        with state_lock:
            if post in state.photos_queue:
                state.photos_queue.remove(post)
            state.processed_posts.append(post)'''

content = content.replace(old_generate2, new_generate2)

# 12. Fix api_batch_generate
old_batch = '''    for post_id in post_ids:
        post = None
        for p in list(state.photos_queue):
            if p.id == post_id:
                post = p
                break
        if not post:
            continue'''

new_batch = '''    for post_id in post_ids:
        post = None
        with state_lock:
            for p in list(state.photos_queue):
                if p.id == post_id:
                    post = p
                    break
        if not post:
            continue'''

content = content.replace(old_batch, new_batch)

old_batch2 = '''            if post in state.photos_queue:
                state.photos_queue.remove(post)
            state.processed_posts.append(post)'''

new_batch2 = '''            with state_lock:
                if post in state.photos_queue:
                    state.photos_queue.remove(post)
                state.processed_posts.append(post)'''

content = content.replace(old_batch2, new_batch2)

# 13. Fix api_schedule
old_schedule = '''    for post in state.processed_posts:
        if post.id == post_id:
            post.scheduled_at = scheduled_at
            if platforms:
                post.platforms = platforms
            if post not in state.scheduled_posts:
                state.scheduled_posts.append(post)
            return jsonify({"success": True, "scheduled_at": scheduled_at})'''

new_schedule = '''    with state_lock:
        for post in state.processed_posts:
            if post.id == post_id:
                post.scheduled_at = scheduled_at
                if platforms:
                    post.platforms = platforms
                if post not in state.scheduled_posts:
                    state.scheduled_posts.append(post)
                return jsonify({"success": True, "scheduled_at": scheduled_at})'''

content = content.replace(old_schedule, new_schedule)

# 14. Fix api_update_content
old_update_content = '''    for post in state.processed_posts + state.scheduled_posts:
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
            return jsonify({"success": True, "previews": post.platform_previews})'''

new_update_content = '''    with state_lock:
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
                return jsonify({"success": True, "previews": post.platform_previews})'''

content = content.replace(old_update_content, new_update_content)

# 15. Fix api_export
old_export = '''    for post in state.processed_posts + state.scheduled_posts:
        if post.id == post_id:
            try:'''

new_export = '''    target_post = None
    with state_lock:
        for post in state.processed_posts + state.scheduled_posts:
            if post.id == post_id:
                target_post = post
                break
    if target_post is None:
        return jsonify({"error": "Post not found"}), 404
    
    post = target_post
    try:'''

content = content.replace(old_export, new_export)

# Remove the old trailing return for api_export since we moved it up
old_export_return = '''    return jsonify({"error": "Post not found"}), 404


@app.route('/api/scheduled-posts')'''
new_export_return = '''

@app.route('/api/scheduled-posts')'''
content = content.replace(old_export_return, new_export_return)

# 16. Fix api_scheduled_posts
old_scheduled_posts = '''@app.route('/api/scheduled-posts')
def api_scheduled_posts():
    posts = []
    for post in state.scheduled_posts:
        d = asdict(post)
        if d.get('image_base64'):
            d['image_base64_preview'] = "data:image/jpeg;base64," + d['image_base64'][:50] + "..."
        posts.append(d)
    return jsonify(posts)'''

new_scheduled_posts = '''@app.route('/api/scheduled-posts')
def api_scheduled_posts():
    with state_lock:
        posts_raw = list(state.scheduled_posts)
    posts = []
    for post in posts_raw:
        d = asdict(post)
        if d.get('image_base64'):
            d['image_base64_preview'] = "data:image/jpeg;base64," + d['image_base64'][:50] + "..."
        posts.append(d)
    return jsonify(posts)'''

content = content.replace(old_scheduled_posts, new_scheduled_posts)

# 17. Fix api_takeout_sync to use lock for state.folder_ids
old_takeout = '''        service = get_drive_service()
        ensure_folder_structure(service)
        takeout_id = state.folder_ids["takeout"]'''

new_takeout = '''        service = get_drive_service()
        ensure_folder_structure(service)
        with state_lock:
            takeout_id = state.folder_ids.get("takeout")
            target_id = state.folder_ids.get(target)'''

content = content.replace(old_takeout, new_takeout)

old_takeout2 = '''                        # Upload to Drive target folder
                        dest_id = state.folder_ids[target]
                        upload_file(service, dest_id, fname, img_bytes, "image/jpeg")'''

new_takeout2 = '''                        # Upload to Drive target folder
                        upload_file(service, target_id, fname, img_bytes, "image/jpeg")'''

content = content.replace(old_takeout2, new_takeout2)

with open("app.py", "w") as f:
    f.write(content)

print("app.py patched")

# Fix check_setup.py token path
with open("check_setup.py", "r") as f:
    c = f.read()
c = c.replace('os.path.join(hermes_home, "google_token.json")', 'os.path.join(hermes_home, "google_token.json")')
# check_setup already looks correct, just ensure it matches
with open("check_setup.py", "w") as f:
    f.write(c)

print("check_setup.py ok")
