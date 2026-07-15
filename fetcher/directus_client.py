"""Directus REST API client for managing channels and videos."""

import httpx
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _active_status_filter(idx: int) -> str:
    """Filter clause matching queued/running/paused (i.e. not done/error/cancelled) at the given _and index."""
    return (
        f"&filter[_and][{idx}][_or][0][status][_eq]=queued"
        f"&filter[_and][{idx}][_or][1][status][_eq]=running"
        f"&filter[_and][{idx}][_or][2][status][_eq]=paused"
    )

AI_NOTE_FIELDS = [
    {"field": "summary", "type": "text", "meta": {"interface": "input-multiline", "width": "full"}, "schema": {"is_nullable": True}},
    {"field": "topics", "type": "json", "meta": {"interface": "list", "width": "full"}, "schema": {"is_nullable": True}},
    {"field": "takeaways", "type": "json", "meta": {"interface": "list", "width": "full"}, "schema": {"is_nullable": True}},
    {"field": "questions", "type": "json", "meta": {"interface": "list", "width": "full"}, "schema": {"is_nullable": True}},
    {"field": "obsidian_note", "type": "text", "meta": {"interface": "input-multiline", "width": "full"}, "schema": {"is_nullable": True}},
    {"field": "study_guide", "type": "text", "meta": {"interface": "input-multiline", "width": "full"}, "schema": {"is_nullable": True}},
    {"field": "critique", "type": "text", "meta": {"interface": "input-multiline", "width": "full"}, "schema": {"is_nullable": True}},
    {"field": "quick_summary", "type": "text", "meta": {"interface": "input-multiline", "width": "full"}, "schema": {"is_nullable": True}},
    {"field": "quick_summary_model", "type": "string", "meta": {"interface": "input", "width": "half"}, "schema": {"max_length": 255, "is_nullable": True}},
    {"field": "quick_summary_generated_at", "type": "timestamp", "meta": {"interface": "datetime", "readonly": True, "width": "half"}, "schema": {"is_nullable": True}},
    {"field": "thumbnail_url", "type": "string", "meta": {"interface": "input", "width": "full"}, "schema": {"max_length": 1024, "is_nullable": True}},
    {"field": "is_members_only", "type": "boolean", "meta": {"interface": "boolean", "width": "half"}, "schema": {"is_nullable": True, "default_value": False}},
    {"field": "ai_notes_status", "type": "string", "meta": {"interface": "select-dropdown", "width": "half", "options": {"choices": [{"text": "Pending", "value": "pending"}, {"text": "Done", "value": "done"}, {"text": "Error", "value": "error"}]}}, "schema": {"max_length": 50, "is_nullable": True}},
    {"field": "ai_notes_generated_at", "type": "timestamp", "meta": {"interface": "datetime", "readonly": True, "width": "half"}, "schema": {"is_nullable": True}},
    {"field": "ai_notes_error", "type": "text", "meta": {"interface": "input-multiline", "readonly": True, "width": "full"}, "schema": {"is_nullable": True}},
]

CHANNEL_EXTRA_FIELDS = [
    {"field": "topic", "type": "string", "meta": {"interface": "input", "width": "half"}, "schema": {"max_length": 255, "is_nullable": True}},
]

JOB_PROGRESS_FIELDS = [
    {"field": "dedupe_key", "type": "string", "meta": {"interface": "input", "width": "full", "readonly": True}, "schema": {"max_length": 512, "is_nullable": True}},
    {"field": "attempts", "type": "integer", "meta": {"interface": "input", "readonly": True, "width": "half"}, "schema": {"is_nullable": True, "default_value": 0}},
    {"field": "max_attempts", "type": "integer", "meta": {"interface": "input", "width": "half"}, "schema": {"is_nullable": True, "default_value": 3}},
    {"field": "progress_current", "type": "integer", "meta": {"interface": "input", "readonly": True, "width": "half"}, "schema": {"is_nullable": True}},
    {"field": "progress_total", "type": "integer", "meta": {"interface": "input", "readonly": True, "width": "half"}, "schema": {"is_nullable": True}},
    {"field": "progress_label", "type": "string", "meta": {"interface": "input", "readonly": True, "width": "full"}, "schema": {"max_length": 512, "is_nullable": True}},
    {"field": "locked_at", "type": "timestamp", "meta": {"interface": "datetime", "readonly": True, "width": "half"}, "schema": {"is_nullable": True}},
    {"field": "locked_by", "type": "string", "meta": {"interface": "input", "readonly": True, "width": "half"}, "schema": {"max_length": 255, "is_nullable": True}},
    {"field": "last_error", "type": "text", "meta": {"interface": "input-multiline", "readonly": True, "width": "full"}, "schema": {"is_nullable": True}},
    {"field": "duration_seconds", "type": "integer", "meta": {"interface": "input", "readonly": True, "width": "half"}, "schema": {"is_nullable": True}},
    {"field": "metrics", "type": "json", "meta": {"interface": "input-code", "readonly": True, "width": "full"}, "schema": {"is_nullable": True}},
]

