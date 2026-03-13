from fastapi import APIRouter, Depends, HTTPException, Query
from asyncpg import Connection
from app.database import get_db
from app.schemas import VideoOut, TranscriptOut
from app.routers.auth import get_current_user, get_token

router = APIRouter(tags=["Videos"])

@router.get("/videos/{channel_name}", response_model=list[VideoOut])
async def list_videos(
    channel_name: str,
    status: str | None = Query(None),
    db: Connection = Depends(get_db),
    token: str = Depends(get_token)
):
    user = await get_current_user(token, db)
    
    # Check if user owns this channel
    channel = await db.fetchrow(
        "SELECT id FROM channels WHERE name=$1 AND owner_id=$2", 
        channel_name, user['id']
    )
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    if status:
        rows = await db.fetch(
            """SELECT video_id, title, url, duration, uploaded_at, status, processed_at
            FROM videos 
            WHERE channel_id=$1 AND status=$2 
            ORDER BY uploaded_at DESC NULLS LAST""",
            channel['id'], status)
    else:
        rows = await db.fetch(
            """SELECT video_id, title, url, duration, uploaded_at, status, processed_at 
            FROM videos 
            WHERE channel_id=$1 
            ORDER BY id DESC""",
            channel['id'])
    
    return [dict(r) for r in rows]

@router.get("/videos/transcript/{video_id}", response_model=TranscriptOut)
async def get_transcript(
    video_id: str, 
    db: Connection = Depends(get_db),
    token: str = Depends(get_token)
):
    user = await get_current_user(token, db)
    
    # Check if user owns the channel of this video
    row = await db.fetchrow(
        """SELECT v.video_id, v.title, v.url, v.duration, v.transcript, v.status, v.processed_at
           FROM videos v
           JOIN channels c ON v.channel_id = c.id
           WHERE v.video_id=$1 AND c.owner_id=$2""", 
        video_id, user['id']
    )
    if not row:
        raise HTTPException(404, "Video not found or access denied")
    return dict(row)
