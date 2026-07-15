"""AI note generation for YouTube transcripts via Ollama or cloud providers."""

import asyncio
import json
import logging
import re
import time
from typing import Any, Awaitable, Callable, Optional

import httpx

logger = logging.getLogger(__name__)

# Placeholder defaults matching config.py's env-parsed values; config.apply_app_settings()
# always calls configure_ai_notes() at boot before any of these are used for a real request.
# config.py can't be imported here directly (it imports configure_ai_notes from this module).
OLLAMA_BASE_URL = "http://host.docker.internal:11434"
OLLAMA_CHAT_MODEL = "gemma4:31b-mlx-bf16"
AI_NOTES_MAX_CHARS = 45000
OLLAMA_TIMEOUT = 600
OLLAMA_QUICK_MODEL = "qwen3:4b"
OLLAMA_QUICK_TIMEOUT = 120
OLLAMA_NUM_CTX = 32768
OLLAMA_QUICK_NUM_CTX = 4096
OLLAMA_TEMPERATURE = 0.1
OLLAMA_NUM_PREDICT = 8192
AI_PROVIDER = "ollama"  # "ollama" | "anthropic" | "openai"
AI_CLOUD_MODEL = "claude-opus-4-7"
ANTHROPIC_API_KEY = ""
OPENAI_API_KEY = ""
OPENAI_BASE_URL = "https://api.openai.com/v1"


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


def _parse_ollama_line(line: str) -> dict:
    """Ollama NDJSON: one {"message": {"content": ...}, "done": ...} object per line."""
    try:
        chunk = json.loads(line)
    except json.JSONDecodeError:
        return {}
    event: dict = {}
    delta = chunk.get("message", {}).get("content", "")
    if delta:
        event["delta"] = delta
    if chunk.get("done"):
        event["done"] = True
        event["usage"] = {"final_chunk": chunk}
    return event


def _parse_anthropic_line(line: str) -> Optional[dict]:
    """Anthropic SSE: "data: {...}" events, terminated by "data: [DONE]"."""
    if not line.startswith("data: "):
        return {}
    data = line[6:]
    if data == "[DONE]":
        return None
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return {}
    event_type = payload.get("type")
    if event_type == "content_block_delta":
        delta = payload.get("delta", {}).get("text", "")
        return {"delta": delta} if delta else {}
    if event_type == "message_start":
        usage = payload.get("message", {}).get("usage", {})
        return {"usage": {"input_tokens": usage.get("input_tokens", 0)}}
    if event_type == "message_delta":
        usage = payload.get("usage", {})
        return {"usage": {"output_tokens": usage.get("output_tokens", 0)}}
    return {}


def _parse_openai_line(line: str) -> Optional[dict]:
    """OpenAI-compatible SSE: "data: {...}" events, terminated by "data: [DONE]"."""
    if not line.startswith("data: "):
        return {}
    data = line[6:]
    if data == "[DONE]":
        return None
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return {}
    choices = payload.get("choices") or []
    delta = choices[0].get("delta", {}).get("content", "") if choices else ""
    event = {"delta": delta} if delta else {}
    usage = payload.get("usage") or {}
    extra_usage = {}
    if usage.get("prompt_tokens"):
        extra_usage["prompt_tokens"] = usage["prompt_tokens"]
    if usage.get("completion_tokens"):
        extra_usage["completion_tokens"] = usage["completion_tokens"]
    if extra_usage:
        event["usage"] = extra_usage
    return event


