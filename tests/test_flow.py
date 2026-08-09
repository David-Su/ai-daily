import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.config import get_timezone, load_config, merge_sources
from src.fetcher import fetch_all_feeds
from src.llm import (
    RETRYABLE_STATUS_CODES,
    compose_digest,
    generate_immediate_push,
    score_batch,
)
from src.main import collect_entries_for_domain_pushes
from src.processor import html_to_markdown
from src.push import send_to_platforms
from src.push.gmail import GmailPlatform
from src.source_sync import dedupe_feeds, parse_opml_feeds, sync_opml_sources, write_opml
from src.storage import (
    add_entry_dedupe_keys,
    append_entries,
    get_fetch_file,
    get_notify_file,
    is_duplicate_entry,
    find_rapidfuzz_duplicate_entry,
    load_existing_dedupe_keys,
    load_recent_notify_titles,
    read_entries,
    save_fetch_file,
    save_notify_file,
)


# 调试开关：需要访问真实 RSS、LLM 或推送服务时，直接把对应值改成 True。
CONFIG_PATH = ROOT / "config.yaml"
DEBUG_DOMAIN = ""
REAL_SOURCE_LIMIT = 3
REAL_FETCH_MINUTES = 120
RUN_REAL_RSS_FETCH = False
RUN_REAL_LLM_SCORE = False
RUN_REAL_LLM_DIGEST = False
RUN_REAL_PUSH = False


def _config():
    """读取真实 config.yaml，确保测试始终贴着当前配置接口走。"""
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
    """验证 config.yaml 的主接口存在，并检查当前启用 domain 的 prompt 文件都可访问。"""
    config = _config()

    for key in ["sources", "filter", "schedule", "fetch", "llm", "push"]:
        assert key in config

    prompts = config["llm"]["prompts"]
    assert Path(prompts["score_batch"]).exists()

    domains = {item["key"]: item for item in prompts["domain"]["domains"]}
    for domain in prompts["domain"]["activity_domains"]:
        assert Path(domains[domain]["score_standard"]).exists()
        assert Path(domains[domain]["digest"]).exists()
        assert Path(domains[domain]["immediate_push"]).exists()


def test_retryable_llm_status_codes_include_transient_gateway_failures():
    """临时网关故障可重试，配置和认证类错误不应盲目重试。"""
    assert {
        408,
        429,
        500,
        502,
        503,
        504,
        520,
        521,
        522,
        523,
        524,
    }.issubset(RETRYABLE_STATUS_CODES)
    assert RETRYABLE_STATUS_CODES.isdisjoint({400, 401, 403, 404, 413, 422})


@pytest.mark.asyncio
async def test_call_llm_retries_cloudflare_524(monkeypatch):
    """524 后应重试，并使用后续成功响应。"""
    import src.llm as llm_module

    statuses = [524, 200]
    requests = []

    class FakeResponse:
        def __init__(self, status):
            self.status = status

        async def text(self):
            return "timeout"

        async def json(self):
            return {"choices": [{"message": {"content": "retry succeeded"}}]}

    class FakeRequest:
        async def __aenter__(self):
            return FakeResponse(statuses.pop(0))

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        def post(self, *args, **kwargs):
            requests.append((args, kwargs))
            return FakeRequest()

    async def no_wait(_):
        return None

    monkeypatch.setenv("TEST_LLM_API_KEY", "test-key")
    monkeypatch.setitem(
        sys.modules, "aiohttp", SimpleNamespace(ClientSession=FakeSession)
    )
    monkeypatch.setattr(llm_module.asyncio, "sleep", no_wait)

    result = await llm_module.call_llm(
        "test prompt",
        {
            "baseUrl": "https://example.com/v1",
            "apiKeyName": "TEST_LLM_API_KEY",
            "max_retries": 2,
        },
    )

    assert result == "retry succeeded"
    assert len(requests) == 2


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


