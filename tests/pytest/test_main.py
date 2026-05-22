"""主程序逻辑测试"""

import json
import pytest
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, AsyncMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from main import (
    now_local,
    parse_time_to_local,
    calculate_push_times,
    collect_entries_for_domain_pushes,
    run_push_job,
    main as run_main,
)


class TestNowLocal:
    """测试获取本地时间"""

    def test_now_local_with_config(self, sample_config):
        result = now_local(sample_config)
        assert isinstance(result, datetime)
        assert result.tzinfo is not None

    def test_now_local_without_config(self):
        result = now_local()
        assert isinstance(result, datetime)


class TestParseTimeToLocal:
    """测试时间解析"""

    def test_parse_iso_format(self, sample_config):
        result = parse_time_to_local("2024-01-15T10:30:00+00:00", sample_config)
        assert result is not None
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    def test_parse_with_z_suffix(self, sample_config):
        result = parse_time_to_local("2024-01-15T10:30:00Z", sample_config)
        assert result is not None
        assert result.year == 2024

    def test_parse_invalid_format(self, sample_config):
        result = parse_time_to_local("not-a-date", sample_config)
        assert result is None

    def test_parse_none(self, sample_config):
        result = parse_time_to_local("", sample_config)
        assert result is None


class TestCalculatePushTimes:
    """测试推送时间计算"""

    def test_calculate_single_cron(self, sample_config):
        times = calculate_push_times(["30 8 * * *"], config=sample_config)
        assert len(times) == 1
        assert times[0].hour == 8
        assert times[0].minute == 30

    def test_calculate_multiple_crons(self, sample_config):
        times = calculate_push_times(["0 8 * * *", "0 17 * * *"], config=sample_config)
        assert len(times) == 2
        hours = [t.hour for t in times]
        assert 8 in hours
        assert 17 in hours

    def test_calculate_with_offset(self, sample_config):
        times = calculate_push_times(["0 8 * * *"], offset_days=1, config=sample_config)
        assert len(times) == 1
        expected_date = (datetime.now(timezone.utc) + timedelta(days=1)).date()
        assert times[0].date() == expected_date

    def test_calculate_invalid_cron(self, sample_config):
        times = calculate_push_times(["invalid cron"], config=sample_config)
        assert times == []


class TestCollectEntriesForDomainPushes:
    """测试按 domain 收集推送条目"""

    def test_collect_entries_for_domain_pushes(self, temp_dir, sample_config):
        from src.config import get_timezone

        tz = get_timezone(sample_config)
        now = datetime.now(tz)
        data = {
            "meta": {"date": now.date().isoformat()},
            "entries": [
                {
                    "title": "AI Entry",
                    "link": "https://example.com/ai",
                    "domain": "AI",
                    "score": 85,
                    "fetched_at": now.isoformat(),
                },
                {
                    "title": "Investment Entry",
                    "link": "https://example.com/investment",
                    "domain": "投资",
                    "score": 88,
                    "fetched_at": now.isoformat(),
                },
            ],
        }

        fetch_file = temp_dir / f"fetch-{now.date().isoformat()}.json"
        fetch_file.write_text(json.dumps(data), encoding="utf-8")

        result = collect_entries_for_domain_pushes(
            context_days=2,
            min_score=60,
            data_dir=str(temp_dir),
            config=sample_config,
        )

        assert set(result.keys()) == {"AI", "投资"}
        assert result["AI"]["to_push"][0]["title"] == "AI Entry"
        assert result["投资"]["to_push"][0]["title"] == "Investment Entry"

    def test_collect_domain_pushes_uses_domain_cutoff(self, temp_dir, sample_config):
        from src.config import get_timezone

        tz = get_timezone(sample_config)
        now = datetime.now(tz)
        last_ai_push = now - timedelta(hours=1)
        older_entry_time = now - timedelta(hours=2)

        data = {
            "meta": {"date": now.date().isoformat()},
            "entries": [
                {
                    "title": "Old AI Entry",
                    "link": "https://example.com/ai-old",
                    "domain": "AI",
                    "score": 85,
                    "fetched_at": older_entry_time.isoformat(),
                },
                {
                    "title": "Old Investment Entry",
                    "link": "https://example.com/investment-old",
                    "domain": "投资",
                    "score": 88,
                    "fetched_at": older_entry_time.isoformat(),
                },
            ],
        }

        fetch_file = temp_dir / f"fetch-{now.date().isoformat()}.json"
        fetch_file.write_text(json.dumps(data), encoding="utf-8")
        ai_push_dir = temp_dir / "push" / "AI"
        ai_push_dir.mkdir(parents=True)
        ai_push_file = ai_push_dir / (
            f"push-{last_ai_push.strftime('%Y-%m-%d-%H-%M-%S')}.md"
        )
        ai_push_file.write_text(
            '---\ndomain: "AI"\n---\n\n# AI push',
            encoding="utf-8",
        )

        result = collect_entries_for_domain_pushes(
            context_days=2,
            min_score=60,
            data_dir=str(temp_dir),
            config=sample_config,
        )

        assert result["AI"]["to_push"] == []
        assert result["AI"]["context"][0]["title"] == "Old AI Entry"
        assert result["投资"]["to_push"][0]["title"] == "Old Investment Entry"


