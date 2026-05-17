"""测试新增的 sentinel 切片与 section-aware 读取"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from storage import extract_section


class TestExtractSection:
    def test_extract_section_with_sentinel(self):
        md = (
            "intro\n"
            "<!-- SECTION:rss BEGIN -->\n"
            "RSS body\n"
            "<!-- SECTION:rss END -->\n"
            "\n"
            "<!-- SECTION:github BEGIN -->\n"
            "GH body\n"
            "<!-- SECTION:github END -->\n"
        )
        assert extract_section(md, "rss").strip() == "RSS body"
        assert extract_section(md, "github").strip() == "GH body"
        assert extract_section(md, "hackernews") == ""

    def test_extract_section_legacy_file_rss(self):
        legacy = "# AI Daily\n### 1️⃣ foo\n### 2️⃣ bar\n"
        assert extract_section(legacy, "rss") == legacy

    def test_extract_section_legacy_file_non_rss(self):
        legacy = "# AI Daily\n### 1️⃣ foo\n"
        assert extract_section(legacy, "github") == ""
        assert extract_section(legacy, "hackernews") == ""
        assert extract_section(legacy, "insights") == ""

    def test_extract_section_missing_end_marker(self):
        broken = "<!-- SECTION:rss BEGIN -->\ncontent only\n"
        assert extract_section(broken, "rss") == ""


from datetime import date, datetime, timedelta
from storage import load_recent_section_titles, save_push_file


class TestLoadRecentSectionTitles:
    def test_returns_empty_when_dir_missing(self, tmp_path):
        assert load_recent_section_titles("rss", 3, str(tmp_path / "missing")) == ""

    def test_returns_empty_when_no_files(self, tmp_path):
        assert load_recent_section_titles("rss", 3, str(tmp_path)) == ""

    def test_extracts_only_target_section_titles(self, tmp_path):
        from config import get_timezone

        today = datetime.now(get_timezone()).date()
        push_file = tmp_path / f"push-{today.isoformat()}-08-00-00.md"
        push_file.write_text(
            f'---\npushDate: "{datetime.now(get_timezone()).isoformat()}"\n---\n\n'
            "<!-- SECTION:rss BEGIN -->\n"
            "### 1️⃣ RSS Title One\n"
            "### 2️⃣ RSS Title Two\n"
            "<!-- SECTION:rss END -->\n\n"
            "<!-- SECTION:github BEGIN -->\n"
            "### GH Repo Title\n"
            "<!-- SECTION:github END -->\n",
            encoding="utf-8",
        )
        rss_titles = load_recent_section_titles("rss", 3, str(tmp_path))
        assert "RSS Title One" in rss_titles
        assert "RSS Title Two" in rss_titles
        assert "GH Repo Title" not in rss_titles

        gh_titles = load_recent_section_titles("github", 3, str(tmp_path))
        assert "GH Repo Title" in gh_titles
        assert "RSS Title One" not in gh_titles