def test_source_sync_opml_parse_dedupe_and_write(tmp_path):
    """验证远端 OPML 解析、跨源去重和写回后仍能被现有 merge_sources 读取。"""
    opml = """<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0">
  <body>
    <outline text="AI">
      <outline text="Feed A" title="Feed A" type="rss" xmlUrl="https://example.com/a.xml" />
      <outline text="Feed A Duplicate" title="Feed A Duplicate" type="rss" xmlUrl="https://example.com/a.xml" />
    </outline>
    <outline text="Feed B" type="rss" xmlUrl="https://example.com/b.xml" category="Tech" />
  </body>
</opml>
"""
    feeds = dedupe_feeds(parse_opml_feeds(opml))

    assert [feed["xmlUrl"] for feed in feeds] == [
        "https://example.com/a.xml",
        "https://example.com/b.xml",
    ]
    assert feeds[0]["category"] == "AI"

    target = tmp_path / "rss.opml"
    write_opml(str(target), feeds, backup=True)

    sources = merge_sources(
        {
            "base_opml": str(target),
            "add": [{"title": "Manual", "xmlUrl": "https://example.com/manual.xml"}],
            "block": [{"xmlUrl": "https://example.com/b.xml"}],
            "block_domains": [],
        }
    )

    assert [source["xmlUrl"] for source in sources] == [
        "https://example.com/a.xml",
        "https://example.com/manual.xml",
    ]


def test_source_sync_repairs_invalid_opml_attribute_text():
    """上游 OPML 属性里的裸 & 或内嵌 HTML 不应导致整次同步失败。"""
    opml = """<?xml version="1.0" encoding="UTF-8"?>
<opml version="1.0">
  <body>
    <outline text="Business & Economy" title="Business & Economy">
      <outline text="Podcast" title="Podcast" description="Stories with <em data-kind="italic">markup</em>" xmlUrl="https://example.com/feed.xml" type="rss" />
      <outline text="Kitces" title="Kitces" description="Personal Finance News & Advice" xmlUrl="http://feeds.feedblitz.com/kitcesnerdseyeview&x=1" type="rss" />
    </outline>
  </body>
</opml>
"""
    feeds = parse_opml_feeds(opml)

    assert [feed["xmlUrl"] for feed in feeds] == [
        "https://example.com/feed.xml",
        "http://feeds.feedblitz.com/kitcesnerdseyeview&x=1",
    ]
    assert feeds[0]["category"] == "Business & Economy"


@pytest.mark.asyncio
async def test_source_sync_skips_invalid_urls(tmp_path, monkeypatch):
    """同步配置里的非法 URL 直接跳过，只请求合法 http(s) URL。"""
    import src.source_sync as source_sync

    requested_urls = []

    async def fake_fetch_opml(session, url, timeout):
        requested_urls.append(url)
        return """<?xml version="1.0" encoding="UTF-8"?>
<opml version="2.0">
  <body>
    <outline text="Feed A" title="Feed A" type="rss" xmlUrl="https://example.com/a.xml" />
    <outline text="Invalid Feed" title="Invalid Feed" type="rss" xmlUrl="not-a-feed-url" />
  </body>
</opml>
"""

    monkeypatch.setattr(source_sync, "_fetch_opml", fake_fetch_opml)

    result = await sync_opml_sources(
        {
            "base_opml": str(tmp_path / "rss.opml"),
            "sync": {
                "urls": ["", "not-a-url", "ftp://example.com/rss.opml", " https://example.com/rss.opml "],
                "backup": False,
            },
        }
    )

    assert result.updated
    assert result.source_count == 1
    assert requested_urls == ["https://example.com/rss.opml"]
    assert result.feed_count == 1


@pytest.mark.asyncio
async def test_startup_source_sync_runs_when_sync_enabled(monkeypatch):
    """远端 OPML 同步启用后，启动同步固定执行。"""
    import src.main as main_module

    calls = []
    config = {
        "sources": {"sync": {"enabled": True}},
    }

    async def fake_run_source_sync_job(startup_config):
        assert startup_config is config
        calls.append("startup_sync")

    monkeypatch.setattr(main_module, "run_source_sync_job", fake_run_source_sync_job)

    await main_module.run_startup_source_sync_if_needed(config)

    assert calls == ["startup_sync"]


