from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class UserOut(BaseModel):
    id: int
    email: str
    name: Optional[str]
    picture: Optional[str]

class ChannelCreate(BaseModel):
    channel_name: str

class ChannelOut(BaseModel):
    id: int
    name: str
    added_at: datetime

class VideoOut(BaseModel):
    video_id: str
    title: Optional[str]
    url: Optional[str]
    duration: Optional[int] = None
    uploaded_at: Optional[datetime] = None
    status: str
    processed_at: Optional[datetime]

class TranscriptOut(VideoOut):
    transcript: Optional[str]
