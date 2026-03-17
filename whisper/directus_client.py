"""Directus REST API client for the Whisper transcription service."""

import httpx
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class DirectusClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.request(method, url, headers=self.headers, **kwargs)
            resp.raise_for_status()
            return resp.json() if resp.content else {}

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.base_url}/server/health")
                return resp.status_code == 200
        except Exception:
            return False

    # ---- Schema bootstrap ----

    async def ensure_whisper_fields(self):
        """Add whisper_status field to videos collection if it doesn't exist."""
        try:
            result = await self._request("GET", "/fields/videos")
            existing = {f["field"] for f in result.get("data", [])}
            if "whisper_status" not in existing:
                await self._request("POST", "/fields/videos", json={
                    "field": "whisper_status",
                    "type": "string",
                    "meta": {
                        "interface": "select-dropdown",
                        "width": "half",
                        "options": {
                            "choices": [
                                {"text": "Processing", "value": "processing"},
                                {"text": "Done", "value": "done"},
                                {"text": "Error", "value": "error"},
                            ]
                        },
                    },
                    "schema": {"max_length": 50, "is_nullable": True},
                })
                logger.info("Added 'whisper_status' field to videos collection")
        except Exception as e:
            logger.warning(f"Could not ensure whisper fields: {e}")

    # ---- Video queries ----

    async def get_no_transcript_videos(self, limit: int = 50) -> list:
        """Fetch videos with status 'no_transcript' and no whisper processing yet."""
        params = (
            "?filter[status][_eq]=no_transcript"
            "&filter[whisper_status][_null]=true"
            "&sort=processed_at"
            f"&limit={limit}"
            "&fields=id,video_id,title,url,duration_seconds"
        )
        result = await self._request("GET", f"/items/videos{params}")
        return result.get("data", [])

    async def update_video(self, video_id: str, data: dict) -> dict:
        result = await self._request("PATCH", f"/items/videos/{video_id}", json=data)
        return result.get("data", {})

    async def find_video_by_yt_id(self, yt_video_id: str) -> Optional[dict]:
        params = f"?filter[video_id][_eq]={yt_video_id}&limit=1"
        result = await self._request("GET", f"/items/videos{params}")
        items = result.get("data", [])
        return items[0] if items else None
