import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config as config_module
from src import llm as llm_module
from src import main as main_module
from src.storage import read_entries, save_fetch_file


ROUND_START = datetime(2026, 9, 27, 4, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def isolated_app_config():
    config_module._reset_config_for_tests()
    config = config_module.initialize_config(str(ROOT / "config.yaml"))
    config = config.model_copy(
        update={
            "dedupe": config.dedupe.model_copy(
                update={"fuzzy_enabled": True, "rejected_ttl_hours": 24}
            ),
            "filter": config.filter.model_copy(update={"hot_threshold": 100}),
        }
    )
    config_module._app_config = config
    yield config
    config_module._reset_config_for_tests()


@pytest.fixture(autouse=True)
def cleared_rejections():
    main_module._rejected_links.clear()
    yield
    main_module._rejected_links.clear()


@pytest.fixture
def clock(monkeypatch):
    clock_state = SimpleNamespace(now=ROUND_START)

    class ControlledDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return clock_state.now.replace(tzinfo=None)
            return clock_state.now.astimezone(tz)

    monkeypatch.setattr(main_module, "datetime", ControlledDatetime)
    return clock_state


def _entry(name, *, title=None, content=None):
    return {
        "title": title or f"Article {name}",
        "link": f"https://example.com/{name}",
        "published": ROUND_START.isoformat(),
        "source": "Example",
        "content": content or f"Distinct article body for {name}",
    }


def _scored(entry, domain="AI"):
    return {
        **entry,
        "domain": domain,
        "score": 80,
        "summary": "Scored summary",
        "tags": [],
    }


def _install_fetch(monkeypatch, tmp_path, entries):
    fetch_file = tmp_path / "fetch.json"

    async def fake_fetch_all_feeds(_sources, _cutoff):
        return [dict(entry) for entry in entries]

    monkeypatch.setattr(
        main_module,
        "merge_sources",
        lambda: [{"xmlUrl": "https://example.com/feed"}],
    )
    monkeypatch.setattr(main_module, "fetch_all_feeds", fake_fetch_all_feeds)
    monkeypatch.setattr(main_module, "get_fetch_file", lambda: str(fetch_file))
    monkeypatch.setattr(main_module, "cleanup_old_files", lambda **_kwargs: None)
    return fetch_file


@pytest.mark.asyncio
async def test_valid_rejections_skip_scoring_before_exact_and_fuzzy_dedupe(
    tmp_path, monkeypatch, clock, capsys
):
    reference = _entry("stored-exact", title="Existing article")
    fuzzy_body = (
        "Google released a new local AI model with faster inference and better tool use."
    )
    fuzzy_reference = _entry("stored-fuzzy", content=fuzzy_body)
    rejected_exact = _entry("rejected-exact", title=reference["title"])
    rejected_fuzzy = _entry("rejected-fuzzy", content=fuzzy_body[:-1] + "!")
    rejected_unique = _entry("rejected-unique", content="Previously rejected subject")
    exact_duplicate = _entry("exact-duplicate", title=reference["title"])
    fuzzy_duplicate = _entry("fuzzy-duplicate", content=fuzzy_body[:-1] + "?")
    fresh = _entry("fresh", content="A completely unrelated economics report")
    rejected_at = ROUND_START - timedelta(hours=3)
    main_module._rejected_links.update(
        {entry["link"]: rejected_at for entry in (
            rejected_exact, rejected_fuzzy, rejected_unique
        )}
    )
    fetch_file = _install_fetch(
        monkeypatch,
        tmp_path,
        [
            rejected_exact,
            rejected_fuzzy,
            rejected_unique,
            exact_duplicate,
            fuzzy_duplicate,
            fresh,
        ],
    )
    save_fetch_file(str(fetch_file), {"date": "2026-09-27"}, [reference, fuzzy_reference])

    async def fake_score_batch(entries):
        assert [entry["link"] for entry in entries] == [fresh["link"]]
        return [_scored(entries[0])], set()

    monkeypatch.setattr(main_module, "score_batch", fake_score_batch)

    await main_module.run_fetch_job()

    assert [entry["link"] for entry in read_entries(str(fetch_file))] == [
        reference["link"], fuzzy_reference["link"], fresh["link"]
    ]
    assert main_module._rejected_links[rejected_unique["link"]] == rejected_at
    output = capsys.readouterr().out
    assert "\u88ab\u62d2\u8df3\u8fc7\uff1a3 \u6761" in output
    assert "\u7cbe\u786e\u53bb\u91cd\uff1a1 \u6761" in output
    assert "\u6a21\u7cca\u53bb\u91cd\uff1a1 \u6761" in output


@pytest.mark.asyncio
@pytest.mark.parametrize("ttl_hours", [2, 24])
async def test_rejection_at_ttl_boundary_is_rescored_and_timestamp_is_completion(
    tmp_path, monkeypatch, clock, isolated_app_config, ttl_hours
):
    entry = _entry("expired", content="An article that was rejected yesterday")
    completed_at = ROUND_START + timedelta(minutes=30)
    config_module._app_config = isolated_app_config.model_copy(
        update={
            "dedupe": isolated_app_config.dedupe.model_copy(
                update={"rejected_ttl_hours": ttl_hours}
            )
        }
    )
    main_module._rejected_links[entry["link"]] = ROUND_START - timedelta(hours=ttl_hours)
    fetch_file = _install_fetch(monkeypatch, tmp_path, [entry])

    async def fake_score_batch(entries):
        assert entry["link"] not in main_module._rejected_links
        assert [item["link"] for item in entries] == [entry["link"]]
        clock.now = completed_at
        return [], {entry["link"]}

    monkeypatch.setattr(main_module, "score_batch", fake_score_batch)

    await main_module.run_fetch_job()

    assert main_module._rejected_links == {entry["link"]: completed_at}
    assert read_entries(str(fetch_file)) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("empty_sources", [True, False])
async def test_expired_rejections_are_pruned_even_when_round_has_no_entries(
    tmp_path, monkeypatch, clock, empty_sources
):
    boundary_link = "https://example.com/at-boundary"
    expired_link = "https://example.com/expired"
    valid_link = "https://example.com/valid"
    main_module._rejected_links.update(
        {
            boundary_link: ROUND_START - timedelta(hours=24),
            expired_link: ROUND_START - timedelta(hours=25),
            valid_link: ROUND_START - timedelta(hours=23),
        }
    )
    _install_fetch(monkeypatch, tmp_path, [])
    if empty_sources:
        monkeypatch.setattr(main_module, "merge_sources", lambda: [])

    await main_module.run_fetch_job()

    assert main_module._rejected_links == {
        valid_link: ROUND_START - timedelta(hours=23)
    }


@pytest.mark.asyncio
async def test_successful_omissions_and_unknown_domains_are_rejected_only_in_memory(
    tmp_path, monkeypatch, clock
):
    entries = [
        _entry("accepted", content="A major model release with improved reasoning"),
        _entry("unknown", content="A local sports competition and its final scores"),
        _entry("omitted", content="A recipe for a seasonal fruit tart"),
    ]
    fetch_file = _install_fetch(monkeypatch, tmp_path, entries)

    async def fake_call_llm(_prompt, _tier, response_format=None):
        assert response_format == {"type": "json_object"}
        return json.dumps(
            {
                "items": [
                    {"id": 0, "domain": "AI", "score": 80, "tags": [], "summary": "Accepted"},
                    {"id": 1, "domain": "Unknown", "score": 80, "tags": [], "summary": "Unknown"},
                ]
            }
        )

    monkeypatch.setattr(llm_module, "call_llm", fake_call_llm)

    await main_module.run_fetch_job()

    assert main_module._rejected_links == {
        entries[1]["link"]: ROUND_START,
        entries[2]["link"]: ROUND_START,
    }
    payload = json.loads(fetch_file.read_text(encoding="utf-8"))
    assert set(payload) == {"meta", "entries"}
    assert set(payload["meta"]) == {"date"}
    assert [entry["link"] for entry in payload["entries"]] == [entries[0]["link"]]
    assert set(payload["entries"][0]) == {
        "title", "link", "published", "source", "content", "domain",
        "score", "summary", "tags", "fetched_at",
    }
    assert list(tmp_path.iterdir()) == [fetch_file]


@pytest.mark.asyncio
async def test_failed_scoring_batch_is_retried_on_next_fetch_round(
    tmp_path, monkeypatch, clock
):
    entry = _entry("retry", content="A new financial market regulation announcement")
    fetch_file = _install_fetch(monkeypatch, tmp_path, [entry])
    attempts = []

    async def fake_call_llm(prompt, _tier, response_format=None):
        assert entry["title"] in prompt
        attempts.append(prompt)
        if len(attempts) == 1:
            raise asyncio.TimeoutError()
        return json.dumps(
            {"items": [
                {"id": 0, "domain": "AI", "score": 80, "tags": [], "summary": "Retried"}
            ]}
        )

    monkeypatch.setattr(llm_module, "call_llm", fake_call_llm)

    await main_module.run_fetch_job()

    assert main_module._rejected_links == {}
    assert read_entries(str(fetch_file)) == []

    clock.now += timedelta(hours=2)
    await main_module.run_fetch_job()

    assert len(attempts) == 2
    assert [item["link"] for item in read_entries(str(fetch_file))] == [entry["link"]]
    assert main_module._rejected_links == {}


@pytest.mark.asyncio
async def test_push_timeout_type_appears_in_log_and_notification(
    monkeypatch, clock, capsys
):
    entry = _scored(_entry("digest"))
    notifications = []
    monkeypatch.setattr(
        main_module,
        "collect_entries_for_domain_pushes",
        lambda: {"AI": {"to_push": [entry], "context": [], "last_push_time": None}},
    )
    monkeypatch.setattr(main_module, "load_recent_push_titles", lambda **_kwargs: "")

    async def fake_compose_digest(*_args, **_kwargs):
        raise asyncio.TimeoutError()

    async def fake_send_to_platforms(content, title):
        notifications.append((content, title))

    monkeypatch.setattr(main_module, "compose_digest", fake_compose_digest)
    monkeypatch.setattr(main_module, "send_to_platforms", fake_send_to_platforms)

    await main_module.run_push_job()

    output = capsys.readouterr().out
    assert "\u751f\u6210\u6c47\u603b\u63a8\u9001\u5931\u8d25: TimeoutError: " in output
    assert len(notifications) == 1
    assert "stage: compose_digest:AI" in notifications[0][0]
    assert "- TimeoutError: " in notifications[0][0]