@pytest.mark.asyncio
async def test_main_runs_startup_source_sync_before_loops(monkeypatch):
    """启动同步完成后，才进入抓取/推送/后续定时同步循环。"""
    import src.main as main_module

    calls = []
    config = {
        "sources": {"sync": {"enabled": True}},
        "llm": {},
    }

    async def fake_check_llm_available(llm_config):
        calls.append("llm_check")

    async def fake_run_startup_source_sync_if_needed(startup_config):
        assert startup_config is config
        calls.append("startup_sync")

    async def fake_fetch_loop(loop_config):
        assert loop_config is config
        calls.append("fetch_loop")

    async def fake_push_loop(loop_config):
        assert loop_config is config
        calls.append("push_loop")

    async def fake_source_sync_loop(loop_config):
        assert loop_config is config
        calls.append("source_sync_loop")

    monkeypatch.setattr(main_module, "load_config", lambda: config)
    monkeypatch.setattr(main_module, "check_llm_available", fake_check_llm_available)
    monkeypatch.setattr(
        main_module,
        "run_startup_source_sync_if_needed",
        fake_run_startup_source_sync_if_needed,
    )
    monkeypatch.setattr(main_module, "fetch_loop", fake_fetch_loop)
    monkeypatch.setattr(main_module, "push_loop", fake_push_loop)
    monkeypatch.setattr(main_module, "source_sync_loop", fake_source_sync_loop)

    await main_module.main()

    assert calls.index("startup_sync") < calls.index("fetch_loop")
    assert calls.index("startup_sync") < calls.index("push_loop")
    assert calls.index("startup_sync") < calls.index("source_sync_loop")


