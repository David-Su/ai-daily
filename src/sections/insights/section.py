"""Insights 板块:基于 RSS/GH/HN 三段成品 + 近 N 天 insights 历史做跨板块小结"""

from datetime import datetime
from typing import Dict, Optional, Tuple

from src.storage import load_recent_section_titles

EMPTY_MARKER = "(本次无内容)"


async def run_insights_section(
    rss_md: str,
    gh_md: str,
    hn_md: str,
    config: Dict,
    now: Optional[datetime] = None,
) -> Tuple[str, Optional[str]]:
    cfg = config.get("sections", {}).get("insights", {})
    if not cfg.get("enabled", False):
        return "", None

    from src.llm import generate_trend_insights

    days = config["filter"].get("push_context_days", 5)
    recent = load_recent_section_titles("insights", days)

    sections = {
        "rss": rss_md or EMPTY_MARKER,
        "github": gh_md or EMPTY_MARKER,
        "hackernews": hn_md or EMPTY_MARKER,
    }

    md, err = await generate_trend_insights(sections, recent, config["llm"])
    if err:
        return "", f"generate_trend_insights: {err}"
    return md or "", None
