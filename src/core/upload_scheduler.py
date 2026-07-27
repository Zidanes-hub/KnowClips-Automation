"""Upload scheduler: upload branded clips to YouTube via Data API v3 with a
future publishAt date, so content stays buffered even if the laptop is offline.

Auth: OAuth 2.0 desktop flow. Put client_secret.json in the project root
(from Google Cloud Console -> APIs & Services -> Credentials). The first run
opens a browser to authorize; the token is cached in token.json.

Scheduling: each new upload is set to publish `buffer_days` from now, at
`publish_hour`, spreading multiple clips one day apart so the queue drains
gradually.
"""
import os
import sys
import glob
from datetime import datetime, timedelta, timezone
from core.utils import load_config, setup_logger, storage_paths, read_json, write_json

LOG = setup_logger("uploader")

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
UPLOAD_STATE = "upload_state.json"  # tracks which files were uploaded + next slot


def get_service(cfg):
    """Build an authenticated YouTube Data API client."""
    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError:
        LOG.error("Google API libs missing. Run: pip install -r requirements.txt")
        return None

    creds = None
    token_file = cfg.get("token_file", "token.json")
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            secret = cfg.get("client_secret", "client_secret.json")
            if not os.path.exists(secret):
                LOG.error(f"Missing {secret}. Download OAuth desktop credentials from Google Cloud.")
                return None
            flow = InstalledAppFlow.from_client_secrets_file(secret, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_file, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    return build("youtube", "v3", credentials=creds)


def next_publish_time(cfg, state):
    """Compute the next publishAt (RFC3339 UTC). Enforce 1 video per 24 hours."""
    last_publish_str = state.get("last_publish_time")
    
    schedule_cfg = cfg.get("upload_schedule", {})
    upload_time_str = schedule_cfg.get("upload_time", "19:00")
    min_gap_hours = schedule_cfg.get("min_gap_between_videos_hours", 24)
    buffer_days = cfg.get("buffer_days", 1)
    
    hour, minute = map(int, upload_time_str.split(':'))
    
    now_utc = datetime.now(timezone.utc)
    # Convert to WIB (UTC+7) since user targets Indonesia prime time
    wib_tz = timezone(timedelta(hours=7))
    now_wib = now_utc.astimezone(wib_tz)
    
    if not last_publish_str:
        # Start fresh
        base_wib = now_wib + timedelta(days=buffer_days)
        target_wib = base_wib.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return target_wib.astimezone(timezone.utc)
        
    last_publish_utc = datetime.fromisoformat(last_publish_str)
    
    # If the queue is empty and last publish was far in the past, reset to tomorrow
    if last_publish_utc < now_utc:
        base_wib = now_wib + timedelta(days=buffer_days)
        target_wib = base_wib.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return target_wib.astimezone(timezone.utc)
        
    # Contiguous scheduling: enforce min_gap_hours (e.g., 24 hours)
    next_publish_utc = last_publish_utc + timedelta(hours=min_gap_hours)
    
    # Align perfectly to the target time in WIB
    next_publish_wib = next_publish_utc.astimezone(wib_tz)
    next_publish_wib = next_publish_wib.replace(hour=hour, minute=minute, second=0, microsecond=0)
    
    # If the exact alignment falls earlier than the min gap, push it to the next day
    if next_publish_wib.astimezone(timezone.utc) < last_publish_utc + timedelta(hours=min_gap_hours):
        next_publish_wib += timedelta(days=1)
        
    return next_publish_wib.astimezone(timezone.utc)


def upload_one(service, video, cfg, publish_at):
    """Upload a single video, scheduled private->public at publish_at."""
    from googleapiclient.http import MediaFileUpload
    
    # Read custom metadata if available
    base_name = os.path.basename(video).replace("_branded.mp4", "")
    clips_dir = os.path.join(cfg.get("storage_dir", "storage"), "clips")
    meta_path = os.path.join(clips_dir, f"{base_name}_metadata.json")
    
    title = base_name
    desc_addon = ""
    if os.path.exists(meta_path):
        meta = read_json(meta_path, {})
        title = meta.get("title", title)
        original_url = meta.get("original_url") or meta.get("channel_url", "")
        if original_url:
            desc_addon = f"\n\nCredit & Video Asli: {original_url}"
            
    body = {
        "snippet": {
            "title": title[:95],
            "description": f"Auto-generated by KnowClips.\n#shorts #edukasi #fakta{desc_addon}",
            "tags": ["knowclips", "shorts", "edukasi", "fakta", "wawasan"],
            "categoryId": str(cfg.get("category_id", "27")),
        },
        "status": {
            "privacyStatus": "private",
            "publishAt": publish_at.isoformat(),
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(video, chunksize=-1, resumable=True)
    LOG.info(f"Uploading '{title[:45]}' (publish {publish_at.date()} {publish_at.hour}:00 UTC)")
    request = service.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    retry_count = 0
    MAX_RETRIES = 5
    
    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                LOG.info(f"  ...{int(status.progress() * 100)}%")
            retry_count = 0  # reset on successful chunk
        except Exception as e:
            retry_count += 1
            if retry_count > MAX_RETRIES:
                raise Exception(f"Failed to upload after {MAX_RETRIES} retries: {e}")
            LOG.warning(f"  Network error during upload (retry {retry_count}/{MAX_RETRIES}). Waiting {2**retry_count}s...")
            import time
            time.sleep(2 ** retry_count)
            
    video_id = response['id']
    LOG.info(f"  done -> https://youtu.be/{video_id}")
    
    # Upload custom thumbnail if exists
    stem = base_name
    thumb_dir = os.path.join(cfg.get("storage_dir", "storage"), "thumbnails")
    thumb_path = os.path.join(thumb_dir, stem + "_thumbnail.jpg")
    if os.path.exists(thumb_path):
        try:
            LOG.info(f"  Uploading custom thumbnail...")
            service.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumb_path)
            ).execute()
            LOG.info(f"  Thumbnail uploaded successfully.")
        except Exception as e:
            LOG.warning(f"  Failed to upload custom thumbnail: {e}")
            
    return video_id


def run(cfg):
    paths = storage_paths(cfg)
    videos = sorted(glob.glob(os.path.join(paths["output"], "*_branded.mp4")))
    if not videos:
        LOG.info(f"No branded videos to upload in {paths['output']}")
        return []

    state = read_json(UPLOAD_STATE, {"uploaded": [], "slots_used": 0})
    uploaded_set = set(state.get("uploaded", []))
    pending = [v for v in videos if os.path.basename(v) not in uploaded_set]
    if not pending:
        LOG.info("All branded videos already uploaded.")
        return []

    service = get_service(cfg)
    if service is None:
        return []

    done = []
    
    # Target date logic for daily physical upload limit
    wib_tz = timezone(timedelta(hours=7))
    today_wib_str = datetime.now(timezone.utc).astimezone(wib_tz).strftime("%Y-%m-%d")
    
    # Content rules from config
    content_rules = cfg.get("content_rules", {})
    min_gap_days = content_rules.get("min_gap_same_source_days", 5)
    
    import difflib
    import re
    
    for video in pending:
        if state.get("last_upload_date") == today_wib_str:
            LOG.info("Daily limit reached. Next upload scheduled for 19:00 tomorrow.")
            break
            
        base_name = os.path.basename(video).replace("_branded.mp4", "")
        clips_dir = os.path.join(cfg.get("storage_dir", "storage"), "clips")
        meta_path = os.path.join(clips_dir, f"{base_name}_metadata.json")
        
        # 1. Title Similarity Check
        title = base_name
        if os.path.exists(meta_path):
            meta = read_json(meta_path, {})
            title = meta.get("title", title)
            
        recent_titles = state.get("recent_titles", [])
        is_similar = False
        for rt in recent_titles[-10:]:
            similarity = difflib.SequenceMatcher(None, title, rt).ratio()
            if similarity > 0.70:
                is_similar = True
                break
                
        if is_similar:
            LOG.warning(f"Warning: Similar title detected ({title}), skipping.")
            # Tandai sebagai di-skip / di-uploaded agar tidak looping terus
            uploaded_set.add(os.path.basename(video))
            state["uploaded"] = sorted(uploaded_set)
            write_json(UPLOAD_STATE, state)
            continue
            
        # 2. Extract Source Channel and check min_gap_same_source_days
        stem = re.sub(r'_clip\d+$', '', base_name)
        info_path = os.path.join(paths["downloads"], stem + ".info.json")
        source_channel = "Unknown"
        if os.path.exists(info_path):
            info = read_json(info_path, {})
            source_channel = info.get("channel") or info.get("uploader") or "Unknown"
            
        sources_used = state.get("sources_used", {})
        last_used_date_str = sources_used.get(source_channel)
        if last_used_date_str:
            last_used_date = datetime.strptime(last_used_date_str, "%Y-%m-%d").date()
            today_date = datetime.now(timezone.utc).astimezone(wib_tz).date()
            if (today_date - last_used_date).days < min_gap_days:
                LOG.info(f"Skipping video from {source_channel}, already used within {min_gap_days} days.")
                continue

        publish_at = next_publish_time(cfg, state)
        try:
            vid_id = upload_one(service, video, cfg, publish_at)
        except Exception as e:  # noqa: BLE001
            LOG.error(f"Upload failed for {os.path.basename(video)}: {e}")
            continue
        uploaded_set.add(os.path.basename(video))
        state["slots_used"] = state.get("slots_used", 0) + 1
        state["last_publish_time"] = publish_at.isoformat()
        state["uploaded"] = sorted(uploaded_set)
        
        # Update our new tracking fields
        state["last_upload_date"] = today_wib_str
        state["last_upload_time"] = datetime.now(timezone.utc).astimezone(wib_tz).strftime("%H:%M")
        
        sources_used[source_channel] = today_wib_str
        state["sources_used"] = sources_used
        
        recent_titles.append(title)
        state["recent_titles"] = recent_titles[-10:]  # Keep last 10
        
        write_json(UPLOAD_STATE, state)
        done.append(vid_id)
    LOG.info(f"Scheduled {len(done)} upload(s).")
    return done


def main():
    cfg = load_config()
    run(cfg)


if __name__ == "__main__":
    main()
