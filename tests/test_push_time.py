from datetime import datetime
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config as config_module
from src.config import get_timezone, initialize_config
from src.storage import extract_push_time, get_push_file, save_push_file


@pytest.fixture(autouse=True)
def initialized_app_config():
    config_module._reset_config_for_tests()
    initialize_config(str(ROOT / "config.yaml"))
    yield
    config_module._reset_config_for_tests()


def _configured_timezone():
    return get_timezone()


def test_push_filename_and_frontmatter_use_the_same_configured_timezone(tmp_path):
    push_time = datetime(2026, 7, 17, 9, 31, 2, tzinfo=_configured_timezone())

    filepath = get_push_file(
        push_time=push_time, data_dir=str(tmp_path), domain="AI"
    )
    assert Path(filepath).name == "push-2026-07-17-09-31-02.md"

    save_push_file(
        filepath,
        "# Digest",
        source_count=1,
        total_entries=1,
        domain="AI",
        push_time=push_time,
    )

    assert f'pushDate: "{push_time.isoformat()}"' in Path(filepath).read_text(
        encoding="utf-8"
    )
    assert extract_push_time(filepath) == push_time
