"""Directus REST API client for managing channels and videos."""

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

    # ---- Collections bootstrap ----

    async def ensure_schema(self):
        """Create channels and videos collections if they don't exist."""
        existing = await self._get_existing_collections()
        if "channels" not in existing:
            await self._create_channels_collection()
            logger.info("Created 'channels' collection")
        if "videos" not in existing:
            await self._create_videos_collection()
            logger.info("Created 'videos' collection")
            await self._create_videos_channel_relation()
            logger.info("Created videos→channels relation")

    async def _get_existing_collections(self) -> set:
        try:
            data = await self._request("GET", "/collections")
            return {c["collection"] for c in data.get("data", [])}
        except Exception:
            return set()

    async def _create_channels_collection(self):
        payload = {
            "collection": "channels",
            "meta": {"icon": "video_library", "display_template": "{{name}}"},
            "schema": {},
            "fields": [
                {"field": "id", "type": "uuid", "meta": {"special": ["uuid"], "hidden": True, "readonly": True}, "schema": {"is_primary_key": True, "is_nullable": False}},
                {"field": "name", "type": "string", "meta": {"interface": "input", "width": "full"}, "schema": {"max_length": 255, "is_nullable": True}},
                {"field": "channel_url", "type": "string", "meta": {"interface": "input", "width": "full"}, "schema": {"max_length": 512, "is_nullable": True}},
                {"field": "channel_handle", "type": "string", "meta": {"interface": "input", "width": "half"}, "schema": {"max_length": 255, "is_nullable": True}},
                {"field": "added_at", "type": "timestamp", "meta": {"special": ["date-created"], "interface": "datetime", "readonly": True, "width": "half"}, "schema": {"is_nullable": True, "default_value": "now()"}},
                {"field": "status", "type": "string", "meta": {"interface": "select-dropdown", "width": "half", "options": {"choices": [{"text": "Pending", "value": "pending"}, {"text": "Processing", "value": "processing"}, {"text": "Done", "value": "done"}, {"text": "Error", "value": "error"}]}}, "schema": {"max_length": 50, "is_nullable": True, "default_value": "pending"}},
                {"field": "video_count", "type": "integer", "meta": {"interface": "input", "readonly": True, "width": "half"}, "schema": {"is_nullable": True, "default_value": 0}},
                {"field": "error_message", "type": "text", "meta": {"interface": "input-multiline", "readonly": True, "width": "full"}, "schema": {"is_nullable": True}},
                {"field": "last_refreshed", "type": "timestamp", "meta": {"interface": "datetime", "readonly": True, "width": "half"}, "schema": {"is_nullable": True}},
            ],
        }
        await self._request("POST", "/collections", json=payload)

    async def _create_videos_collection(self):
        payload = {
            "collection": "videos",
            "meta": {"icon": "ondemand_video", "display_template": "{{title}}"},
            "schema": {},
            "fields": [
                {"field": "id", "type": "uuid", "meta": {"special": ["uuid"], "hidden": True, "readonly": True}, "schema": {"is_primary_key": True, "is_nullable": False}},
                {"field": "video_id", "type": "string", "meta": {"interface": "input", "width": "half"}, "schema": {"max_length": 50, "is_nullable": True}},
                {"field": "channel_id", "type": "uuid", "meta": {"interface": "select-dropdown-m2o", "special": ["m2o"], "width": "half"}, "schema": {"is_nullable": True, "foreign_key_table": "channels", "foreign_key_column": "id"}},
                {"field": "title", "type": "string", "meta": {"interface": "input", "width": "full"}, "schema": {"max_length": 512, "is_nullable": True}},
                {"field": "url", "type": "string", "meta": {"interface": "input", "width": "full"}, "schema": {"max_length": 512, "is_nullable": True}},
                {"field": "duration_seconds", "type": "integer", "meta": {"interface": "input", "width": "half"}, "schema": {"is_nullable": True}},
                {"field": "uploaded_at", "type": "timestamp", "meta": {"interface": "datetime", "width": "half"}, "schema": {"is_nullable": True}},
                {"field": "transcript", "type": "text", "meta": {"interface": "input-multiline", "width": "full"}, "schema": {"is_nullable": True}},
                {"field": "status", "type": "string", "meta": {"interface": "select-dropdown", "width": "half", "options": {"choices": [{"text": "Pending", "value": "pending"}, {"text": "Done", "value": "done"}, {"text": "No Transcript", "value": "no_transcript"}, {"text": "Error", "value": "error"}]}}, "schema": {"max_length": 50, "is_nullable": True, "default_value": "pending"}},
                {"field": "processed_at", "type": "timestamp", "meta": {"interface": "datetime", "readonly": True, "width": "half"}, "schema": {"is_nullable": True}},
            ],
        }
        await self._request("POST", "/collections", json=payload)

    async def _create_videos_channel_relation(self):
        payload = {
            "collection": "videos",
            "field": "channel_id",
            "related_collection": "channels",
            "schema": {"on_delete": "CASCADE"},
            "meta": {
                "many_collection": "videos",
                "many_field": "channel_id",
                "one_collection": "channels",
                "one_deselect_action": "nullify",
            },
        }
        try:
            await self._request("POST", "/relations", json=payload)
        except Exception as e:
            logger.warning(f"Relation may already exist: {e}")

    # ---- Channel CRUD ----

    async def create_channel(self, data: dict) -> dict:
        result = await self._request("POST", "/items/channels", json=data)
        return result.get("data", {})

    async def get_channel(self, channel_id: str) -> Optional[dict]:
        try:
            result = await self._request("GET", f"/items/channels/{channel_id}")
            return result.get("data")
        except Exception:
            return None

    async def get_all_channels(self) -> list:
        result = await self._request("GET", "/items/channels?limit=-1")
        return result.get("data", [])

    async def update_channel(self, channel_id: str, data: dict) -> dict:
        result = await self._request("PATCH", f"/items/channels/{channel_id}", json=data)
        return result.get("data", {})

    async def find_channel_by_handle(self, handle: str) -> Optional[dict]:
        params = f'?filter[channel_handle][_eq]={handle}&limit=1'
        result = await self._request("GET", f"/items/channels{params}")
        items = result.get("data", [])
        return items[0] if items else None

    # ---- Video CRUD ----

    async def create_video(self, data: dict) -> dict:
        result = await self._request("POST", "/items/videos", json=data)
        return result.get("data", {})

    async def update_video(self, video_id: str, data: dict) -> dict:
        result = await self._request("PATCH", f"/items/videos/{video_id}", json=data)
        return result.get("data", {})

    async def get_videos_by_channel(self, channel_id: str) -> list:
        params = f'?filter[channel_id][_eq]={channel_id}&limit=-1&fields=video_id'
        result = await self._request("GET", f"/items/videos{params}")
        return result.get("data", [])

    async def get_videos_missing_date(self) -> list:
        params = '?filter[uploaded_at][_null]=true&limit=-1&fields=id,video_id'
        result = await self._request("GET", f"/items/videos{params}")
        return result.get("data", [])

    async def find_video_by_yt_id(self, yt_video_id: str) -> Optional[dict]:
        params = f'?filter[video_id][_eq]={yt_video_id}&limit=1'
        result = await self._request("GET", f"/items/videos{params}")
        items = result.get("data", [])
        return items[0] if items else None
