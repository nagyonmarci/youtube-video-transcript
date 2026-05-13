"""AI note generation for YouTube transcripts via Ollama or cloud providers."""

import asyncio
import json
import logging
import os
import re
import time
from typing import Any, Awaitable, Callable, Optional

import httpx

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434").rstrip("/")
OLLAMA_CHAT_MODEL = os.environ.get("OLLAMA_CHAT_MODEL", "gemma4:31b-mlx-bf16")
AI_NOTES_MAX_CHARS = int(os.environ.get("AI_NOTES_MAX_CHARS", "45000"))
OLLAMA_TIMEOUT = int(os.environ.get("OLLAMA_TIMEOUT", "600"))
OLLAMA_QUICK_MODEL = os.environ.get("OLLAMA_QUICK_MODEL", "llama3.2")
OLLAMA_QUICK_TIMEOUT = int(os.environ.get("OLLAMA_QUICK_TIMEOUT", "300"))
OLLAMA_NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "32768"))
OLLAMA_QUICK_NUM_CTX = int(os.environ.get("OLLAMA_QUICK_NUM_CTX", "4096"))
OLLAMA_TEMPERATURE = float(os.environ.get("OLLAMA_TEMPERATURE", "0.1"))
OLLAMA_NUM_PREDICT = int(os.environ.get("OLLAMA_NUM_PREDICT", "8192"))
AI_PROVIDER = os.environ.get("AI_PROVIDER", "ollama")  # "ollama" | "anthropic" | "openai"
AI_CLOUD_MODEL = os.environ.get("AI_CLOUD_MODEL", "claude-opus-4-7")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")


def configure_ai_notes(
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    max_chars: Optional[int] = None,
    timeout: Optional[int] = None,
    quick_model: Optional[str] = None,
    quick_timeout: Optional[int] = None,
    num_ctx: Optional[int] = None,
    quick_num_ctx: Optional[int] = None,
    temperature: Optional[float] = None,
    num_predict: Optional[int] = None,
    provider: Optional[str] = None,
    cloud_model: Optional[str] = None,
    anthropic_api_key: Optional[str] = None,
    openai_api_key: Optional[str] = None,
    openai_base_url: Optional[str] = None,
) -> None:
    global OLLAMA_BASE_URL, OLLAMA_CHAT_MODEL, AI_NOTES_MAX_CHARS, OLLAMA_TIMEOUT
    global OLLAMA_QUICK_MODEL, OLLAMA_QUICK_TIMEOUT
    global OLLAMA_NUM_CTX, OLLAMA_QUICK_NUM_CTX, OLLAMA_TEMPERATURE, OLLAMA_NUM_PREDICT
    global AI_PROVIDER, AI_CLOUD_MODEL, ANTHROPIC_API_KEY, OPENAI_API_KEY, OPENAI_BASE_URL
    if base_url:
        OLLAMA_BASE_URL = base_url.rstrip("/")
    if model:
        OLLAMA_CHAT_MODEL = model
    if max_chars is not None:
        AI_NOTES_MAX_CHARS = max(1000, int(max_chars))
    if timeout is not None:
        OLLAMA_TIMEOUT = max(30, int(timeout))
    if quick_model:
        OLLAMA_QUICK_MODEL = quick_model
    if quick_timeout is not None:
        OLLAMA_QUICK_TIMEOUT = max(10, int(quick_timeout))
    if num_ctx is not None:
        OLLAMA_NUM_CTX = max(2048, int(num_ctx))
    if quick_num_ctx is not None:
        OLLAMA_QUICK_NUM_CTX = max(512, int(quick_num_ctx))
    if temperature is not None:
        OLLAMA_TEMPERATURE = float(temperature)
    if num_predict is not None:
        OLLAMA_NUM_PREDICT = max(256, int(num_predict))
    if provider:
        AI_PROVIDER = provider.lower().strip()
    if cloud_model:
        AI_CLOUD_MODEL = cloud_model
    if anthropic_api_key is not None:
        ANTHROPIC_API_KEY = anthropic_api_key
    if openai_api_key is not None:
        OPENAI_API_KEY = openai_api_key
    if openai_base_url:
        OPENAI_BASE_URL = openai_base_url.rstrip("/")


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