async def _stream_chat(
    *,
    provider_name: str,
    model: str,
    url: str,
    headers: Optional[dict],
    payload: dict,
    timeout: int,
    parse_line: Callable[[str], Optional[dict]],
    generating_prefix: str,
    progress_callback: Optional[ProgressCallback],
    prompt: str,
    transcript: str,
) -> tuple[str, dict, Optional[float], int, float]:
    """Shared chat-completion streaming loop: first-token/progress callbacks, a 10s
    progress ticker, and timeout handling, identical across every provider.

    `parse_line` turns one response line into an event dict — any of `delta` (text
    chunk), `usage` (dict merged into the returned usage state), `done` (stop the
    stream) — or `None` to stop the stream early (e.g. an SSE "[DONE]").

    Returns (content, usage, first_token_seconds, chunk_count, stream_started).
    """
    chunks: list[str] = []
    usage: dict = {}
    first_token_at: list[Optional[float]] = [None]
    stream_started = time.monotonic()

    if progress_callback:
        await progress_callback({
            "phase": "waiting_first_token",
            "progress_label": f"Waiting for {provider_name} first token ({model})",
            "prompt_chars": len(prompt),
            "transcript_chars": len(transcript),
        })

    async def _stream() -> None:
        # read=None: no per-chunk timeout so slow/large models don't get cut off mid-stream.
        # connect=30: still guards against an unreachable server.
        # The outer asyncio.wait_for provides the overall deadline via `timeout`.
        async with httpx.AsyncClient(timeout=httpx.Timeout(None, connect=30)) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    event = parse_line(line)
                    if event is None:
                        break
                    delta = event.get("delta")
                    if delta:
                        if first_token_at[0] is None:
                            first_token_at[0] = round(time.monotonic() - stream_started, 3)
                        chunks.append(delta)
                    if "usage" in event:
                        usage.update(event["usage"])
                    if event.get("done"):
                        break

    async def _progress_ticker() -> None:
        while True:
            await asyncio.sleep(10)
            if not progress_callback:
                continue
            elapsed_label = _fmt_elapsed(time.monotonic() - stream_started)
            if first_token_at[0] is None:
                await progress_callback({
                    "phase": "waiting_first_token",
                    "progress_label": f"Waiting for {provider_name} first token ({elapsed_label} elapsed)",
                    "prompt_chars": len(prompt),
                    "transcript_chars": len(transcript),
                })
            else:
                output_chars = sum(len(c) for c in chunks)
                await progress_callback({
                    "phase": "generating",
                    "progress_label": f"{generating_prefix} ({elapsed_label} elapsed, {output_chars} chars)",
                    "first_token_seconds": first_token_at[0],
                    "prompt_chars": len(prompt),
                    "transcript_chars": len(transcript),
                })

    progress_task = asyncio.create_task(_progress_ticker())
    try:
        await asyncio.wait_for(_stream(), timeout=timeout)
    except asyncio.TimeoutError:
        elapsed = round(time.monotonic() - stream_started, 1)
        raise TimeoutError(
            f"{provider_name} did not finish within {timeout}s "
            f"(elapsed: {elapsed}s, model: {model}, "
            f"first_token: {first_token_at[0]})"
        )
    finally:
        progress_task.cancel()
        try:
            await progress_task
        except asyncio.CancelledError:
            pass

    return "".join(chunks), usage, first_token_at[0], len(chunks), stream_started


