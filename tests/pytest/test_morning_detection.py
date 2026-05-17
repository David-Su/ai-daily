"""测试早报判定:cron + 容差"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.main import is_morning_push


TZ = timezone(timedelta(hours=8))


def _cfg(cron, tol=5):
    return {
        "schedule": {
            "morning_cron": cron,
            "morning_match_tolerance_minutes": tol,
            "timezone_hours": 8,
        }
    }


def test_returns_false_when_no_morning_cron_configured():
    assert is_morning_push(datetime(2026, 5, 17, 8, 0, tzinfo=TZ), {"schedule": {}}) is False


def test_match_exact_time():
    cfg = _cfg("0 8 * * *")
    now = datetime(2026, 5, 17, 8, 0, tzinfo=TZ)
    assert is_morning_push(now, cfg) is True


def test_match_within_tolerance():
    cfg = _cfg("0 8 * * *", tol=5)
    assert is_morning_push(datetime(2026, 5, 17, 8, 4, tzinfo=TZ), cfg) is True
    assert is_morning_push(datetime(2026, 5, 17, 7, 56, tzinfo=TZ), cfg) is True


def test_outside_tolerance():
    cfg = _cfg("0 8 * * *", tol=5)
    assert is_morning_push(datetime(2026, 5, 17, 8, 6, tzinfo=TZ), cfg) is False
    assert is_morning_push(datetime(2026, 5, 17, 9, 0, tzinfo=TZ), cfg) is False


def test_evening_time_not_morning():
    cfg = _cfg("0 8 * * *", tol=5)
    assert is_morning_push(datetime(2026, 5, 17, 17, 0, tzinfo=TZ), cfg) is False
