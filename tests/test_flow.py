import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.config import get_timezone, load_config, merge_sources
from src.fetcher import fetch_all_feeds
from src.llm import compose_digest, score_batch
from src.main import collect_entries_for_domain_pushes
from src.processor import html_to_markdown
from src.push import send_to_platforms
from src.push.gmail import GmailPlatform
from src.storage import get_fetch_file, save_fetch_file


# 调试开关：需要访问真实 RSS、LLM 或推送服务时，直接把对应值改成 True。
CONFIG_PATH = ROOT / "config.json"
DEBUG_DOMAIN = ""
REAL_SOURCE_LIMIT = 3
REAL_FETCH_MINUTES = 120
RUN_REAL_RSS_FETCH = False
RUN_REAL_LLM_SCORE = False
RUN_REAL_LLM_DIGEST = False
RUN_REAL_PUSH = False


def _config():
    """读取真实 config.json，确保测试始终贴着当前配置接口走。"""
    return load_config(str(CONFIG_PATH))


def _domain(config):
    """选择测试用 domain；默认取配置里的第一个活跃 domain，可用 DEBUG_DOMAIN 手动指定。"""
    if DEBUG_DOMAIN:
        return DEBUG_DOMAIN
    return config["llm"]["prompts"]["domain"]["activity_domains"][0]


def _sample_entries(domain):
    """构造两条最小新闻样本，用于测试评分、digest 和推送筛选流程。"""
    now = datetime.now(timezone.utc).isoformat()
    return [
        {
            "title": "Sample model release",
            "link": "https://example.com/model-release",
            "published": now,
            "fetched_at": now,
            "source": "Example Feed",
            "content": "A new model was released with useful benchmark details.",
            "tags": [],
            "domain": domain,
            "score": 0,
            "summary": "",
        },
        {
            "title": "Sample funding news",
            "link": "https://example.com/funding-news",
            "published": now,
            "fetched_at": now,
            "source": "Example Feed",
            "content": "A company raised funding for AI infrastructure.",
            "tags": [],
            "domain": domain,
            "score": 0,
            "summary": "",
        },
    ]


def test_config_interface_and_prompt_files():
    """验证 config.json 的主接口存在，并检查当前启用 domain 的 prompt 文件都可访问。"""
    config = _config()

    for key in ["sources", "filter", "schedule", "fetch", "llm", "push"]:
        assert key in config

    prompts = config["llm"]["prompts"]
    assert Path(prompts["score_batch"]).exists()
    assert Path(prompts["immediate_push"]).exists()

    domains = {item["key"]: item for item in prompts["domain"]["domains"]}
    for domain in prompts["domain"]["activity_domains"]:
        assert Path(domains[domain]["score_standard"]).exists()
        assert Path(domains[domain]["digest"]).exists()


def test_sources_merge_and_html_processing():
    """验证 RSS 源合并、去重、屏蔽配置，以及 HTML 到 Markdown 的基础转换。"""
    config = _config()
    sources = merge_sources(config["sources"])

    assert sources
    urls = [source["xmlUrl"] for source in sources]
    assert len(urls) == len(set(urls))

    blocked_urls = {item["xmlUrl"] for item in config["sources"].get("block", [])}
    assert blocked_urls.isdisjoint(urls)

    markdown = html_to_markdown(
        '<p>Hello <a href="more.html">more</a></p><img src="img.png">',
        "https://example.com/articles/start",
    )
    assert "[more](https://example.com/articles/more.html)" in markdown
    assert "![](https://example.com/articles/img.png)" in markdown


@pytest.mark.asyncio
async def test_score_step_with_fake_llm(monkeypatch):
    """用 fake LLM 测评分步骤，确认 LLM JSON 结果能按 link 合并回原始 entries。"""
    import src.llm as llm_module

    config = _config()
    domain = _domain(config)
    entries = _sample_entries(domain)

    async def fake_call_llm(prompt, llm_config):
        assert entries[0]["title"] in prompt
        return json.dumps(
            [
                {
                    "link": entries[0]["link"],
                    "tags": ["release"],
                    "domain": domain,
                    "score": 88,
                    "summary": "Release summary",
                },
                {
                    "link": entries[1]["link"],
                    "tags": ["funding"],
                    "domain": domain,
                    "score": 71,
                    "summary": "Funding summary",
                },
            ]
        )

    monkeypatch.setattr(llm_module, "call_llm", fake_call_llm)

    scored, errors = await score_batch(entries, config["llm"])

    assert errors == []
    assert scored[0]["score"] == 88
    assert scored[0]["domain"] == domain
    assert scored[1]["summary"] == "Funding summary"


@pytest.mark.asyncio
async def test_digest_step_with_fake_llm(monkeypatch):
    """用 fake LLM 测 digest 步骤，确认 domain prompt、待推送内容和近期上下文会进入调用链。"""
    import src.llm as llm_module

    config = _config()
    domain = _domain(config)
    entries = _sample_entries(domain)
    entries[0]["score"] = 88
    entries[0]["summary"] = "Release summary"

    async def fake_call_llm(prompt, llm_config):
        assert entries[0]["title"] in prompt
        assert "recent item" in prompt
        return "# Digest\n\n- Ready"

    monkeypatch.setattr(llm_module, "call_llm", fake_call_llm)

    content = await compose_digest(
        [entries[0]],
        [entries[1]],
        config["llm"],
        recent_push_context="- recent item",
        domain=domain,
    )

    assert content.startswith("# Digest")


