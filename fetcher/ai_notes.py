"""AI note generation for YouTube transcripts via Ollama."""

import json
import logging
import os
import re
import time
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434").rstrip("/")
OLLAMA_CHAT_MODEL = os.environ.get("OLLAMA_CHAT_MODEL", "gemma4:31b-mlx-bf16")
AI_NOTES_MAX_CHARS = int(os.environ.get("AI_NOTES_MAX_CHARS", "45000"))
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "600"))


def configure_ai_notes(
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    max_chars: Optional[int] = None,
    timeout: Optional[int] = None,
) -> None:
    global OLLAMA_BASE_URL, OLLAMA_CHAT_MODEL, AI_NOTES_MAX_CHARS, OLLAMA_TIMEOUT
    if base_url:
        OLLAMA_BASE_URL = base_url.rstrip("/")
    if model:
        OLLAMA_CHAT_MODEL = model
    if max_chars is not None:
        AI_NOTES_MAX_CHARS = max(1000, int(max_chars))
    if timeout is not None:
        OLLAMA_TIMEOUT = max(30, int(timeout))


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
- The "obsidian_note" field must start with "# {{video title}}" as the root heading, followed by "## Section" headings. ALL content must be "- bullet" items — no prose paragraphs. Include a "## Critical Notes" section when critique points exist. This makes it compatible with the Obsidian markmap plugin for mind map rendering.
- The "study_guide" field must be structured learning markdown: "## Learning Objectives" (3-5 bullet goals), "## Key Concepts" (- **Term**: definition), "## Content Breakdown" (timestamp-anchored bullets, e.g. "(5:23) Topic: ..."), "## Review" (2-3 practice prompts). English only.
- The "critique" field must challenge the video's reasoning using only the transcript: unsupported claims, overgeneralizations, missing caveats, assumptions to verify, and alternative interpretations. Do not fact-check with outside knowledge.
- If the transcript contains timestamps, keep them next to important claims in parentheses, for example (12:34).

JSON schema:
{{
  "summary": "A concise 5-8 sentence summary",
  "topics": ["topic 1", "topic 2"],
  "takeaways": ["key takeaway 1", "key takeaway 2"],
  "questions": ["useful review or study question 1", "question 2"],
  "obsidian_note": "# Video Title\\n## Summary\\n- key point 1\\n- key point 2\\n\\n## Topics\\n- topic 1\\n\\n## Takeaways\\n- takeaway 1\\n\\n## Questions\\n- question 1",
  "study_guide": "## Learning Objectives\\n- ...\\n\\n## Key Concepts\\n- **Term**: definition\\n\\n## Content Breakdown\\n- (0:00) Introduction: ...\\n- (5:23) Core topic: ...\\n\\n## Review\\n- Try to explain X in your own words",
  "critique": "## Critical Notes\\n- The transcript asserts ... but does not show ...\\n\\n## Assumptions to Check\\n- ...\\n\\n## Alternative Interpretations\\n- ..."
}}

Video:
Title: {title}
URL: {url}
Uploaded: {uploaded}
Duration in seconds: {duration}

Transcript:
{transcript}
""".strip()


def ns_to_seconds(value: Any) -> Optional[float]:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return None
    return round(number / 1_000_000_000, 3) if number > 0 else None


async def generate_ai_notes(video: dict) -> Optional[dict]:
    transcript = video.get("transcript") or video.get("transcript_timed")
    if not transcript:
        return None
    compacted = compact_transcript(video)
    prompt_start = time.monotonic()
    prompt = build_prompt({**video, "transcript": compacted, "transcript_timed": None})
    prompt_build_seconds = round(time.monotonic() - prompt_start, 3)

    messages = [
        {
            "role": "system",
            "content": "You are a source-grounded English note-taking assistant. Always return valid JSON only.",
        },
        {"role": "user", "content": prompt},
    ]
    payload = {
        "model": OLLAMA_CHAT_MODEL,
        "messages": messages,
        "stream": True,
        "format": "json",
    }

    # Stream the response. read=None disables the per-chunk read timeout so
    # large models that take >10 min to load or generate don't timeout.
    # connect=30 still guards against an unreachable server.
    chunks = []
    final_chunk = {}
    stream_started = time.monotonic()
    first_token_seconds = None
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(None, connect=30)
    ) as client:
        async with client.stream("POST", f"{OLLAMA_BASE_URL}/api/chat", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                delta = chunk.get("message", {}).get("content", "")
                if delta:
                    if first_token_seconds is None:
                        first_token_seconds = round(time.monotonic() - stream_started, 3)
                    chunks.append(delta)
                if chunk.get("done"):
                    final_chunk = chunk

    content = "".join(chunks)
    parse_start = time.monotonic()
    parsed = extract_json(content)
    parse_seconds = round(time.monotonic() - parse_start, 3)
    total_seconds = round(time.monotonic() - stream_started + prompt_build_seconds, 3)
    eval_count = int(final_chunk.get("eval_count") or 0)
    eval_seconds = ns_to_seconds(final_chunk.get("eval_duration"))
    metrics = {
        "model": OLLAMA_CHAT_MODEL,
        "transcript_chars": len(transcript),
        "prompt_chars": len(prompt),
        "output_chars": len(content),
        "chunks": len(chunks),
        "prompt_build_seconds": prompt_build_seconds,
        "first_token_seconds": first_token_seconds,
        "json_parse_seconds": parse_seconds,
        "total_seconds": total_seconds,
        "ollama_total_seconds": ns_to_seconds(final_chunk.get("total_duration")),
        "ollama_load_seconds": ns_to_seconds(final_chunk.get("load_duration")),
        "prompt_eval_count": final_chunk.get("prompt_eval_count"),
        "prompt_eval_seconds": ns_to_seconds(final_chunk.get("prompt_eval_duration")),
        "eval_count": eval_count or None,
        "eval_seconds": eval_seconds,
        "eval_tokens_per_second": round(eval_count / eval_seconds, 2) if eval_count and eval_seconds else None,
    }
    return {
        "summary": str(parsed.get("summary", "")).strip(),
        "topics": normalize_list(parsed.get("topics")),
        "takeaways": normalize_list(parsed.get("takeaways")),
        "questions": normalize_list(parsed.get("questions")),
        "obsidian_note": str(parsed.get("obsidian_note", "")).strip(),
        "study_guide": str(parsed.get("study_guide", "")).strip(),
        "critique": str(parsed.get("critique", "")).strip(),
        "_metrics": metrics,
    }
