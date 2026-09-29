import json
import logging
import re
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config as config_module
from src.config import initialize_config, load_config, merge_sources
from src.llm import _build_batch_prompt, _parse_score_response


CONFIG_PATH = ROOT / "config.yaml"
BLOCKED_DATELESS_FEEDS = {
    "http://engineering.khanacademy.org/rss",
    "https://browser.engineering/rss.xml",
}


@pytest.fixture
def initialized_config():
    config_module._reset_config_for_tests()
    config = initialize_config(str(CONFIG_PATH))
    yield config
    config_module._reset_config_for_tests()


def test_load_config_requires_rejected_ttl_hours(tmp_path, caplog):
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    raw["dedupe"].pop("rejected_ttl_hours", None)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

    with caplog.at_level(logging.ERROR):
        with pytest.raises(SystemExit) as exc_info:
            load_config(str(path))

    assert exc_info.value.code == 1
    assert "dedupe.rejected_ttl_hours: Field required" in caplog.text


@pytest.mark.parametrize(
    "value, error_message",
    [
        (0, "Input should be greater than 0"),
        (-1, "Input should be greater than 0"),
        (1.5, "Input should be a valid integer"),
    ],
    ids=["zero", "negative", "fractional"],
)
def test_load_config_rejects_invalid_rejected_ttl_hours(
    tmp_path, caplog, value, error_message
):
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    raw["dedupe"]["rejected_ttl_hours"] = value
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

    with caplog.at_level(logging.ERROR):
        with pytest.raises(SystemExit) as exc_info:
            load_config(str(path))

    assert exc_info.value.code == 1
    assert f"dedupe.rejected_ttl_hours: {error_message}" in caplog.text


def test_real_config_loads_scoring_limits(initialized_config):
    assert initialized_config.dedupe.rejected_ttl_hours == 24
    assert initialized_config.llm.max_prompt_chars == 40000


def test_rendered_score_prompt_has_compact_ordered_json_example(initialized_config):
    prompt = _build_batch_prompt(initialized_config.llm, [{"id": 1}])
    example = re.search(r'(?m)^\{"items":.*\}$', prompt)

    assert example is not None
    parsed = json.loads(example.group())
    assert list(parsed) == ["items"]
    assert list(parsed["items"][0]) == ["id", "domain", "score", "tags", "summary"]
    assert example.group() == json.dumps(
        parsed, ensure_ascii=False, separators=(",", ":")
    )


def test_rendered_score_prompt_declares_json_only_output_once(initialized_config):
    prompt = _build_batch_prompt(initialized_config.llm, [{"id": 1}])
    instructions = [
        line for line in prompt.splitlines() if re.search(r"JSON\s*\u5bf9\u8c61", line)
    ]

    assert len(instructions) == 1
    assert "\u53ea\u8f93\u51fa" in instructions[0]


def test_parse_score_response_accepts_formatted_and_compact_json():
    items = [
        {
            "id": 1,
            "domain": "AI",
            "score": 95,
            "tags": ["Model"],
            "summary": "A new model was released.",
        }
    ]
    response = {"items": items}
    formatted = json.dumps(response, indent=2)
    compact = json.dumps(response, separators=(",", ":"))

    assert _parse_score_response(formatted) == items
    assert _parse_score_response(compact) == items


def test_real_source_merge_excludes_dateless_feeds(initialized_config):
    blocked_urls = {item.xmlUrl for item in initialized_config.sources.block}
    merged_urls = {source["xmlUrl"] for source in merge_sources()}

    assert BLOCKED_DATELESS_FEEDS.issubset(blocked_urls)
    assert BLOCKED_DATELESS_FEEDS.isdisjoint(merged_urls)
    assert "https://openai.com/news/rss.xml" in merged_urls
