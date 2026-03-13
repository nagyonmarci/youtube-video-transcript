import asyncio
import os
import tempfile
import http.cookiejar
from datetime import datetime, timezone
from typing import Optional, Iterable
import json
import subprocess

import asyncpg
import yt_dlp
from requests import Session
from youtube_transcript_api import YouTubeTranscriptApi

from app.config import settings

# Global task queue
_task_queue = asyncio.Queue()

async def get_queue():
    return _task_queue

async def worker_loop():
    """Background worker that processes tasks serially from the queue."""
    print("🚀🚀🚀 [Worker] SERIAL LOOP STARTED AND WAITING FOR TASKS 🚀🚀🚀")
    while True:
        task = await _task_queue.get()
        try:
            task_type, payload = task # payload is channel_id
            if task_type == 'process':
                await _run_process_channel(payload)
            elif task_type == 'refresh':
                await _run_refresh_metadata(payload)
        except Exception as e:
            print(f"[Worker] ❌ Error in worker loop: {e}")
        finally:
            _task_queue.task_done()

async def process_channel(channel_id: int):
    """Adds a processing task to the queue."""
    await _task_queue.put(('process', channel_id))
    print(f"[Worker] 📥 Queued channel processing (ID: {channel_id})")

async def refresh_channel_metadata(channel_id: int):
    """Adds a metadata refresh task to the queue."""
    await _task_queue.put(('refresh', channel_id))
    print(f"[Worker] 📥 Queued metadata refresh (ID: {channel_id})")

async def clear_worker_queue():
    """Clears all pending tasks from the queue."""
    removed = 0
    while not _task_queue.empty():
        try:
            _task_queue.get_nowait()
            _task_queue.task_done()
            removed += 1
        except asyncio.QueueEmpty:
            break
    print(f"[Worker] 🛑 Queue cleared. Removed {removed} tasks.")
    return removed

def _create_ytt_session(cookie_path: Optional[str]) -> YouTubeTranscriptApi:
    """Helper to create a YouTubeTranscriptApi instance with a session that has cookies and browser-like headers."""
    session = Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    })
    if cookie_path and os.path.exists(cookie_path):
        try:
            cj = http.cookiejar.MozillaCookieJar(cookie_path)
            cj.load(ignore_discard=True, ignore_expires=True)
            session.cookies = cj
        except Exception as e:
            print(f"    ⚠️ Cookie load error: {e}")
    return YouTubeTranscriptApi(http_client=session)

async def _fetch_transcript_with_ytdlp(video_id: str, cookie_path: Optional[str]) -> Optional[str]:
    """Fallback: use yt-dlp to fetch auto-generated transcripts."""
    tmp_dir = tempfile.mkdtemp()
    try:
        cmd = [
            'yt-dlp', '--quiet', '--skip-download', 
            '--write-auto-subs', '--sub-langs', 'en', 
            '--sub-format', 'json3', '--remote-components', 'ejs:github',
            '--impersonate', 'chrome',
            '--output', f'{tmp_dir}/%(id)s',
            f'https://www.youtube.com/watch?v={video_id}'
        ]
        if cookie_path:
            cmd.extend(['--cookies', cookie_path])
        
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        # Look for the generated file
        for f in os.listdir(tmp_dir):
            if f.endswith('.json3'):
                with open(os.path.join(tmp_dir, f), 'r') as jf:
                    data = json.load(jf)
                    text = ' '.join([e.get('segs', [{}])[0].get('utf8', '') for e in data.get('events', []) if e.get('segs')])
                    if text.strip():
                        print(f"    ✅ yt-dlp fallback SUCCESS for {video_id}")
                        return text
        
        # If we didn't find a file, but had output/error
        if proc.returncode != 0:
            err_msg = stderr.decode().strip()
            print(f"    ⚠️ yt-dlp fallback failed for {video_id} (code {proc.returncode}): {err_msg[:100]}...")
            
    except Exception as e:
        print(f"    ⚠️ yt-dlp fallback fatal error for {video_id}: {e}")
    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)
    return None