async def _finish_notes(
    *,
    provider: str,
    model: str,
    content: str,
    transcript: str,
    prompt: str,
    prompt_build_seconds: float,
    stream_started: float,
    first_token_seconds: Optional[float],
    progress_callback: Optional[ProgressCallback],
    parsing_label: str,
    extra_metrics: dict,
) -> dict:
    """Shared JSON-parse + result-shape step, identical across every provider."""
    if progress_callback:
        await progress_callback({
            "phase": "parsing_json",
            "progress_label": parsing_label,
            "first_token_seconds": first_token_seconds,
            "output_chars": len(content),
        })
    parse_start = time.monotonic()
    parsed = extract_json(content)
    parse_seconds = round(time.monotonic() - parse_start, 3)
    total_seconds = round(time.monotonic() - stream_started + prompt_build_seconds, 3)
    metrics = {
        "model": model,
        "provider": provider,
        "transcript_chars": len(transcript),
        "prompt_chars": len(prompt),
        "output_chars": len(content),
        "prompt_build_seconds": prompt_build_seconds,
        "first_token_seconds": first_token_seconds,
        "json_parse_seconds": parse_seconds,
        "total_seconds": total_seconds,
        **extra_metrics,
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

    payload = {
        "model": OLLAMA_CHAT_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "You are a source-grounded English note-taking assistant. Always return valid JSON only.",
            },
            {"role": "user", "content": prompt},
        ],
        "stream": True,
        "format": "json",
        "options": {
            "num_ctx": OLLAMA_NUM_CTX,
            "temperature": OLLAMA_TEMPERATURE,
            "num_predict": OLLAMA_NUM_PREDICT,
        },
    }

    content, usage, first_token_seconds, chunk_count, stream_started = await _stream_chat(
        provider_name="Ollama",
        model=OLLAMA_CHAT_MODEL,
        url=f"{OLLAMA_BASE_URL}/api/chat",
        headers=None,
        payload=payload,
        timeout=OLLAMA_TIMEOUT,
        parse_line=_parse_ollama_line,
        generating_prefix="Generating...",
        progress_callback=progress_callback,
        prompt=prompt,
        transcript=transcript,
    )

    final_chunk = usage.get("final_chunk", {})
    eval_count = int(final_chunk.get("eval_count") or 0)
    eval_seconds = ns_to_seconds(final_chunk.get("eval_duration"))
    return await _finish_notes(
        provider="ollama",
        model=OLLAMA_CHAT_MODEL,
        content=content,
        transcript=transcript,
        prompt=prompt,
        prompt_build_seconds=prompt_build_seconds,
        stream_started=stream_started,
        first_token_seconds=first_token_seconds,
        progress_callback=progress_callback,
        parsing_label="Parsing Ollama JSON response",
        extra_metrics={
            "chunks": chunk_count,
            "ollama_total_seconds": ns_to_seconds(final_chunk.get("total_duration")),
            "ollama_load_seconds": ns_to_seconds(final_chunk.get("load_duration")),
            "prompt_eval_count": final_chunk.get("prompt_eval_count"),
            "prompt_eval_seconds": ns_to_seconds(final_chunk.get("prompt_eval_duration")),
            "eval_count": eval_count or None,
            "eval_seconds": eval_seconds,
            "eval_tokens_per_second": round(eval_count / eval_seconds, 2) if eval_count and eval_seconds else None,
            "num_ctx": OLLAMA_NUM_CTX,
            "num_predict": OLLAMA_NUM_PREDICT,
            "temperature": OLLAMA_TEMPERATURE,
        },
    )


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

    content, usage, first_token_seconds, chunk_count, stream_started = await _stream_chat(
        provider_name="Anthropic",
        model=AI_CLOUD_MODEL,
        url="https://api.anthropic.com/v1/messages",
        headers=headers,
        payload=payload,
        timeout=OLLAMA_TIMEOUT,
        parse_line=_parse_anthropic_line,
        generating_prefix=f"Generating [{AI_CLOUD_MODEL}]...",
        progress_callback=progress_callback,
        prompt=prompt,
        transcript=transcript,
    )

    return await _finish_notes(
        provider="anthropic",
        model=AI_CLOUD_MODEL,
        content=content,
        transcript=transcript,
        prompt=prompt,
        prompt_build_seconds=prompt_build_seconds,
        stream_started=stream_started,
        first_token_seconds=first_token_seconds,
        progress_callback=progress_callback,
        parsing_label=f"Parsing Anthropic JSON response ({AI_CLOUD_MODEL})",
        extra_metrics={
            "chunks": chunk_count,
            "prompt_eval_count": usage.get("input_tokens") or None,
            "eval_count": usage.get("output_tokens") or None,
        },
    )


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

    content, usage, first_token_seconds, chunk_count, stream_started = await _stream_chat(
        provider_name="OpenAI",
        model=AI_CLOUD_MODEL,
        url=f"{OPENAI_BASE_URL}/chat/completions",
        headers=headers,
        payload=payload,
        timeout=OLLAMA_TIMEOUT,
        parse_line=_parse_openai_line,
        generating_prefix=f"Generating [{AI_CLOUD_MODEL}]...",
        progress_callback=progress_callback,
        prompt=prompt,
        transcript=transcript,
    )

    return await _finish_notes(
        provider="openai",
        model=AI_CLOUD_MODEL,
        content=content,
        transcript=transcript,
        prompt=prompt,
        prompt_build_seconds=prompt_build_seconds,
        stream_started=stream_started,
        first_token_seconds=first_token_seconds,
        progress_callback=progress_callback,
        parsing_label=f"Parsing OpenAI JSON response ({AI_CLOUD_MODEL})",
        extra_metrics={
            "chunks": chunk_count,
            "prompt_eval_count": usage.get("prompt_tokens") or None,
            "eval_count": usage.get("completion_tokens") or None,
        },
    )


async def generate_ai_notes(
    video: dict, progress_callback: Optional[ProgressCallback] = None
) -> Optional[dict]:
    """Generate full AI notes — dispatches to the configured provider."""
    if AI_PROVIDER == "anthropic":
        return await _generate_ai_notes_anthropic(video, progress_callback)
    if AI_PROVIDER == "openai":
        return await _generate_ai_notes_openai(video, progress_callback)
    return await _generate_ai_notes_ollama(video, progress_callback)


