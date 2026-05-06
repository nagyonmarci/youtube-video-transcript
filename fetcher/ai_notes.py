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
    title = video.get("title") or "Unknown title"
    url = video.get("url") or ""
    uploaded = video.get("uploaded_at") or ""
    duration = video.get("duration_seconds") or ""
    transcript = compact_transcript(video)

    return f"""
You are an English-language, source-grounded YouTube knowledge assistant.
Create structured study notes from the video transcript below.

Rules:
- Work and answer in English, even when the transcript is in another language.
- Use only information present in the transcript and metadata.
- Do not invent facts, dates, claims, names, or conclusions.
- The response must be ONLY valid JSON, without a markdown code block.
- The "topics", "takeaways", and "questions" fields must be arrays.
- The "obsidian_note" field must start with "# {{video title}}" as the root heading, followed by "## Section" headings. ALL content must be "- bullet" items — no prose paragraphs. This makes it compatible with the Obsidian markmap plugin for mind map rendering.
- If the transcript contains timestamps, keep them next to important claims in parentheses, for example (12:34).

JSON schema:
{{
  "summary": "A concise 5-8 sentence summary",
  "topics": ["topic 1", "topic 2"],
  "takeaways": ["key takeaway 1", "key takeaway 2"],
  "questions": ["useful review or study question 1", "question 2"],
  "obsidian_note": "# Video Title\\n## Summary\\n- key point 1\\n- key point 2\\n\\n## Topics\\n- topic 1\\n\\n## Takeaways\\n- takeaway 1\\n\\n## Questions\\n- question 1"
}}

Video:
Title: {title}
URL: {url}
Uploaded: {uploaded}
Duration in seconds: {duration}

Transcript:
{transcript}
""".strip()


async def generate_ai_notes(video: dict) -> Optional[dict]:
    transcript = video.get("transcript") or video.get("transcript_timed")
    if not transcript:
        return None

    messages = [
        {
            "role": "system",
            "content": "You are a source-grounded English note-taking assistant. Always return valid JSON only.",
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
