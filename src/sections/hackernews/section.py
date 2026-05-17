"""HN 板块入口。流程:首页 → 轻 LLM 选 K → enrich → 最终 LLM 行文"""

from datetime import datetime
from typing import Dict, Optional, Tuple

from src.sections.hackernews.frontpage_scraper import (
    fetch_frontpage,
    parse_frontpage_html,
)
from src.sections.hackernews.item_enricher import enrich_stories


async def run_hackernews_section(
    config: Dict, now: Optional[datetime] = None
) -> Tuple[str, Optional[str]]:
    cfg = config.get("sections", {}).get("hackernews", {})
    if not cfg.get("enabled", False):
        return "", None

    # 延迟 import (Task 16 提供这两个函数)
    from src.llm import select_ai_related_hn, summarize_hackernews

    timeout = cfg.get("request_timeout", 10)
    select_k = cfg.get("select_k", 1)
    top_comments = cfg.get("top_comments", 20)
    comment_max_chars = cfg.get("comment_max_chars", 500)
    link_content_max_chars = cfg.get("link_content_max_chars", 3000)
    algolia_base = cfg.get("algolia_base", "https://hn.algolia.com/api/v1")

    # 1. 抓首页
    try:
        html = await fetch_frontpage(timeout=timeout)
    except Exception as e:
        return "", f"HN 首页抓取失败: {e}"

    front = parse_frontpage_html(html)
    if not front:
        return "", None

    # 2. 轻 LLM 初筛
    selected_ids, select_err = await select_ai_related_hn(front, k=select_k, config=config["llm"])
    if select_err:
        return "", f"select_ai_related_hn: {select_err}"
    if not selected_ids:
        return "", None

    selected = [s for s in front if s["id"] in set(selected_ids)]
    if not selected:
        return "", None

    # 3. enrich
    enriched, enrich_errors = await enrich_stories(
        selected,
        top_comments=top_comments,
        comment_max_chars=comment_max_chars,
        link_content_max_chars=link_content_max_chars,
        algolia_base=algolia_base,
        timeout=timeout,
    )
    for e in enrich_errors:
        print(f"⚠️ HN enrich: {e}")
    if not enriched:
        return "", None

    # 4. LLM 总结
    md, err = await summarize_hackernews(enriched, config["llm"])
    if err:
        return "", f"summarize_hackernews: {err}"
    return md or "", None
