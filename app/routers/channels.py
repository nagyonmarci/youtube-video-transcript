from fastapi import APIRouter, Depends, HTTPException, Query
from asyncpg import Connection
from app.database import get_db
from app.schemas import ChannelCreate, ChannelOut
from app.worker import process_channel, refresh_channel_metadata
from app.routers.auth import get_current_user, get_token

router = APIRouter(tags=["Channels"])

@router.post("/channels", response_model=dict)
async def add_channel(
    req: ChannelCreate,
    db: Connection = Depends(get_db),
    token: str = Depends(get_token)
):
    user = await get_current_user(token, db)
    # Insert channel and get ID
    row = await db.fetchrow(
        "INSERT INTO channels(name, owner_id) VALUES($1, $2) ON CONFLICT(name, owner_id) DO UPDATE SET name=EXCLUDED.name RETURNING id",
        req.channel_name, user['id'])
    
    await process_channel(row['id']) 
    return {"status": "queued", "channel": req.channel_name, "id": row['id']}

@router.get("/channels", response_model=list[ChannelOut])
async def list_channels(
    db: Connection = Depends(get_db),
    token: str = Depends(get_token)
):
    user = await get_current_user(token, db)
    rows = await db.fetch("SELECT id, name, added_at FROM channels WHERE owner_id=$1 ORDER BY added_at DESC", user['id'])
    return [dict(r) for r in rows]

@router.post("/channels/stop-tasks")
async def stop_tasks():
    from app.worker import clear_worker_queue
    removed = await clear_worker_queue()
    return {"status": "success", "message": f"Queue cleared. {removed} tasks removed."}

@router.delete("/channels/{channel_name}")
async def delete_channel(
    channel_name: str, 
    db: Connection = Depends(get_db),
    token: str = Depends(get_token)
):
    user = await get_current_user(token, db)
    await db.execute("DELETE FROM channels WHERE name=$1 AND owner_id=$2", channel_name, user['id'])
    return {"status": "deleted"}

@router.get("/channels/{channel_name}/export")
async def export_channel(
    channel_name: str, 
    format: str = Query("txt"),
    db: Connection = Depends(get_db),
    token: str = Depends(get_token)
):
    user = await get_current_user(token, db)
    rows = await db.fetch(
        """SELECT v.title, v.url, v.transcript 
           FROM videos v
           JOIN channels c ON v.channel_id = c.id
           WHERE c.name=$1 AND c.owner_id=$2 AND v.status='done'
           ORDER BY v.id ASC""",
        channel_name, user['id']
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No transcripts found for export.")

    content = _format_transcripts(rows, format)
    filename = f"{channel_name}_transcripts.{format}"
    
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(
        content, 
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@router.get("/export-all")
async def export_all(
    format: str = Query("txt"),
    db: Connection = Depends(get_db),
    token: str = Depends(get_token)
):
    user = await get_current_user(token, db)
    rows = await db.fetch(
        """SELECT v.title, v.url, v.transcript, c.name as channel_name 
           FROM videos v
           JOIN channels c ON v.channel_id = c.id
           WHERE c.owner_id=$1 AND v.status='done'
           ORDER BY c.name ASC, v.id ASC""",
        user['id']
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No transcripts found for export.")

    content = _format_transcripts(rows, format, grouped=True)
    filename = f"all_transcripts.{format}"
    
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(
        content, 
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

def _format_transcripts(rows, format, grouped=False):
    lines = []
    current_channel = None
    
    for row in rows:
        if grouped and row.get('channel_name') != current_channel:
            current_channel = row['channel_name']
            if format == "md":
                lines.append(f"# Channel: {current_channel}")
            else:
                lines.append(f"========== CHANNEL: {current_channel} ==========")
            lines.append("")

        if format == "md":
            lines.append(f"## {row['title']}")
            lines.append(f"**URL:** {row['url']}")
            lines.append("")
            lines.append(row['transcript'])
            lines.append("")
            lines.append("---")
            lines.append("")
        else:
            lines.append(f"=== {row['title']} ===")
            lines.append(f"URL: {row['url']}")
            lines.append("")
            lines.append(row['transcript'])
            lines.append("\n")
            
    return "\n".join(lines)

@router.post("/channels/{channel_name}/save-to-drive")
async def save_to_drive(
    channel_name: str,
    req: dict, # Expecting {"access_token": "...", "format": "txt"}
    db: Connection = Depends(get_db),
    token: str = Depends(get_token)
):
    user = await get_current_user(token, db)
    access_token = req.get("access_token")
    file_format = req.get("format", "txt")
    
    if not access_token:
        raise HTTPException(status_code=400, detail="Google Access Token is required for Drive upload.")

    rows = await db.fetch(
        """SELECT v.title, v.url, v.transcript 
           FROM videos v
           JOIN channels c ON v.channel_id = c.id
           WHERE c.name=$1 AND c.owner_id=$2 AND v.status='done'
           ORDER BY v.id ASC""",
        channel_name, user['id']
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No transcripts found for upload.")

    content = _format_transcripts(rows, file_format)
    filename = f"{channel_name}_transcripts.{file_format}"
    mime_type = "text/markdown" if file_format == "md" else "text/plain"

    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseUpload
        from google.oauth2.credentials import Credentials
        import io

        creds = Credentials(access_token)
        service = build('drive', 'v3', credentials=creds)

        file_metadata = {'name': filename}
        fh = io.BytesIO(content.encode('utf-8'))
        media = MediaIoBaseUpload(fh, mimetype=mime_type, resumable=True)
        
        file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        return {"status": "success", "file_id": file.get('id')}

    except Exception as e:
        print(f"[Drive] ❌ Upload failed: {e}")
        raise HTTPException(status_code=500, detail=f"Google Drive upload failed: {str(e)}")

@router.post("/export-all/save-to-drive")
async def save_all_to_drive(
    req: dict, 
    db: Connection = Depends(get_db),
    token: str = Depends(get_token)
):
    user = await get_current_user(token, db)
    access_token = req.get("access_token")
    file_format = req.get("format", "txt")
    
    if not access_token:
        raise HTTPException(status_code=400, detail="Google Access Token is required.")

    rows = await db.fetch(
        """SELECT v.title, v.url, v.transcript, c.name as channel_name 
           FROM videos v
           JOIN channels c ON v.channel_id = c.id
           WHERE c.owner_id=$1 AND v.status='done'
           ORDER BY c.name ASC, v.id ASC""",
        user['id']
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No transcripts found.")

    content = _format_transcripts(rows, file_format, grouped=True)
    filename = f"all_transcripts.{file_format}"
    mime_type = "text/markdown" if file_format == "md" else "text/plain"

    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseUpload
        from google.oauth2.credentials import Credentials
        import io

        creds = Credentials(access_token)
        service = build('drive', 'v3', credentials=creds)

        file_metadata = {'name': filename}
        fh = io.BytesIO(content.encode('utf-8'))
        media = MediaIoBaseUpload(fh, mimetype=mime_type, resumable=True)
        
        file = service.files().create(body=file_metadata, media_body=media, fields='id').execute()
        return {"status": "success", "file_id": file.get('id')}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/channels/{channel_name}/refresh-metadata")
async def refresh_metadata(
    channel_name: str, 
    db: Connection = Depends(get_db),
    token: str = Depends(get_token)
):
    user = await get_current_user(token, db)
    # Verify ownership
    row = await db.fetchrow("SELECT id FROM channels WHERE name=$1 AND owner_id=$2", channel_name, user['id'])
    if not row:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    await refresh_channel_metadata(row['id'])
    return {"status": "refreshing", "channel": channel_name}