def _fmt_elapsed(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s}s" if m else f"{s}s"


def ns_to_seconds(value: Any) -> Optional[float]:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return None
    return round(number / 1_000_000_000, 3) if number > 0 else None


ProgressCallback = Callable[[dict], Awaitable[None]]


QUICK_MAX_CHARS = 3000  # keep prompt short so small models respond quickly


async def generate_quick_summary(
    video: dict, progress_callback: Optional[ProgressCallback] = None
) -> Optional[str]:
    """Generate a quick summary using a small fast Ollama model."""
    transcript = video.get("transcript") or video.get("transcript_timed")
    if not transcript:
        return None
    # Hard-cap input so small models stay fast regardless of AI_NOTES_MAX_CHARS
    raw = re.sub(r"\n{3,}", "\n\n", transcript.strip())
    snippet = raw[:QUICK_MAX_CHARS]
    title = video.get("title") or "Unknown title"
    prompt = (
        f'Summarize this YouTube video in 3-5 sentences. '
        f'Return ONLY valid JSON: {{"summary": "..."}}\n\n'
        f"Title: {title}\n\nTranscript:\n{snippet}"
    )
    payload = {
        "model": OLLAMA_QUICK_MODEL,
        "messages": [
            {"role": "system", "content": "You are a concise summarizer. Return only valid JSON, no other text."},
            {"role": "user", "content": prompt},
        ],
        "stream": True,
        # No format:"json" — avoid Ollama constrained-decoding overhead
        "options": {
            "num_predict": 512,
            "num_ctx": OLLAMA_QUICK_NUM_CTX,
            "temperature": OLLAMA_TEMPERATURE,
        },
    }
    chunks: list[str] = []
    stream_started = time.monotonic()

    if progress_callback:
        await progress_callback({
            "phase": "quick_summary",
            "progress_label": f"Quick summary ({OLLAMA_QUICK_MODEL})...",
        })

    async def _stream() -> None:
        async with httpx.AsyncClient(timeout=httpx.Timeout(None, connect=30)) as client:
            async with client.stream("POST", f"{OLLAMA_BASE_URL}/api/chat", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    delta = chunk.get("message", {}).get("content", "")
                    if delta:
                        chunks.append(delta)
                    if chunk.get("done"):
                        break

    try:
        await asyncio.wait_for(_stream(), timeout=OLLAMA_QUICK_TIMEOUT)
    except asyncio.TimeoutError:
        elapsed = round(time.monotonic() - stream_started, 1)
        raise TimeoutError(
            f"Quick summary timed out after {OLLAMA_QUICK_TIMEOUT}s (elapsed: {elapsed}s, model: {OLLAMA_QUICK_MODEL})"
        )

    content = "".join(chunks)
    try:
        parsed = extract_json(content)
        result = str(parsed.get("summary", "")).strip()
        return result or None
    except Exception as e:
        logger.warning(f"Quick summary JSON parse failed: {e}; raw: {content[:200]}")
        return None


async def _generate_ai_notes_ollama(
    video: dict, progress_callback: Optional[ProgressCallback] = None
) -> Optional[dict]:
    """Generate full AI notes via Ollama (local)."""
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
        "options": {
            "num_ctx": OLLAMA_NUM_CTX,
            "temperature": OLLAMA_TEMPERATURE,
            "num_predict": OLLAMA_NUM_PREDICT,
        },
    }

    chunks: list[str] = []
    _final: list[dict] = [{}]
    _first_token_at: list[Optional[float]] = [None]
    stream_started = time.monotonic()

    if progress_callback:
        await progress_callback({
            "phase": "waiting_first_token",
            "progress_label": f"Waiting for Ollama first token ({OLLAMA_CHAT_MODEL})",
            "prompt_chars": len(prompt),
            "transcript_chars": len(transcript),
        })

    async def _stream() -> None:
        # read=None: no per-chunk timeout so slow/large models don't get cut off mid-stream.
        # connect=30: still guards against an unreachable server.
        # The outer asyncio.wait_for provides the overall deadline via OLLAMA_TIMEOUT.
        async with httpx.AsyncClient(timeout=httpx.Timeout(None, connect=30)) as client:
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
                        if _first_token_at[0] is None:
                            _first_token_at[0] = round(time.monotonic() - stream_started, 3)
                        chunks.append(delta)
                    if chunk.get("done"):
                        _final[0] = chunk

    async def _progress_ticker() -> None:
        while True:
            await asyncio.sleep(10)
            if not progress_callback:
                continue
            elapsed = time.monotonic() - stream_started
            label = _fmt_elapsed(elapsed)
            if _first_token_at[0] is None:
                await progress_callback({
                    "phase": "waiting_first_token",
                    "progress_label": f"Waiting for Ollama first token ({label} elapsed)",
                    "prompt_chars": len(prompt),
                    "transcript_chars": len(transcript),
                })
            else:
                output_chars = sum(len(c) for c in chunks)
                await progress_callback({
                    "phase": "generating",
                    "progress_label": f"Generating... ({label} elapsed, {output_chars} chars)",
                    "first_token_seconds": _first_token_at[0],
                    "prompt_chars": len(prompt),
                    "transcript_chars": len(transcript),
                })

    progress_task = asyncio.create_task(_progress_ticker())
    try:
        await asyncio.wait_for(_stream(), timeout=OLLAMA_TIMEOUT)
    except asyncio.TimeoutError:
        elapsed = round(time.monotonic() - stream_started, 1)
        raise TimeoutError(
            f"Ollama did not finish within {OLLAMA_TIMEOUT}s "
            f"(elapsed: {elapsed}s, model: {OLLAMA_CHAT_MODEL}, "
            f"first_token: {_first_token_at[0]})"
        )
    finally:
        progress_task.cancel()
        try:
            await progress_task
        except asyncio.CancelledError:
            pass

    first_token_seconds = _first_token_at[0]
    final_chunk = _final[0]

    content = "".join(chunks)
    if progress_callback:
        await progress_callback({
            "phase": "parsing_json",
            "progress_label": "Parsing Ollama JSON response",
            "first_token_seconds": first_token_seconds,
            "output_chars": len(content),
        })
    parse_start = time.monotonic()
    parsed = extract_json(content)
    parse_seconds = round(time.monotonic() - parse_start, 3)
    total_seconds = round(time.monotonic() - stream_started + prompt_build_seconds, 3)
    eval_count = int(final_chunk.get("eval_count") or 0)
    eval_seconds = ns_to_seconds(final_chunk.get("eval_duration"))
    metrics = {
        "model": OLLAMA_CHAT_MODEL,
        "provider": "ollama",
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


async def _generate_ai_notes_anthropic(
    video: dict, progress_callback: Optional[ProgressCallback] = None
) -> Optional[dict]:
    """Generate full AI notes via Anthropic cloud API (SSE streaming via httpx)."""
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY is not set")
    transcript = video.get("transcript") or video.get("transcript_timed")
    if not transcript:
        return None
    compacted = compact_transcript(video)
    prompt_start = time.monotonic()
    prompt = build_prompt({**video, "transcript": compacted, "transcript_timed": None})
    prompt_build_seconds = round(time.monotonic() - prompt_start, 3)

    payload = {
        "model": AI_CLOUD_MODEL,
        "max_tokens": 8192,
        "system": "You are a source-grounded English note-taking assistant. Always return valid JSON only.",
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
    }
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    chunks: list[str] = []
    _first_token_at: list[Optional[float]] = [None]
    _input_tokens: list[int] = [0]
    _output_tokens: list[int] = [0]
    stream_started = time.monotonic()

    if progress_callback:
        await progress_callback({
            "phase": "waiting_first_token",
            "progress_label": f"Waiting for Anthropic first token ({AI_CLOUD_MODEL})",
            "prompt_chars": len(prompt),
            "transcript_chars": len(transcript),
        })

    async def _stream() -> None:
        async with httpx.AsyncClient(timeout=httpx.Timeout(None, connect=30)) as client:
            async with client.stream(
                "POST",
                "https://api.anthropic.com/v1/messages",
                json=payload,
                headers=headers,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    event_type = event.get("type")
                    if event_type == "content_block_delta":
                        delta = event.get("delta", {}).get("text", "")
                        if delta:
                            if _first_token_at[0] is None:
                                _first_token_at[0] = round(time.monotonic() - stream_started, 3)
                            chunks.append(delta)
                    elif event_type == "message_start":
                        usage = event.get("message", {}).get("usage", {})
                        _input_tokens[0] = usage.get("input_tokens", 0)
                    elif event_type == "message_delta":
                        usage = event.get("usage", {})
                        _output_tokens[0] = usage.get("output_tokens", 0)

    async def _progress_ticker() -> None:
        while True:
            await asyncio.sleep(10)
            if not progress_callback:
                continue
            elapsed = time.monotonic() - stream_started
            label = _fmt_elapsed(elapsed)
            if _first_token_at[0] is None:
                await progress_callback({
                    "phase": "waiting_first_token",
                    "progress_label": f"Waiting for Anthropic first token ({label} elapsed)",
                    "prompt_chars": len(prompt),
                    "transcript_chars": len(transcript),
                })
            else:
                output_chars = sum(len(c) for c in chunks)
                await progress_callback({
                    "phase": "generating",
                    "progress_label": f"Generating [{AI_CLOUD_MODEL}]... ({label} elapsed, {output_chars} chars)",
                    "first_token_seconds": _first_token_at[0],
                    "prompt_chars": len(prompt),
                    "transcript_chars": len(transcript),
                })

    progress_task = asyncio.create_task(_progress_ticker())
    try:
        await asyncio.wait_for(_stream(), timeout=OLLAMA_TIMEOUT)
    except asyncio.TimeoutError:
        elapsed = round(time.monotonic() - stream_started, 1)
        raise TimeoutError(
            f"Anthropic did not finish within {OLLAMA_TIMEOUT}s "
            f"(elapsed: {elapsed}s, model: {AI_CLOUD_MODEL}, "
            f"first_token: {_first_token_at[0]})"
        )
    finally:
        progress_task.cancel()
        try:
            await progress_task
        except asyncio.CancelledError:
            pass

    content = "".join(chunks)
    if progress_callback:
        await progress_callback({
            "phase": "parsing_json",
            "progress_label": f"Parsing Anthropic JSON response ({AI_CLOUD_MODEL})",
            "first_token_seconds": _first_token_at[0],
            "output_chars": len(content),
        })
    parse_start = time.monotonic()
    parsed = extract_json(content)
    parse_seconds = round(time.monotonic() - parse_start, 3)
    total_seconds = round(time.monotonic() - stream_started + prompt_build_seconds, 3)
    metrics = {
        "model": AI_CLOUD_MODEL,
        "provider": "anthropic",
        "transcript_chars": len(transcript),
        "prompt_chars": len(prompt),
        "output_chars": len(content),
        "chunks": len(chunks),
        "prompt_build_seconds": prompt_build_seconds,
        "first_token_seconds": _first_token_at[0],
        "json_parse_seconds": parse_seconds,
        "total_seconds": total_seconds,
        "prompt_eval_count": _input_tokens[0] or None,
        "eval_count": _output_tokens[0] or None,
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


async def _generate_ai_notes_openai(
    video: dict, progress_callback: Optional[ProgressCallback] = None
) -> Optional[dict]:
    """Generate full AI notes via OpenAI-compatible API (SSE streaming via httpx)."""
    if not OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is not set")
    transcript = video.get("transcript") or video.get("transcript_timed")
    if not transcript:
        return None
    compacted = compact_transcript(video)
    prompt_start = time.monotonic()
    prompt = build_prompt({**video, "transcript": compacted, "transcript_timed": None})
    prompt_build_seconds = round(time.monotonic() - prompt_start, 3)

    payload = {
        "model": AI_CLOUD_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "You are a source-grounded English note-taking assistant. Always return valid JSON only.",
            },
            {"role": "user", "content": prompt},
        ],
        "stream": True,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "content-type": "application/json",
    }

    chunks: list[str] = []
    _first_token_at: list[Optional[float]] = [None]
    _prompt_tokens: list[int] = [0]
    _completion_tokens: list[int] = [0]
    stream_started = time.monotonic()

    if progress_callback:
        await progress_callback({
            "phase": "waiting_first_token",
            "progress_label": f"Waiting for OpenAI first token ({AI_CLOUD_MODEL})",
            "prompt_chars": len(prompt),
            "transcript_chars": len(transcript),
        })

    async def _stream() -> None:
        async with httpx.AsyncClient(timeout=httpx.Timeout(None, connect=30)) as client:
            async with client.stream(
                "POST",
                f"{OPENAI_BASE_URL}/chat/completions",
                json=payload,
                headers=headers,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    for choice in event.get("choices", []):
                        delta = choice.get("delta", {}).get("content", "")
                        if delta:
                            if _first_token_at[0] is None:
                                _first_token_at[0] = round(time.monotonic() - stream_started, 3)
                            chunks.append(delta)
                    usage = event.get("usage") or {}
                    if usage.get("prompt_tokens"):
                        _prompt_tokens[0] = usage["prompt_tokens"]
                    if usage.get("completion_tokens"):
                        _completion_tokens[0] = usage["completion_tokens"]

    async def _progress_ticker() -> None:
        while True:
            await asyncio.sleep(10)
            if not progress_callback:
                continue
            elapsed = time.monotonic() - stream_started
            label = _fmt_elapsed(elapsed)
            if _first_token_at[0] is None:
                await progress_callback({
                    "phase": "waiting_first_token",
                    "progress_label": f"Waiting for OpenAI first token ({label} elapsed)",
                    "prompt_chars": len(prompt),
                    "transcript_chars": len(transcript),
                })
            else:
                output_chars = sum(len(c) for c in chunks)
                await progress_callback({
                    "phase": "generating",
                    "progress_label": f"Generating [{AI_CLOUD_MODEL}]... ({label} elapsed, {output_chars} chars)",
                    "first_token_seconds": _first_token_at[0],
                    "prompt_chars": len(prompt),
                    "transcript_chars": len(transcript),
                })

    progress_task = asyncio.create_task(_progress_ticker())
    try:
        await asyncio.wait_for(_stream(), timeout=OLLAMA_TIMEOUT)
    except asyncio.TimeoutError:
        elapsed = round(time.monotonic() - stream_started, 1)
        raise TimeoutError(
            f"OpenAI did not finish within {OLLAMA_TIMEOUT}s "
            f"(elapsed: {elapsed}s, model: {AI_CLOUD_MODEL}, "
            f"first_token: {_first_token_at[0]})"
        )
    finally:
        progress_task.cancel()
        try:
            await progress_task
        except asyncio.CancelledError:
            pass

    content = "".join(chunks)
    if progress_callback:
        await progress_callback({
            "phase": "parsing_json",
            "progress_label": f"Parsing OpenAI JSON response ({AI_CLOUD_MODEL})",
            "first_token_seconds": _first_token_at[0],
            "output_chars": len(content),
        })
    parse_start = time.monotonic()
    parsed = extract_json(content)
    parse_seconds = round(time.monotonic() - parse_start, 3)
    total_seconds = round(time.monotonic() - stream_started + prompt_build_seconds, 3)
    metrics = {
        "model": AI_CLOUD_MODEL,
        "provider": "openai",
        "transcript_chars": len(transcript),
        "prompt_chars": len(prompt),
        "output_chars": len(content),
        "chunks": len(chunks),
        "prompt_build_seconds": prompt_build_seconds,
        "first_token_seconds": _first_token_at[0],
        "json_parse_seconds": parse_seconds,
        "total_seconds": total_seconds,
        "prompt_eval_count": _prompt_tokens[0] or None,
        "eval_count": _completion_tokens[0] or None,
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


async def generate_ai_notes(
    video: dict, progress_callback: Optional[ProgressCallback] = None
) -> Optional[dict]:
    """Generate full AI notes — dispatches to the configured provider."""
    if AI_PROVIDER == "anthropic":
        return await _generate_ai_notes_anthropic(video, progress_callback)
    if AI_PROVIDER == "openai":
        return await _generate_ai_notes_openai(video, progress_callback)
    return await _generate_ai_notes_ollama(video, progress_callback)
