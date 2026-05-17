"""测试 insights 模块"""

import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Stub Task 17's LLM function until it lands
import src.llm as _llm
if not hasattr(_llm, "generate_trend_insights"):
    async def _stub(*a, **k):
        return "", None
    _llm.generate_trend_insights = _stub

from src.sections.insights.section import run_insights_section


def _cfg() -> dict:
    return {
        "filter": {"push_context_days": 5},
        "sections": {"insights": {"enabled": True}},
        "llm": {
            "model": "x",
            "baseUrl": "http://x",
            "apiKeyName": "DEEPSEEK_API_KEY",
            "prompts": {"insights": "prompts/insights.md"},
        },
    }


@pytest.mark.asyncio
async def test_disabled_returns_empty():
    cfg = _cfg()
    cfg["sections"]["insights"]["enabled"] = False
    md, err = await run_insights_section("rss", "gh", "hn", cfg, now=None)
    assert md == ""
    assert err is None


@pytest.mark.asyncio
async def test_marks_empty_sections_for_llm():
    cfg = _cfg()
    captured = {}

    async def fake_gen(sections, recent_insights, config):
        captured["sections"] = sections
        return "insights md", None

    with patch(
        "src.sections.insights.section.load_recent_section_titles", return_value=""
    ), patch(
        "src.llm.generate_trend_insights",
        new=AsyncMock(side_effect=fake_gen),
    ):
        md, err = await run_insights_section("", "gh md", "", cfg, now=None)

    assert md == "insights md"
    assert captured["sections"]["rss"] == "(本次无内容)"
    assert captured["sections"]["github"] == "gh md"
    assert captured["sections"]["hackernews"] == "(本次无内容)"
