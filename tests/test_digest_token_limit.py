import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.llm import compose_digest


@pytest.mark.asyncio
async def test_digest_removes_oldest_then_lowest_score_until_within_token_limit(
    monkeypatch, capsys
):
    import src.llm as llm_module

    entries = [
        {
            "title": "old-low",
            "link": "https://example.com/old-low",
            "published": "2026-07-01T00:00:00+08:00",
            "source": "Example",
            "content": "old-low",
            "tags": [],
            "score": 60,
            "summary": "old-low",
        },
        {
            "title": "old-high",
            "link": "https://example.com/old-high",
            "published": "2026-07-01T00:00:00+08:00",
            "source": "Example",
            "content": "old-high",
            "tags": [],
            "score": 90,
            "summary": "old-high",
        },
        {
            "title": "new-low",
            "link": "https://example.com/new-low",
            "published": "2026-07-02T00:00:00+08:00",
            "source": "Example",
            "content": "new-low",
            "tags": [],
            "score": 10,
            "summary": "new-low",
        },
    ]
    captured = {}

    def fake_count_tokens(prompt):
        return sum(title in prompt for title in ("old-low", "old-high", "new-low"))

    async def fake_call_llm(prompt, config):
        captured["prompt"] = prompt
        return "# Digest"

    monkeypatch.setattr(llm_module, "_count_digest_tokens", fake_count_tokens)
    monkeypatch.setattr(llm_module, "call_llm", fake_call_llm)

    result = await compose_digest(
        entries,
        [],
        {
            "digest_max_input_tokens": 1,
            "prompts": {
                "domain": {
                    "domains": [
                        {"key": "AI", "digest": "prompts/digest/ai/digest.md"}
                    ]
                }
            },
        },
        domain="AI",
    )

    assert result == "# Digest"
    assert "new-low" in captured["prompt"]
    assert "old-low" not in captured["prompt"]
    assert "old-high" not in captured["prompt"]
    assert "[AI] token裁剪 | 上限: 1, 最终: 1, 保留: 1 条, 移除: 2 条" in (
        capsys.readouterr().out
    )