async def _run_process_channel(channel_id: int):
    """Actual logic for processing a channel."""
    print(f"[Worker] Connecting to: {settings.database_url}")
    conn = await asyncpg.connect(settings.database_url)
    try:
        # Get channel name and owner_id
        row = await conn.fetchrow("SELECT name, owner_id FROM channels WHERE id = $1", channel_id)
        if not row:
            print(f"[Worker] Channel {channel_id} not found.")
            return
        
        channel_name, owner_id = row['name'], row['owner_id']
        
        # Get user cookies
        cookie_text = await conn.fetchval("SELECT youtube_cookies FROM users WHERE id = $1", owner_id)
        
        cookie_path = None
        if cookie_text:
            cookie_path = f"/tmp/cookies_{owner_id}.txt"
            with open(cookie_path, "w") as f:
                f.write(cookie_text)

        # 1. Get video list using yt-dlp
        ydl_opts = {
            'quiet': True,
            'extract_flat': True,
            'force_generic_extractor': False,
            'remote_components': ['ejs:github'],
        }
        if cookie_path:
            ydl_opts['cookiefile'] = cookie_path

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f"https://www.youtube.com/@{channel_name}/videos", download=False)
                if not info or not info.get('entries'):
                    print(f"[{channel_name}] ⚠️ No videos found.")
                    return
                
                videos_found = info.get('entries', [])
                print(f"[{channel_name}] Found {len(videos_found)} videos.")
                
                for entry in videos_found:
                    video_id = entry.get('id')
                    if not video_id: continue
                    
                    video_url = f"https://www.youtube.com/watch?v={video_id}"
                    
                    # Check if already exists
                    exists = await conn.fetchrow("SELECT id, transcript FROM videos WHERE video_id = $1 AND owner_id = $2", video_id, owner_id)
                    
                    if exists and exists['transcript']:
                        continue
                    
                    print(f"  🔄 Processing: {entry.get('title')}")
                    
                    # Get detailed info if needed
                    duration = entry.get('duration')
                    upload_date_str = entry.get('upload_date')
                    uploaded_at = None
                    if upload_date_str:
                        try:
                            uploaded_at = datetime.strptime(upload_date_str, "%Y%m%d").replace(tzinfo=timezone.utc)
                        except: pass

                    # Phase 1: YouTubeTranscriptApi
                    transcript_text = None
                    try:
                        ytt = _create_ytt_session(cookie_path)
                        tlist = ytt.list(video_id)
                        try:
                            t = tlist.find_transcript(['en', 'en-US', 'en-GB', 'hu'])
                        except:
                            t = next(iter(tlist))
                        
                        transcript_text = ' '.join([s['text'] for s in t.fetch()])
                        if transcript_text:
                            print(f"    ✅ YouTubeTranscriptApi SUCCESS for {video_id}")
                    except Exception as te:
                        print(f"    ⚠️ YouTubeTranscriptApi error for {video_id}, trying yt-dlp fallback...")
                        # Phase 2: yt-dlp fallback
                        transcript_text = await _fetch_transcript_with_ytdlp(video_id, cookie_path)

                    # Upsert
                    if transcript_text:
                        if exists:
                            await conn.execute(
                                "UPDATE videos SET title=$1, url=$2, transcript=$3, duration=$4, uploaded_at=$5, processed_at=NOW(), status='processed' WHERE id=$6",
                                entry.get('title'), video_url, transcript_text, duration, uploaded_at, exists['id']
                            )
                        else:
                            await conn.execute(
                                """INSERT INTO videos(video_id, channel_id, channel_name, title, url, transcript, duration, uploaded_at, status, owner_id)
                                   VALUES($1,$2,$3,$4,$5,$6,$7,$8,'processed',$9)""",
                                video_id, channel_id, channel_name, entry.get('title'), video_url, transcript_text, duration, uploaded_at, owner_id
                            )
                    else:
                        print(f"    ❌ FAILED to get transcript for {video_id}")
                    
                    # Rate limit (30s-60s wait to be safe)
                    await asyncio.sleep(60)
                    
        except Exception as e:
            print(f"[{channel_name}] ❌ Error: {e}")
            
    finally:
        await conn.close()
        if cookie_path and os.path.exists(cookie_path):
            try: os.remove(cookie_path)
            except: pass

async def _run_refresh_metadata(channel_id: int):
    await _run_process_channel(channel_id)