class TestMainStartup:
    """测试主程序启动流程"""

    @pytest.mark.asyncio
    async def test_run_push_job_pushes_each_domain_separately(
        self, sample_config, temp_dir
    ):
        domain_pushes = {
            "AI": {
                "to_push": [{"title": "AI Entry", "domain": "AI", "score": 90}],
                "context": [],
                "last_push_time": None,
                "push_cutoff": datetime.now(timezone.utc),
            },
            "投资": {
                "to_push": [{"title": "Investment Entry", "domain": "投资", "score": 92}],
                "context": [],
                "last_push_time": None,
                "push_cutoff": datetime.now(timezone.utc),
            },
        }

        def push_file_for_domain(domain=None):
            return str(temp_dir / "push" / domain / "push-test.md")

        with patch(
            "main.collect_entries_for_domain_pushes", return_value=domain_pushes
        ), patch("main.load_recent_push_titles", return_value=""), patch(
            "main.compose_digest", new_callable=AsyncMock
        ) as mock_compose, patch(
            "main.send_to_platforms", new_callable=AsyncMock
        ) as mock_send, patch(
            "main.get_push_file", side_effect=push_file_for_domain
        ) as mock_get_push_file, patch(
            "main.save_push_file"
        ) as mock_save_push_file:
            mock_compose.side_effect = ["# AI Digest", "# Investment Digest"]

            await run_push_job(sample_config)

        compose_domains = [
            call.kwargs["domain"] for call in mock_compose.await_args_list
        ]
        sent_titles = [call.kwargs["title"] for call in mock_send.await_args_list]
        saved_domains = [
            call.kwargs["domain"] for call in mock_save_push_file.call_args_list
        ]

        assert compose_domains == ["AI", "投资"]
        assert sent_titles == ["AI 资讯汇总", "投资 资讯汇总"]
        assert saved_domains == ["AI", "投资"]
        assert mock_get_push_file.call_count == 2

    @pytest.mark.asyncio
    async def test_main_checks_llm_before_starting_loops(self, sample_config):
        with patch("main.load_config", return_value=sample_config), patch(
            "main.check_llm_available", new_callable=AsyncMock
        ) as mock_check, patch(
            "main.fetch_loop", new_callable=AsyncMock
        ) as mock_fetch_loop, patch(
            "main.push_loop", new_callable=AsyncMock
        ) as mock_push_loop:
            await run_main()

        mock_check.assert_awaited_once_with(sample_config["llm"])
        mock_fetch_loop.assert_awaited_once_with(sample_config)
        mock_push_loop.assert_awaited_once_with(sample_config)

    @pytest.mark.asyncio
    async def test_main_exits_when_llm_health_check_fails(self, sample_config):
        with patch("main.load_config", return_value=sample_config), patch(
            "main.check_llm_available", new_callable=AsyncMock
        ) as mock_check, patch(
            "main.fetch_loop", new_callable=AsyncMock
        ) as mock_fetch_loop, patch(
            "main.push_loop", new_callable=AsyncMock
        ) as mock_push_loop:
            mock_check.side_effect = RuntimeError("health failed")

            await run_main()

        mock_check.assert_awaited_once_with(sample_config["llm"])
        mock_fetch_loop.assert_not_called()
        mock_push_loop.assert_not_called()
