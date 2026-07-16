"""Remote OPML synchronization for RSS sources."""

import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List
from urllib.parse import urlparse

import aiohttp


DEFAULT_SOURCE_SYNC_CRON = "0 4 * * 0"
DEFAULT_SOURCE_SYNC_TIMEOUT = 30
DEFAULT_SOURCE_SYNC_TITLE = "AI Daily RSS Sources"
DESCRIPTION_ATTR_RE = re.compile(
    r"\sdescription=(['\"]).*?\s(?=(?:xmlUrl|xmlurl)=)",
)
BARE_AMPERSAND_RE = re.compile(r"&(?!#?[A-Za-z0-9]+;)")


@dataclass
class SourceSyncResult:
    updated: bool
    target_path: Path
    source_count: int
    feed_count: int
    failures: List[str] = field(default_factory=list)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _outline_children(element: ET.Element) -> List[ET.Element]:
    return [child for child in list(element) if _local_name(child.tag) == "outline"]


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _repair_opml_attribute_values(opml_content: str) -> str:
    """Escape common invalid characters inside OPML attribute values."""
    opml_content = DESCRIPTION_ATTR_RE.sub(" ", opml_content)
    return BARE_AMPERSAND_RE.sub("&amp;", opml_content)


def parse_opml_feeds(opml_content: str) -> List[Dict]:
    """Parse RSS feed entries from OPML content.

    The parser accepts any outline with an xmlUrl attribute, and inherits a
    category from parent outline folders when a feed does not provide one.
    """
    root = ET.fromstring(_repair_opml_attribute_values(opml_content))
    body = next((child for child in list(root) if _local_name(child.tag) == "body"), root)
    feeds: List[Dict] = []

    def walk(outline: ET.Element, inherited_category: str = ""):
        title = (outline.get("title") or outline.get("text") or "").strip()
        category = (outline.get("category") or "").strip() or inherited_category
        xml_url = (outline.get("xmlUrl") or outline.get("xmlurl") or "").strip()

        if xml_url and _is_http_url(xml_url):
            feeds.append(
                {
                    "title": title or xml_url,
                    "xmlUrl": xml_url,
                    "category": category or "Uncategorized",
                }
            )
        else:
            category = category or title

        for child in _outline_children(outline):
            walk(child, category)

    for outline in _outline_children(body):
        walk(outline)

    return feeds


def dedupe_feeds(feeds: Iterable[Dict]) -> List[Dict]:
    """Dedupe feeds by xmlUrl while preserving first-seen order."""
    seen = set()
    result = []
    for feed in feeds:
        url = str(feed.get("xmlUrl", "") or "").strip()
        if not _is_http_url(url) or url in seen:
            continue
        seen.add(url)
        result.append(
            {
                "title": str(feed.get("title", "") or "").strip() or url,
                "xmlUrl": url,
                "category": str(feed.get("category", "") or "").strip() or "Uncategorized",
            }
        )
    return result


def build_opml(feeds: Iterable[Dict], title: str = DEFAULT_SOURCE_SYNC_TITLE) -> str:
    opml = ET.Element("opml", {"version": "2.0"})
    head = ET.SubElement(opml, "head")
    ET.SubElement(head, "title").text = title
    ET.SubElement(head, "dateModified").text = datetime.now(timezone.utc).isoformat()

    body = ET.SubElement(opml, "body")
    for feed in feeds:
        url = str(feed.get("xmlUrl", "") or "").strip()
        if not _is_http_url(url):
            continue
        feed_title = str(feed.get("title", "") or "").strip() or url
        attrs = {
            "text": feed_title,
            "title": feed_title,
            "type": "rss",
            "xmlUrl": url,
        }
        category = str(feed.get("category", "") or "").strip()
        if category:
            attrs["category"] = category
        ET.SubElement(body, "outline", attrs)

    ET.indent(opml, space="  ")
    xml_body = ET.tostring(opml, encoding="unicode")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_body}\n'


def write_opml(target_path: str, feeds: Iterable[Dict], backup: bool = True) -> Path:
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    if backup and target.exists():
        backup_path = target.with_name(f"{target.name}.bak")
        backup_path.write_bytes(target.read_bytes())

    tmp_path = target.with_name(f"{target.name}.tmp")
    tmp_path.write_text(build_opml(feeds), encoding="utf-8")
    os.replace(tmp_path, target)
    return target


async def _fetch_opml(session: aiohttp.ClientSession, url: str, timeout: int) -> str:
    async with session.get(url, timeout=timeout) as response:
        response.raise_for_status()
        return await response.text()


async def sync_opml_sources(sources_config: Dict) -> SourceSyncResult:
    sync_config = sources_config.get("sync", {})
    urls = []
    for raw_url in sync_config.get("urls", []):
        url = str(raw_url or "").strip()
        if _is_http_url(url):
            urls.append(url)
    target_path = Path(sources_config.get("base_opml", "resources/rss.opml"))

    if not urls:
        return SourceSyncResult(False, target_path, 0, 0, ["sources.sync.urls is empty"])

    timeout = int(sync_config.get("timeout", DEFAULT_SOURCE_SYNC_TIMEOUT))
    backup = bool(sync_config.get("backup", True))

    failures: List[str] = []
    feeds: List[Dict] = []
    headers = {
        "User-Agent": "ai-daily/1.0 (+https://github.com/rss)",
        "Accept": "application/xml,text/xml,text/plain,*/*",
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        for url in urls:
            try:
                content = await _fetch_opml(session, url, timeout)
                parsed_feeds = parse_opml_feeds(content)
                if not parsed_feeds:
                    failures.append(f"{url}: no feeds found")
                    continue
                feeds.extend(parsed_feeds)
            except Exception as e:
                failures.append(f"{url}: {type(e).__name__}: {e}")

    if failures:
        return SourceSyncResult(False, target_path, len(urls), 0, failures)

    feeds = dedupe_feeds(feeds)
    if not feeds:
        return SourceSyncResult(False, target_path, len(urls), 0, ["no feeds after dedupe"])

    written_path = write_opml(str(target_path), feeds, backup=backup)
    return SourceSyncResult(True, written_path, len(urls), len(feeds), [])