JOB_LIST_FIELDS = (
    "id,queue,type,label,status,sort_order,payload,dedupe_key,attempts,max_attempts,"
    "progress_current,progress_total,progress_label,locked_at,locked_by,created_at,started_at,finished_at,"
    "error_message,last_error,duration_seconds,metrics"
)

class DirectusClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30, headers=self.headers)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f"{self.base_url}{path}"
        client = self._get_client()
        resp = await client.request(method, url, **kwargs)
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
        else:
            await self._ensure_channels_fields()
        if "videos" not in existing:
            await self._create_videos_collection()
            logger.info("Created 'videos' collection")
            await self._create_videos_channel_relation()
            logger.info("Created videos→channels relation")
        else:
            await self._ensure_videos_fields()
        if "app_settings" not in existing:
            await self._create_app_settings_collection()
            logger.info("Created 'app_settings' collection")
        if "jobs" not in existing:
            await self._create_jobs_collection()
            logger.info("Created 'jobs' collection")
        else:
            await self._ensure_jobs_fields()

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
                *CHANNEL_EXTRA_FIELDS,
                {"field": "channel_url", "type": "string", "meta": {"interface": "input", "width": "full"}, "schema": {"max_length": 512, "is_nullable": True}},
                {"field": "channel_handle", "type": "string", "meta": {"interface": "input", "width": "half"}, "schema": {"max_length": 255, "is_nullable": True}},
                {"field": "added_at", "type": "timestamp", "meta": {"special": ["date-created"], "interface": "datetime", "readonly": True, "width": "half"}, "schema": {"is_nullable": True, "default_value": "now()"}},
                {"field": "status", "type": "string", "meta": {"interface": "select-dropdown", "width": "half", "options": {"choices": [{"text": "Pending", "value": "pending"}, {"text": "Processing", "value": "processing"}, {"text": "Backlog", "value": "backlog"}, {"text": "Done", "value": "done"}, {"text": "Error", "value": "error"}]}}, "schema": {"max_length": 50, "is_nullable": True, "default_value": "pending"}},
                {"field": "video_count", "type": "integer", "meta": {"interface": "input", "readonly": True, "width": "half"}, "schema": {"is_nullable": True, "default_value": 0}},
                {"field": "error_message", "type": "text", "meta": {"interface": "input-multiline", "readonly": True, "width": "full"}, "schema": {"is_nullable": True}},
                {"field": "last_refreshed", "type": "timestamp", "meta": {"interface": "datetime", "readonly": True, "width": "half"}, "schema": {"is_nullable": True}},
            ],
        }
        await self._request("POST", "/collections", json=payload)

    async def _ensure_channels_fields(self):
        try:
            result = await self._request("GET", "/fields/channels")
            existing = {f["field"] for f in result.get("data", [])}
            for field in CHANNEL_EXTRA_FIELDS:
                if field["field"] not in existing:
                    await self._request("POST", "/fields/channels", json=field)
                    logger.info(f"Added '{field['field']}' field to channels collection")
        except Exception as e:
            logger.warning(f"Could not ensure channels fields: {e}")

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
                {"field": "thumbnail_url", "type": "string", "meta": {"interface": "input", "width": "full"}, "schema": {"max_length": 1024, "is_nullable": True}},
                {"field": "is_members_only", "type": "boolean", "meta": {"interface": "boolean", "width": "half"}, "schema": {"is_nullable": True, "default_value": False}},
                {"field": "duration_seconds", "type": "integer", "meta": {"interface": "input", "width": "half"}, "schema": {"is_nullable": True}},
                {"field": "uploaded_at", "type": "timestamp", "meta": {"interface": "datetime", "width": "half"}, "schema": {"is_nullable": True}},
                {"field": "transcript", "type": "text", "meta": {"interface": "input-multiline", "width": "full"}, "schema": {"is_nullable": True}},
                {"field": "transcript_timed", "type": "text", "meta": {"interface": "input-multiline", "width": "full"}, "schema": {"is_nullable": True}},
                {"field": "summary", "type": "text", "meta": {"interface": "input-multiline", "width": "full"}, "schema": {"is_nullable": True}},
                {"field": "topics", "type": "json", "meta": {"interface": "list", "width": "full"}, "schema": {"is_nullable": True}},
                {"field": "takeaways", "type": "json", "meta": {"interface": "list", "width": "full"}, "schema": {"is_nullable": True}},
                {"field": "questions", "type": "json", "meta": {"interface": "list", "width": "full"}, "schema": {"is_nullable": True}},
                {"field": "obsidian_note", "type": "text", "meta": {"interface": "input-multiline", "width": "full"}, "schema": {"is_nullable": True}},
                {"field": "study_guide", "type": "text", "meta": {"interface": "input-multiline", "width": "full"}, "schema": {"is_nullable": True}},
                {"field": "critique", "type": "text", "meta": {"interface": "input-multiline", "width": "full"}, "schema": {"is_nullable": True}},
                {"field": "ai_notes_status", "type": "string", "meta": {"interface": "select-dropdown", "width": "half", "options": {"choices": [{"text": "Pending", "value": "pending"}, {"text": "Done", "value": "done"}, {"text": "Error", "value": "error"}]}}, "schema": {"max_length": 50, "is_nullable": True}},
                {"field": "ai_notes_generated_at", "type": "timestamp", "meta": {"interface": "datetime", "readonly": True, "width": "half"}, "schema": {"is_nullable": True}},
                {"field": "ai_notes_error", "type": "text", "meta": {"interface": "input-multiline", "readonly": True, "width": "full"}, "schema": {"is_nullable": True}},
                {"field": "status", "type": "string", "meta": {"interface": "select-dropdown", "width": "half", "options": {"choices": [{"text": "Pending", "value": "pending"}, {"text": "Done", "value": "done"}, {"text": "No Transcript", "value": "no_transcript"}, {"text": "Error", "value": "error"}]}}, "schema": {"max_length": 50, "is_nullable": True, "default_value": "pending"}},
                {"field": "processed_at", "type": "timestamp", "meta": {"interface": "datetime", "readonly": True, "width": "half"}, "schema": {"is_nullable": True}},
            ],
        }
        await self._request("POST", "/collections", json=payload)

    async def _ensure_videos_fields(self):
        async def create_field_if_missing(field: dict) -> None:
            try:
                await self._request("POST", "/fields/videos", json=field)
                logger.info(f"Added '{field['field']}' field to videos collection")
            except httpx.HTTPStatusError as e:
                message = e.response.text.lower()
                if e.response.status_code == 500 and "already exists" in message:
                    logger.info(f"Field '{field['field']}' already exists in videos collection")
                    return
                raise

        try:
            result = await self._request("GET", "/fields/videos")
            existing = {f["field"] for f in result.get("data", [])}
            if "transcript_timed" not in existing:
                await create_field_if_missing({
                    "field": "transcript_timed",
                    "type": "text",
                    "meta": {"interface": "input-multiline", "width": "full"},
                    "schema": {"is_nullable": True},
                })
            for field in AI_NOTE_FIELDS:
                if field["field"] not in existing:
                    await create_field_if_missing(field)
        except Exception as e:
            logger.warning(f"Could not ensure videos fields: {e}")

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

    async def _create_app_settings_collection(self):
        payload = {
            "collection": "app_settings",
            "meta": {"icon": "settings", "display_template": "{{key}}"},
            "schema": {},
            "fields": [
                {"field": "id", "type": "uuid", "meta": {"special": ["uuid"], "hidden": True, "readonly": True}, "schema": {"is_primary_key": True, "is_nullable": False}},
                {"field": "key", "type": "string", "meta": {"interface": "input", "width": "half"}, "schema": {"max_length": 100, "is_nullable": False, "is_unique": True}},
                {"field": "value", "type": "text", "meta": {"interface": "input-multiline", "width": "full"}, "schema": {"is_nullable": True}},
            ],
        }
        await self._request("POST", "/collections", json=payload)

    async def _create_jobs_collection(self):
        payload = {
            "collection": "jobs",
            "meta": {"icon": "pending_actions", "display_template": "{{label}}"},
            "schema": {},
            "fields": [
                {"field": "id", "type": "uuid", "meta": {"special": ["uuid"], "hidden": True, "readonly": True}, "schema": {"is_primary_key": True, "is_nullable": False}},
                {"field": "queue", "type": "string", "meta": {"interface": "select-dropdown", "width": "half", "options": {"choices": [{"text": "Fetch", "value": "fetch"}, {"text": "AI", "value": "ai"}, {"text": "Whisper", "value": "whisper"}]}}, "schema": {"max_length": 50, "is_nullable": False}},
                {"field": "type", "type": "string", "meta": {"interface": "input", "width": "half"}, "schema": {"max_length": 100, "is_nullable": False}},
                {"field": "label", "type": "string", "meta": {"interface": "input", "width": "full"}, "schema": {"max_length": 512, "is_nullable": True}},
                {"field": "status", "type": "string", "meta": {"interface": "select-dropdown", "width": "half", "options": {"choices": [{"text": "Queued", "value": "queued"}, {"text": "Running", "value": "running"}, {"text": "Paused", "value": "paused"}, {"text": "Done", "value": "done"}, {"text": "Error", "value": "error"}, {"text": "Cancelled", "value": "cancelled"}]}}, "schema": {"max_length": 50, "is_nullable": False, "default_value": "queued"}},
                {"field": "sort_order", "type": "integer", "meta": {"interface": "input", "width": "half"}, "schema": {"is_nullable": True, "default_value": 0}},
                {"field": "payload", "type": "json", "meta": {"interface": "input-code", "width": "full"}, "schema": {"is_nullable": True}},
                {"field": "created_at", "type": "timestamp", "meta": {"special": ["date-created"], "interface": "datetime", "readonly": True, "width": "half"}, "schema": {"is_nullable": True, "default_value": "now()"}},
                {"field": "started_at", "type": "timestamp", "meta": {"interface": "datetime", "readonly": True, "width": "half"}, "schema": {"is_nullable": True}},
                {"field": "finished_at", "type": "timestamp", "meta": {"interface": "datetime", "readonly": True, "width": "half"}, "schema": {"is_nullable": True}},
                {"field": "error_message", "type": "text", "meta": {"interface": "input-multiline", "readonly": True, "width": "full"}, "schema": {"is_nullable": True}},
                *JOB_PROGRESS_FIELDS,
            ],
        }
        await self._request("POST", "/collections", json=payload)

    async def _ensure_jobs_fields(self):
        try:
            result = await self._request("GET", "/fields/jobs")
            existing = {f["field"] for f in result.get("data", [])}
            for field in JOB_PROGRESS_FIELDS:
                if field["field"] not in existing:
                    await self._request("POST", "/fields/jobs", json=field)
                    logger.info(f"Added '{field['field']}' field to jobs collection")
        except Exception as e:
            logger.warning(f"Could not ensure jobs fields: {e}")

    # ---- App settings ----

    async def get_setting(self, key: str) -> Optional[str]:
        params = f"?filter[key][_eq]={key}&limit=1&fields=id,key,value"
        result = await self._request("GET", f"/items/app_settings{params}")
        items = result.get("data", [])
        return items[0].get("value") if items else None

    async def set_setting(self, key: str, value: str) -> dict:
        params = f"?filter[key][_eq]={key}&limit=1&fields=id"
        result = await self._request("GET", f"/items/app_settings{params}")
        items = result.get("data", [])
        if items:
            updated = await self._request("PATCH", f"/items/app_settings/{items[0]['id']}", json={"value": value})
            return updated.get("data", {})
        created = await self._request("POST", "/items/app_settings", json={"key": key, "value": value})
        return created.get("data", {})

    # ---- Jobs ----

    async def create_job(
        self,
        queue: str,
        task: dict,
        label: Optional[str] = None,
        sort_order: Optional[int] = None,
        dedupe_key: Optional[str] = None,
        max_attempts: int = 3,
    ) -> dict:
        if dedupe_key:
            existing = await self.get_active_job_by_dedupe_key(queue, dedupe_key)
            if existing:
                return {**existing, "existing": True}
        if sort_order is None:
            sort_order = await self.next_job_sort_order(queue)
        payload = {
            "queue": queue,
            "type": task.get("type"),
            "label": label or await self.job_label(task),
            "status": "queued",
            "sort_order": sort_order,
            "payload": task,
            "dedupe_key": dedupe_key,
            "attempts": 0,
            "max_attempts": max_attempts,
        }
        try:
            result = await self._request("POST", "/items/jobs", json=payload)
        except httpx.HTTPStatusError:
            if dedupe_key:
                existing = await self.get_active_job_by_dedupe_key(queue, dedupe_key)
                if existing:
                    return {**existing, "existing": True}
            raise
        return result.get("data", {})

    async def job_label(self, task: dict) -> str:
        task_type = task.get("type") or "job"
        if task_type == "channel":
            channel = await self.get_channel(task.get("channel_id")) if task.get("channel_id") else None
            name = (channel or {}).get("name") or (channel or {}).get("channel_handle") or task.get("channel_url") or task.get("channel_id") or ""
            return f"Csatorna letöltés: {name}".strip()
        if task_type == "refresh":
            channel = await self.get_channel(task.get("channel_id")) if task.get("channel_id") else None
            name = (channel or {}).get("name") or (channel or {}).get("channel_handle") or task.get("channel_id") or ""
            return f"Csatorna frissítés: {name}".strip()
        if task_type == "video":
            return f"Videó letöltés: {task.get('video_url') or ''}".strip()
        if task_type == "refresh_dates":
            return "Hiányzó dátumok frissítése"
        if task_type == "refresh_thumbnails":
            return "Hiányzó thumbnail képek frissítése"
        if task_type == "ai_notes":
            return f"Hiányzó AI jegyzetek: {task.get('limit') or ''}".strip()
        if task_type == "ai_note_video":
            video = await self.get_video(task.get("video_id")) if task.get("video_id") else None
            title = (video or {}).get("title") or (video or {}).get("video_id") or task.get("video_id") or ""
            return f"AI jegyzet: {title}".strip()
        return task_type

    async def next_job_sort_order(self, queue: str) -> int:
        params = (
            f"?filter[_and][0][queue][_eq]={quote(queue)}"
            "&filter[_and][1][_or][0][status][_eq]=queued"
            "&filter[_and][1][_or][1][status][_eq]=paused"
            "&sort=-sort_order"
            "&limit=1"
            "&fields=sort_order"
        )
        result = await self._request("GET", f"/items/jobs{params}")
        items = result.get("data", [])
        if not items:
            return 1000
        return int(items[0].get("sort_order") or 0) + 1000

    async def get_next_job(self, queue: str) -> Optional[dict]:
        params = (
            f"?filter[queue][_eq]={quote(queue)}"
            "&filter[status][_eq]=queued"
            "&sort=sort_order,created_at"
            "&limit=1"
            f"&fields={JOB_LIST_FIELDS}"
        )
        result = await self._request("GET", f"/items/jobs{params}")
        items = result.get("data", [])
        return items[0] if items else None

    async def list_jobs(self, statuses: Optional[list] = None, limit: int = 200) -> list:
        status_filter = ""
        if statuses:
            parts = "".join(
                f"&filter[_or][{i}][status][_eq]={s}" for i, s in enumerate(statuses)
            )
            status_filter = parts
        params = (
            f"?limit={limit}"
            "&sort=queue,sort_order,created_at"
            f"&fields={JOB_LIST_FIELDS}"
            f"{status_filter}"
        )
        result = await self._request("GET", f"/items/jobs{params}")
        return result.get("data", [])

    async def count_jobs(self, queue: str, statuses: str = "queued") -> int:
        status_parts = [
            f"&filter[_and][1][_or][{idx}][status][_eq]={status.strip()}"
            for idx, status in enumerate(statuses.split(","))
            if status.strip()
        ]
        params = f"?filter[_and][0][queue][_eq]={quote(queue)}{''.join(status_parts)}&limit=1&meta=filter_count&fields=id"
        result = await self._request("GET", f"/items/jobs{params}")
        return result.get("meta", {}).get("filter_count", 0)

    async def get_running_job(self, queue: str) -> Optional[dict]:
        params = (
            f"?filter[queue][_eq]={quote(queue)}"
            "&filter[status][_eq]=running"
            "&sort=started_at"
            "&limit=1"
            f"&fields={JOB_LIST_FIELDS}"
        )
        result = await self._request("GET", f"/items/jobs{params}")
        items = result.get("data", [])
        return items[0] if items else None

    async def get_ai_note_job_video_ids(self) -> set[str]:
        params = (
            "?filter[_and][0][queue][_eq]=ai"
            "&filter[_and][1][type][_eq]=ai_note_video"
            f"{_active_status_filter(2)}"
            "&limit=-1"
            "&fields=payload"
        )
        result = await self._request("GET", f"/items/jobs{params}")
        ids = set()
        for item in result.get("data", []):
            video_id = (item.get("payload") or {}).get("video_id")
            if video_id:
                ids.add(video_id)
        return ids

    async def get_active_job_by_type(self, queue: str, job_type: str) -> Optional[dict]:
        params = (
            f"?filter[_and][0][queue][_eq]={quote(queue)}"
            f"&filter[_and][1][type][_eq]={quote(job_type)}"
            f"{_active_status_filter(2)}"
            "&sort=created_at"
            "&limit=1"
            f"&fields={JOB_LIST_FIELDS}"
        )
        result = await self._request("GET", f"/items/jobs{params}")
        items = result.get("data", [])
        return items[0] if items else None

    async def get_active_job_by_dedupe_key(self, queue: str, dedupe_key: str) -> Optional[dict]:
        params = (
            f"?filter[_and][0][queue][_eq]={quote(queue)}"
            f"&filter[_and][1][dedupe_key][_eq]={quote(dedupe_key, safe='')}"
            f"{_active_status_filter(2)}"
            "&sort=created_at"
            "&limit=1"
            f"&fields={JOB_LIST_FIELDS}"
        )
        result = await self._request("GET", f"/items/jobs{params}")
        items = result.get("data", [])
        return items[0] if items else None

    async def get_job(self, job_id: str) -> Optional[dict]:
        try:
            result = await self._request("GET", f"/items/jobs/{job_id}?fields={JOB_LIST_FIELDS}")
            return result.get("data")
        except Exception:
            return None

    async def update_job(self, job_id: str, data: dict) -> dict:
        result = await self._request("PATCH", f"/items/jobs/{job_id}", json=data)
        return result.get("data", {})

    async def delete_job(self, job_id: str) -> None:
        await self._request("DELETE", f"/items/jobs/{job_id}")

    async def delete_old_jobs(self, older_than_days: int = 7) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat()
        result = await self._request(
            "GET",
            f"/items/jobs?filter[status][_in]=done,cancelled&filter[created_at][_lt]={cutoff}&fields=id&limit=-1",
        )
        items = result.get("data", [])
        for item in items:
            try:
                await self.delete_job(item["id"])
            except Exception:
                pass
        return len(items)

    async def mark_stale_running_jobs_cancelled(self) -> int:
        result = await self._request("GET", "/items/jobs?filter[status][_eq]=running&limit=-1&fields=id")
        items = result.get("data", [])
        for item in items:
            await self.update_job(item["id"], {
                "status": "cancelled",
                "finished_at": None,
                "error_message": "Fetcher restarted while this job was running",
            })
        return len(items)

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

    async def get_channels_by_status(self, status: str) -> list:
        params = f'?filter[status][_eq]={status}&limit=-1'
        result = await self._request("GET", f"/items/channels{params}")
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

    async def get_video(self, video_id: str) -> Optional[dict]:
        fields = ",".join([
            "id",
            "video_id",
            "title",
            "url",
            "thumbnail_url",
            "is_members_only",
            "uploaded_at",
            "duration_seconds",
            "transcript",
            "transcript_timed",
        ])
        try:
            result = await self._request("GET", f"/items/videos/{video_id}?fields={fields}")
            return result.get("data")
        except Exception:
            return None

    async def get_videos_by_channel(self, channel_id: str) -> list:
        params = f'?filter[channel_id][_eq]={channel_id}&limit=-1&fields=id,video_id,title,uploaded_at,thumbnail_url,is_members_only,status'
        result = await self._request("GET", f"/items/videos{params}")
        return result.get("data", [])

    async def get_videos_missing_date(self) -> list:
        params = '?filter[uploaded_at][_null]=true&limit=-1&fields=id,video_id'
        result = await self._request("GET", f"/items/videos{params}")
        return result.get("data", [])

    async def get_videos_missing_thumbnail(self) -> list:
        params = '?filter[thumbnail_url][_null]=true&limit=-1&fields=id,video_id'
        result = await self._request("GET", f"/items/videos{params}")
        return result.get("data", [])

    def _missing_ai_notes_filter_params(self, year: Optional[int] = None) -> str:
        params = (
            "?filter[_and][0][transcript][_nnull]=true"
            "&filter[_and][1][_or][0][summary][_null]=true"
            "&filter[_and][1][_or][1][critique][_null]=true"
            "&filter[_and][1][_or][2][ai_notes_status][_eq]=error"
        )
        if year:
            start = quote(f"{year}-01-01T00:00:00+00:00")
            end = quote(f"{year + 1}-01-01T00:00:00+00:00")
            params += (
                f"&filter[_and][2][uploaded_at][_gte]={start}"
                f"&filter[_and][3][uploaded_at][_lt]={end}"
            )
        return params

    async def get_videos_missing_ai_notes(self, limit: int = 10, year: Optional[int] = None) -> list:
        params = (
            self._missing_ai_notes_filter_params(year)
            + f"&limit={limit}"
            + "&sort=-uploaded_at"
            + "&fields=id,video_id,title,url,uploaded_at,duration_seconds,transcript,transcript_timed"
        )
        result = await self._request("GET", f"/items/videos{params}")
        return result.get("data", [])

    async def count_videos_missing_ai_notes(self, year: Optional[int] = None) -> int:
        params = f"{self._missing_ai_notes_filter_params(year)}&limit=1&meta=filter_count&fields=id"
        result = await self._request("GET", f"/items/videos{params}")
        return int(result.get("meta", {}).get("filter_count") or 0)

    async def get_channel_videos_missing_ai_notes(self, channel_id: str, limit: int = 500) -> list:
        params = (
            f"?filter[_and][0][channel_id][_eq]={channel_id}"
            "&filter[_and][1][transcript][_nnull]=true"
            "&filter[_and][2][_or][0][summary][_null]=true"
            "&filter[_and][2][_or][1][critique][_null]=true"
            "&filter[_and][2][_or][2][ai_notes_status][_eq]=error"
            f"&limit={limit}"
            "&sort=-uploaded_at"
            "&fields=id,video_id,title,url,uploaded_at,duration_seconds,transcript,transcript_timed"
        )
        result = await self._request("GET", f"/items/videos{params}")
        return result.get("data", [])

    async def get_videos_with_ai_status(self, status: str) -> list:
        params = f"?filter[ai_notes_status][_eq]={status}&limit=-1&fields=id,video_id,title,ai_notes_status"
        result = await self._request("GET", f"/items/videos{params}")
        return result.get("data", [])

    async def find_video_by_yt_id(self, yt_video_id: str) -> Optional[dict]:
        params = f'?filter[video_id][_eq]={yt_video_id}&limit=1'
        result = await self._request("GET", f"/items/videos{params}")
        items = result.get("data", [])
        return items[0] if items else None
