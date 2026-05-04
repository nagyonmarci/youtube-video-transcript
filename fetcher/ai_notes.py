"""AI note generation for YouTube transcripts via Ollama."""

import json
import logging
import os
import re
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434").rstrip("/")
OLLAMA_CHAT_MODEL = os.environ.get("OLLAMA_CHAT_MODEL", "gemma4:31b")
AI_NOTES_MAX_CHARS = int(os.environ.get("AI_NOTES_MAX_CHARS", "45000"))


def compact_transcript(video: dict) -> str:
    transcript = video.get("transcript_timed") or video.get("transcript") or ""
    transcript = re.sub(r"\n{3,}", "\n\n", transcript.strip())
    if len(transcript) <= AI_NOTES_MAX_CHARS:
        return transcript
    head = transcript[: AI_NOTES_MAX_CHARS // 2]
    tail = transcript[-AI_NOTES_MAX_CHARS // 2 :]
    return f"{head}\n\n[... transzkript kozepe kihagyva a rovidites miatt ...]\n\n{tail}"


def normalize_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [line.strip("- •\t ") for line in value.splitlines() if line.strip("- •\t ")]
    return []


def extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def build_prompt(video: dict) -> str:
    title = video.get("title") or "Ismeretlen cim"
    url = video.get("url") or ""
    uploaded = video.get("uploaded_at") or ""
    duration = video.get("duration_seconds") or ""
    transcript = compact_transcript(video)

    return f"""
Te egy magyar nyelvu, forrasalapu YouTube tudasgyujto asszisztens vagy.
Keszits strukturalt jegyzetet az alabbi video transzkriptjebol.

Szabalyok:
- Csak a transzkriptben es metaadatokban szereplo informaciokra tamaszkodj.
- Ne talalj ki tenyallitasokat.
- Magyarul valaszolj.
- A valasz KIZAROLAG ervenyes JSON legyen, markdown kodblokk nelkul.
- A "topics", "takeaways" es "questions" mezok tombok legyenek.
- Az "obsidian_note" legyen Obsidian-kompatibilis markdown, belso szekciokkal.
- Ha a transzkript idobelyegeket tartalmaz, a fontos allitasoknal tartsd meg oket zarojelben, pl. (12:34).

JSON schema:
{{
  "summary": "5-8 mondatos tomor osszefoglalo",
  "topics": ["tema 1", "tema 2"],
  "takeaways": ["legfontosabb tanulsag 1", "legfontosabb tanulsag 2"],
  "questions": ["jo visszakerdezo vagy tanulasi kerdes 1", "kerdes 2"],
  "obsidian_note": "## Osszefoglalo\\n...\\n\\n## Temak\\n- ...\\n\\n## Tanulsagok\\n- ...\\n\\n## Kerdesek\\n- ..."
}}

Video:
Cim: {title}
URL: {url}
Feltoltve: {uploaded}
Hossz masodpercben: {duration}

Transzkript:
{transcript}
""".strip()


async def generate_ai_notes(video: dict) -> Optional[dict]:
    transcript = video.get("transcript") or video.get("transcript_timed")
    if not transcript:
        return None

    messages = [
        {
            "role": "system",
            "content": "Forrasalapu magyar jegyzetelo asszisztens vagy. Mindig ervenyes JSON-t adsz vissza.",
        },
        {"role": "user", "content": build_prompt(video)},
    ]
    payload = {
        "model": OLLAMA_CHAT_MODEL,
        "messages": messages,
        "stream": False,
        "format": "json",
    }

    async with httpx.AsyncClient(timeout=None) as client:
        response = await client.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload)
        response.raise_for_status()
        data = response.json()

    content = data.get("message", {}).get("content", "")
    parsed = extract_json(content)
    return {
        "summary": str(parsed.get("summary", "")).strip(),
        "topics": normalize_list(parsed.get("topics")),
        "takeaways": normalize_list(parsed.get("takeaways")),
        "questions": normalize_list(parsed.get("questions")),
        "obsidian_note": str(parsed.get("obsidian_note", "")).strip(),
    }