def test_storage_and_push_candidate_selection(tmp_path):
    """写入临时 fetch 文件后，验证主流程能按 domain、分数和时间筛出待推送与上下文。"""
    config = _config()
    domain = _domain(config)
    tz = get_timezone(config)
    now = datetime.now(tz)
    old_time = now - timedelta(days=2)

    entries = [
        {
            "title": "Fresh item",
            "link": "https://example.com/fresh",
            "published": now.isoformat(),
            "fetched_at": now.isoformat(),
            "source": "Example",
            "content": "Fresh content",
            "tags": ["fresh"],
            "domain": domain,
            "score": 80,
            "summary": "Fresh summary",
        },
        {
            "title": "Context item",
            "link": "https://example.com/context",
            "published": old_time.isoformat(),
            "fetched_at": old_time.isoformat(),
            "source": "Example",
            "content": "Context content",
            "tags": ["context"],
            "domain": domain,
            "score": 75,
            "summary": "Context summary",
        },
        {
            "title": "Low score item",
            "link": "https://example.com/low",
            "published": now.isoformat(),
            "fetched_at": now.isoformat(),
            "source": "Example",
            "content": "Low score content",
            "tags": [],
            "domain": domain,
            "score": 10,
            "summary": "",
        },
    ]

    fetch_file = get_fetch_file(now.date(), str(tmp_path))
    save_fetch_file(fetch_file, {"date": now.date().isoformat()}, entries)

    groups = collect_entries_for_domain_pushes(
        context_days=1,
        min_score=config["filter"]["min_score"],
        data_dir=str(tmp_path),
        config=config,
    )

    assert [item["title"] for item in groups[domain]["to_push"]] == ["Fresh item"]
    assert [item["title"] for item in groups[domain]["context"]] == ["Context item"]


def test_push_message_can_be_built_from_config(monkeypatch):
    """基于 config.json 的 Gmail 配置构建邮件消息，只验证格式，不发送真实邮件。"""
    config = _config()
    gmail_config = dict(config["push"]["gmail"])
    gmail_config["enabled"] = True
    gmail_config["to"] = "receiver@example.com"

    monkeypatch.setenv(gmail_config["usernameKeyName"], "sender@example.com")
    monkeypatch.setenv(gmail_config["passwordKeyName"], "app-password")

    platform = GmailPlatform(gmail_config)
    message = platform._build_message("# Test\n\nHello", "AI Daily Test")

    assert platform.validate_config(gmail_config)
    assert message["Subject"] == "AI Daily Test"
    assert message["To"] == "receiver@example.com"
    assert "sender@example.com" in message["From"]


@pytest.mark.skipif(not RUN_REAL_RSS_FETCH, reason="real RSS debug is off")
@pytest.mark.asyncio
async def test_debug_real_rss_fetch_step():
    """真实 RSS 抓取调试；默认跳过，打开 RUN_REAL_RSS_FETCH 后才访问网络。"""
    config = _config()
    sources = merge_sources(config["sources"])[:REAL_SOURCE_LIMIT]
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=REAL_FETCH_MINUTES)

    entries = await fetch_all_feeds(
        sources,
        cutoff,
        max_workers=config["fetch"]["max_workers"],
        timeout=config["fetch"]["timeout"],
    )

    for entry in entries:
        entry["content"] = html_to_markdown(entry.get("content", ""), entry["link"])

    print(f"Fetched {len(entries)} entries from {len(sources)} sources")
    assert isinstance(entries, list)


@pytest.mark.skipif(not RUN_REAL_LLM_SCORE, reason="real LLM score debug is off")
@pytest.mark.asyncio
async def test_debug_real_llm_score_step():
    """真实 LLM 评分调试；默认跳过，打开 RUN_REAL_LLM_SCORE 后才调用接口。"""
    config = _config()
    scored, errors = await score_batch(_sample_entries(_domain(config)), config["llm"])

    print(json.dumps(scored, ensure_ascii=False, indent=2))
    assert scored
    assert errors == []


@pytest.mark.skipif(not RUN_REAL_LLM_DIGEST, reason="real LLM digest debug is off")
@pytest.mark.asyncio
async def test_debug_real_llm_digest_step():
    """真实 LLM digest 调试；默认跳过，打开 RUN_REAL_LLM_DIGEST 后才调用接口。"""
    config = _config()
    domain = _domain(config)
    entries = _sample_entries(domain)
    entries[0]["score"] = 88
    entries[0]["summary"] = "Release summary"

    content = await compose_digest([entries[0]], [entries[1]], config["llm"], domain=domain)

    print(content)
    assert content.strip()


@pytest.mark.skipif(not RUN_REAL_PUSH, reason="real push debug is off")
@pytest.mark.asyncio
async def test_debug_real_push_step():
    """真实推送调试；默认跳过，打开 RUN_REAL_PUSH 后会发送测试消息。"""
    config = _config()

    await send_to_platforms(
        "# AI Daily Test\n\nThis is a manual push test.",
        config["push"],
        title="AI Daily Test",
    )
