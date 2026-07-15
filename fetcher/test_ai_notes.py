"""Self-check for the SSE line-parsers in ai_notes.py. Run: python3 fetcher/test_ai_notes.py"""

from ai_notes import _parse_ollama_line, _parse_anthropic_line, _parse_openai_line


def test_parse_ollama_line() -> None:
    assert _parse_ollama_line('{"message": {"content": "hi"}, "done": false}') == {"delta": "hi"}
    assert _parse_ollama_line("not json") == {}
    done = _parse_ollama_line('{"message": {"content": ""}, "done": true, "eval_count": 5}')
    assert done["done"] is True and done["usage"]["final_chunk"]["eval_count"] == 5


def test_parse_anthropic_line() -> None:
    assert _parse_anthropic_line("event: ping") == {}
    assert _parse_anthropic_line("data: [DONE]") is None
    assert _parse_anthropic_line(
        'data: {"type": "content_block_delta", "delta": {"text": "hi"}}'
    ) == {"delta": "hi"}
    assert _parse_anthropic_line(
        'data: {"type": "message_start", "message": {"usage": {"input_tokens": 7}}}'
    ) == {"usage": {"input_tokens": 7}}


def test_parse_openai_line() -> None:
    assert _parse_openai_line("data: [DONE]") is None
    assert _parse_openai_line(
        'data: {"choices": [{"delta": {"content": "hi"}}]}'
    ) == {"delta": "hi"}
    assert _parse_openai_line(
        'data: {"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 4}}'
    ) == {"usage": {"prompt_tokens": 3, "completion_tokens": 4}}


if __name__ == "__main__":
    test_parse_ollama_line()
    test_parse_anthropic_line()
    test_parse_openai_line()
    print("ai_notes self-check OK")
