import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import config as config_module
from src.config import initialize_config
from src.llm import _build_batch_prompt, _get_push_prompt_entries, get_config
from src.processor import clean_for_llm


def setup_module():
    config_module._reset_config_for_tests()
    initialize_config(str(ROOT / "config.yaml"))


def teardown_module():
    config_module._reset_config_for_tests()


def test_clean_removes_images_keeps_text():
    text = "海信发布新品。\n\n![](https://img.ithome.com/a.jpg)\n\n功率达330W。"
    cleaned = clean_for_llm(text)
    assert "![" not in cleaned
    assert "img.ithome.com" not in cleaned
    assert "海信发布新品。" in cleaned
    assert "功率达330W。" in cleaned


def test_clean_removes_shopping_links_keeps_facts():
    text = "75英寸888分区。\n\n[![](https://img/a.png)京东直达链接](https://u.jd.com/4GvXqqe)"
    cleaned = clean_for_llm(text)
    assert "u.jd.com" not in cleaned
    assert "![" not in cleaned
    assert "75英寸888分区。" in cleaned


def test_clean_collapses_blank_lines():
    assert clean_for_llm("A\n\n\n\nB") == "A\n\nB"
    assert clean_for_llm("") == ""
    assert clean_for_llm(None) == ""


def test_clean_is_idempotent():
    text = "A\n\n![](https://x/y.png)\n\n\nB [s](https://u.jd.com/z)"
    assert clean_for_llm(clean_for_llm(text)) == clean_for_llm(text)


def test_push_prompt_entries_cleaned_and_original_untouched():
    entries = [
        {
            "title": "t",
            "link": "https://www.ithome.com/1/006/417.htm",
            "content": "A\n\n![](https://img.ithome.com/a.jpg)\n\nB",
            "summary": "摘要",
        }
    ]
    result = _get_push_prompt_entries(entries)
    assert "![" not in result[0]["content"]
    assert "A" in result[0]["content"] and "B" in result[0]["content"]
    assert "summary" not in result[0]
    assert result[0]["link"] == "https://www.ithome.com/1/006/417.htm"
    assert "![" in entries[0]["content"]


def test_score_batch_prompt_has_no_image_markup():
    entries = [
        {
            "id": 0,
            "title": "t",
            "source": "IT之家",
            "published": "2026-09-23T19:31:31+08:00",
            "content": "A\n\n![](https://img.ithome.com/a.jpg)\n\nB",
        }
    ]
    prompt = _build_batch_prompt(get_config().llm, entries)
    assert "![" not in prompt
    assert '"content":"A\\n\\nB"' in prompt