@pytest.mark.asyncio
async def test_score_step_with_fake_llm(monkeypatch):
    """用 fake LLM 测评分步骤，确认 LLM JSON 结果能按 link 合并回原始 entries。"""
    import src.llm as llm_module

    config = _config()
    domain = _domain(config)
    entries = _sample_entries(domain)

    async def fake_call_llm(prompt, llm_config, response_format=None):
        assert entries[0]["title"] in prompt
        assert response_format == {"type": "json_object"}
        return json.dumps(
            {
                "items": [
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
            }
        )

    monkeypatch.setattr(llm_module, "call_llm", fake_call_llm)

    scored, errors = await score_batch(entries, config["llm"])

    assert errors == []
    assert scored[0]["score"] == 88
    assert scored[0]["domain"] == domain
    assert scored[1]["summary"] == "Funding summary"


def test_parse_score_response_accepts_legacy_array():
    """评分解析器仍兼容迁移前的顶层数组输出。"""
    import src.llm as llm_module

    response = json.dumps(
        [
            {
                "link": "https://example.com/article",
                "tags": ["release"],
                "domain": "AI",
                "score": 88,
                "summary": "Release summary",
            }
        ]
    )

    assert llm_module._parse_score_response(response)[0]["score"] == 88


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

    monkeypatch.setattr(llm_module, "_count_digest_tokens", lambda prompt: 0)
    monkeypatch.setattr(llm_module, "call_llm", fake_call_llm)

    content = await compose_digest(
        [entries[0]],
        [entries[1]],
        config["llm"],
        recent_push_context="- recent item",
        domain=domain,
    )

    assert content.startswith("# Digest")


@pytest.mark.asyncio
async def test_immediate_push_uses_domain_prompt(monkeypatch):
    """确认即时推送会使用 domain 专属 prompt。"""
    import src.llm as llm_module

    config = _config()
    domains = {
        item["key"]: item for item in config["llm"]["prompts"]["domain"]["domains"]
    }
    domain = "Investment" if "Investment" in domains else _domain(config)
    entries = _sample_entries(domain)
    entries[0]["score"] = 95

    async def fake_call_llm(prompt, llm_config):
        assert entries[0]["title"] in prompt
        assert "recent item" in prompt
        if domain == "Investment":
            assert "不构成投资建议" in prompt
        return "# Immediate\n\n- Ready"

    monkeypatch.setattr(llm_module, "call_llm", fake_call_llm)

    content, error = await generate_immediate_push(
        [entries[0]],
        config["llm"],
        recent_push_context="- recent item",
        domain=domain,
    )

    assert error is None
    assert content.startswith("# Immediate")


def test_notify_titles_are_scoped_by_domain(tmp_path):
    """即时推送历史按 domain 读写，避免 AI 和 Investment 查重上下文混在一起。"""
    ai_file = get_notify_file(data_dir=str(tmp_path), domain="AI")
    investment_file = get_notify_file(data_dir=str(tmp_path), domain="Investment")

    save_notify_file(
        ai_file,
        "# 🚨 AI Daily 快讯 | 2026-05-26\n\n## 🔥 AI model release",
        domain="AI",
    )
    save_notify_file(
        investment_file,
        "# 🚨 AI Daily 投资快讯 | 2026-05-26\n\n## 🔥 Earnings surprise",
        domain="Investment",
    )

    ai_titles = load_recent_notify_titles(1, data_dir=str(tmp_path), domain="AI")
    investment_titles = load_recent_notify_titles(
        1, data_dir=str(tmp_path), domain="Investment"
    )

    assert "AI model release" in ai_titles
    assert "Earnings surprise" not in ai_titles
    assert "Earnings surprise" in investment_titles
    assert "AI model release" not in investment_titles


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


def test_fetch_dedupe_keys_cover_title_content_and_append(tmp_path):
    """验证 fetch 去重能覆盖 link、title、content，并能处理本批次内重复。"""
    now = datetime.now(get_timezone())
    yesterday = now - timedelta(days=1)
    today_file = get_fetch_file(now.date(), str(tmp_path))
    yesterday_file = get_fetch_file(yesterday.date(), str(tmp_path))

    save_fetch_file(
        today_file,
        {"date": now.date().isoformat()},
        [
            {
                "title": "Same Title",
                "link": "https://example.com/original",
                "content": "Same content body",
            }
        ],
    )
    save_fetch_file(
        yesterday_file,
        {"date": yesterday.date().isoformat()},
        [
            {
                "title": "Yesterday Title",
                "link": "https://example.com/yesterday",
                "content": "Yesterday content",
            }
        ],
    )

    keys = load_existing_dedupe_keys(today_file, threshold=24 * 60 + 1)

    assert keys == [
        {
            "link": "https://example.com/original",
            "title": "same title",
            "content": "same content body",
        },
        {
            "link": "https://example.com/yesterday",
            "title": "yesterday title",
            "content": "yesterday content",
        },
    ]
    assert is_duplicate_entry(
        {
            "title": " same   title ",
            "link": "https://example.com/new-title",
            "content": "Fresh body",
        },
        keys,
    )
    assert is_duplicate_entry(
        {
            "title": "Fresh title",
            "link": "https://example.com/new-content",
            "content": "same content body",
        },
        keys,
    )
    assert is_duplicate_entry(
        {
            "title": "Fresh title",
            "link": "https://example.com/yesterday",
            "content": "Fresh body",
        },
        keys,
    )

    fresh = {
        "title": "Fresh Title",
        "link": "https://example.com/fresh",
        "content": "Fresh body",
    }
    assert not is_duplicate_entry(fresh, keys)
    add_entry_dedupe_keys(fresh, keys)
    assert is_duplicate_entry(
        {
            "title": "Another title",
            "link": "https://example.com/another",
            "content": "fresh body",
        },
        keys,
    )

    append_entries(
        today_file,
        [
            {
                "title": "Same Title",
                "link": "https://example.com/duplicate-title",
                "content": "Different body",
            },
            {
                "title": "Unique Title",
                "link": "https://example.com/unique",
                "content": "Unique body",
            },
            {
                "title": "Another Unique Title",
                "link": "https://example.com/another-unique",
                "content": "unique body",
            },
        ],
    )

    entries = read_entries(today_file)
    assert [entry["title"] for entry in entries] == ["Same Title", "Unique Title"]


def test_rapidfuzz_content_dedupe_detects_near_duplicate():
    keys = [
        {
            "link": "",
            "title": "",
            "content": "google released a new local ai model with faster inference and better tool use.",
        }
    ]

    assert find_rapidfuzz_duplicate_entry(
        {
            "title": "Different title",
            "link": "https://example.com/new",
            "content": "Google released a new local AI model with faster inference and better tool use!",
        },
        keys,
    )


def test_push_message_can_be_built_from_config(monkeypatch):
    """基于 config.yaml 的 Gmail 配置构建邮件消息，只验证格式，不发送真实邮件。"""
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
