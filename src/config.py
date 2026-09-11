"""配置模型、加载校验和源管理"""
import fnmatch
import logging
import sys
import xml.etree.ElementTree as ET
from datetime import time, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Annotated, Dict, List, Literal, NoReturn, Optional, Tuple
from urllib.parse import urlparse

import yaml
from croniter import croniter
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = "config.yaml"

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
EnvVarName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
    ),
]
Score = Annotated[int, Field(ge=0, le=100)]
PositiveInt = Annotated[int, Field(gt=0)]


class ConfigModel(BaseModel):
    """配置模型基类：禁止未知字段，允许按字段名或别名赋值。"""

    model_config = ConfigDict(
        populate_by_name=True,
        extra="forbid",
        frozen=True,
    )


def _validate_cron(value: str) -> str:
    if not croniter.is_valid(value):
        raise ValueError(f"无效的 cron 表达式: {value}")
    return value


def _validate_http_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"必须是合法的 http(s) URL: {value}")
    return value


class FilterConfig(ConfigModel):
    """评分筛选阈值"""

    min_score: Score
    hot_threshold: Score
    context_days: PositiveInt
    keep_days: PositiveInt
    push_context_days: PositiveInt
    no_content_marker: NonEmptyStr

    @model_validator(mode="after")
    def check_thresholds(self) -> "FilterConfig":
        if self.hot_threshold < self.min_score:
            raise ValueError(
                f"hot_threshold({self.hot_threshold}) 不能低于 min_score({self.min_score})"
            )
        return self


class DedupeConfig(ConfigModel):
    """去重策略"""

    fuzzy_enabled: bool
    content_threshold: Score


class ScheduleConfig(ConfigModel):
    """抓取与推送调度"""

    fetch_interval_minutes: PositiveInt
    fetch_lookback_minutes: PositiveInt
    push_cron: Tuple[NonEmptyStr, ...] = Field(min_length=1)
    hot_push_block_periods: Tuple[Tuple[time, time], ...]
    timezone_hours: Annotated[int, Field(ge=-12, le=14)]

    @field_validator("push_cron")
    @classmethod
    def check_cron(cls, value: Tuple[str, ...]) -> Tuple[str, ...]:
        return tuple(_validate_cron(cron) for cron in value)

    @field_validator("hot_push_block_periods")
    @classmethod
    def check_periods(
        cls, value: Tuple[Tuple[time, time], ...]
    ) -> Tuple[Tuple[time, time], ...]:
        for start, end in value:
            if start >= end:
                raise ValueError(f"静默时段起始时间必须早于结束时间: {start} - {end}")
        return value

    @model_validator(mode="after")
    def check_lookback_window(self) -> "ScheduleConfig":
        if self.fetch_lookback_minutes < self.fetch_interval_minutes:
            raise ValueError(
                "fetch_lookback_minutes 不能小于 fetch_interval_minutes"
            )
        return self


class FetchConfig(ConfigModel):
    """RSS 抓取并发"""

    max_workers: PositiveInt
    timeout: PositiveInt


class DomainPromptConfig(ConfigModel):
    """单个 domain 的 prompt 路径"""

    score_standard: NonEmptyStr
    digest: NonEmptyStr
    immediate_push: NonEmptyStr


class PromptsConfig(ConfigModel):
    """prompt 路径集合"""

    domains: Dict[NonEmptyStr, DomainPromptConfig] = Field(min_length=1)
    score_batch: NonEmptyStr


class ModelTier(str, Enum):
    """模型档位；成本与能力由低到高，值与配置键一致。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class LLMConfig(ConfigModel):
    """LLM 接口与批处理参数"""

    provider: Literal["openai"]
    models: Dict[ModelTier, NonEmptyStr]
    fallback: Optional[NonEmptyStr] = None
    baseUrl: NonEmptyStr
    apiKeyName: EnvVarName
    max_prompt_chars: PositiveInt
    digest_max_input_tokens: PositiveInt
    max_concurrent_batches: PositiveInt
    max_retries: PositiveInt
    startup_timeout_seconds: PositiveInt
    prompts: PromptsConfig

    @field_validator("baseUrl")
    @classmethod
    def check_base_url(cls, value: str) -> str:
        return _validate_http_url(value).rstrip("/")

    @field_validator("models")
    @classmethod
    def check_all_tiers(
        cls, value: Dict[ModelTier, str]
    ) -> Dict[ModelTier, str]:
        missing = [tier.value for tier in ModelTier if tier not in value]
        if missing:
            raise ValueError(f"缺少模型档位: {', '.join(missing)}")
        return value

    def model_for(self, tier: ModelTier) -> str:
        """返回档位对应的模型名；档位齐全由校验保证。"""
        return self.models[tier]


class WebhookPushConfig(ConfigModel):
    """Webhook 类推送平台（Discord / 飞书）"""

    enabled: bool
    apiKeyName: EnvVarName


class GmailPushConfig(ConfigModel):
    """Gmail SMTP 推送配置；SMTP 端点固定，收件人从环境变量读取。"""

    enabled: bool
    usernameKeyName: EnvVarName
    passwordKeyName: EnvVarName
    toKeyName: EnvVarName
    fromName: NonEmptyStr


class PushConfig(ConfigModel):
    """推送平台集合"""

    discord: WebhookPushConfig
    feishu: WebhookPushConfig
    gmail: GmailPushConfig

    def enabled_platforms(self) -> Dict[str, ConfigModel]:
        """返回已启用的平台，键名与 create_platform() 的注册名一致。"""
        candidates = {
            "discord": self.discord,
            "feishu": self.feishu,
            "gmail": self.gmail,
        }
        return {name: conf for name, conf in candidates.items() if conf.enabled}


class SourceFeedConfig(ConfigModel):
    """自定义补充源"""

    title: NonEmptyStr
    xmlUrl: NonEmptyStr
    category: NonEmptyStr

    @field_validator("xmlUrl")
    @classmethod
    def check_url(cls, value: str) -> str:
        return _validate_http_url(value)


class BlockedFeedConfig(ConfigModel):
    """按 xmlUrl 屏蔽的源"""

    xmlUrl: NonEmptyStr

    @field_validator("xmlUrl")
    @classmethod
    def check_url(cls, value: str) -> str:
        return _validate_http_url(value)


class SourceSyncConfig(ConfigModel):
    """远端 OPML 同步"""

    enabled: bool
    cron: NonEmptyStr
    backup: bool
    timeout: PositiveInt
    title: NonEmptyStr
    urls: Tuple[NonEmptyStr, ...]

    @field_validator("cron")
    @classmethod
    def check_cron(cls, value: str) -> str:
        return _validate_cron(value)

    @field_validator("urls")
    @classmethod
    def check_urls(cls, value: Tuple[str, ...]) -> Tuple[str, ...]:
        return tuple(_validate_http_url(url) for url in value)

    @model_validator(mode="after")
    def check_urls_present_when_enabled(self) -> "SourceSyncConfig":
        if self.enabled and not self.urls:
            raise ValueError("sources.sync.enabled 为 true 时 urls 不能为空")
        return self


class SourcesConfig(ConfigModel):
    """RSS 源：base_opml + add - block - block_domains"""

    base_opml: NonEmptyStr
    sync: SourceSyncConfig
    add: Tuple[SourceFeedConfig, ...]
    block: Tuple[BlockedFeedConfig, ...]
    block_domains: Tuple[NonEmptyStr, ...]


class AppConfig(ConfigModel):
    """应用配置根模型"""

    filter: FilterConfig
    dedupe: DedupeConfig
    schedule: ScheduleConfig
    fetch: FetchConfig
    llm: LLMConfig
    push: PushConfig
    sources: SourcesConfig

    @property
    def timezone(self) -> timezone:
        """推送展示用时区；时区偏移由配置明确提供。"""
        return timezone(timedelta(hours=self.schedule.timezone_hours))


def _exit_with_error(message: str, details: str = "") -> NoReturn:
    """配置不可用时打印原因并直接退出。"""
    logger.error("配置加载失败: %s", message)
    for line in details.splitlines():
        if line.strip():
            logger.error("  %s", line)
    sys.exit(1)


def _format_validation_error(error: ValidationError) -> str:
    """把 Pydantic 校验错误整理成逐行的可读提示。"""
    lines = []
    for item in error.errors():
        location = ".".join(str(part) for part in item["loc"]) or "<root>"
        lines.append(f"{location}: {item['msg']}")
    return "\n".join(lines)


def load_config(config_path: str = DEFAULT_CONFIG_PATH) -> AppConfig:
    """读取并校验 YAML 配置，任何非法配置都直接退出进程。"""
    path = Path(config_path)
    if not path.is_file():
        _exit_with_error(f"配置文件不存在或不是普通文件: {path}")

    try:
        raw = path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
    except (OSError, UnicodeError) as e:
        _exit_with_error(f"配置文件无法读取: {path}", f"{type(e).__name__}: {e}")
    except yaml.YAMLError as e:
        _exit_with_error(f"配置文件不是合法的 YAML: {path}", str(e))

    if not isinstance(data, dict):
        _exit_with_error(f"配置文件顶层必须是键值映射: {path}")

    try:
        return AppConfig.model_validate(data)
    except ValidationError as e:
        _exit_with_error(
            f"配置校验未通过: {path} ({e.error_count()} 处问题)",
            _format_validation_error(e),
        )


_app_config: Optional[AppConfig] = None


def _resolve_path(value: str, config_dir: Path) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = config_dir / candidate
    return candidate.resolve()


def _validate_local_resources(config: AppConfig, config_dir: Path) -> AppConfig:
    """解析并检查配置引用的本地文件，避免启动后才发现路径错误。"""
    prompt_domains = {
        key: item.model_copy(
            update={
                "score_standard": str(_resolve_path(item.score_standard, config_dir)),
                "digest": str(_resolve_path(item.digest, config_dir)),
                "immediate_push": str(_resolve_path(item.immediate_push, config_dir)),
            }
        )
        for key, item in config.llm.prompts.domains.items()
    }
    prompts = config.llm.prompts.model_copy(update={
        "domains": prompt_domains,
        "score_batch": str(_resolve_path(config.llm.prompts.score_batch, config_dir)),
    })
    llm = config.llm.model_copy(update={"prompts": prompts})
    sources = config.sources.model_copy(
        update={"base_opml": str(_resolve_path(config.sources.base_opml, config_dir))}
    )
    resolved = config.model_copy(update={"llm": llm, "sources": sources})

    paths = [
        ("sources.base_opml", resolved.sources.base_opml),
        ("llm.prompts.score_batch", resolved.llm.prompts.score_batch),
    ]
    paths.extend(
        (f"llm.prompts.domains.{key}.{field_name}", getattr(item, field_name))
        for key, item in resolved.llm.prompts.domains.items()
        for field_name in ("score_standard", "digest", "immediate_push")
    )
    for location, raw_path in paths:
        resource = Path(raw_path)
        if not resource.is_file():
            _exit_with_error(f"配置引用的文件不存在: {location} -> {resource}")
        try:
            with resource.open("rb"):
                pass
        except (OSError, UnicodeError) as e:
            _exit_with_error(
                f"配置引用的文件无法读取: {location} -> {resource}",
                f"{type(e).__name__}: {e}",
            )

    return resolved


def initialize_config(config_path: str = DEFAULT_CONFIG_PATH) -> AppConfig:
    """加载、校验一次配置并将其保存为进程级只读配置。"""
    global _app_config

    if _app_config is not None:
        raise RuntimeError("AppConfig 已初始化，不能重复初始化")

    path = Path(config_path)
    config = load_config(config_path)
    config = _validate_local_resources(config, path.resolve().parent)
    _app_config = config
    return _app_config


def get_config() -> AppConfig:
    """返回已初始化的全局配置，不执行任何文件读取。"""
    if _app_config is None:
        raise RuntimeError("AppConfig 尚未初始化；请先调用 initialize_config()")
    return _app_config


def _reset_config_for_tests() -> None:
    """仅供测试隔离全局配置状态使用。"""
    global _app_config
    _app_config = None


def get_timezone() -> timezone:
    """返回已初始化配置的时区；读取信息源统一使用 UTC。"""
    return get_config().timezone


def parse_opml(opml_path: str) -> List[Dict]:
    """解析OPML文件获取订阅源列表"""
    path = Path(opml_path)
    tree = ET.parse(path)
    root = tree.getroot()

    feeds = []
    for outline in root.findall(".//outline[@type='rss']"):
        feeds.append({
            "title": outline.get("title", ""),
            "xmlUrl": outline.get("xmlUrl", ""),
            "category": outline.get("category", "未分类"),
        })

    return feeds


def _is_domain_blocked(url: str, block_domains: Tuple[str, ...]) -> bool:
    """判断 URL 域名是否被屏蔽，支持 *.example.com 通配符。"""
    domain = urlparse(url).netloc.lower()
    if not domain:
        return False

    for pattern in block_domains:
        if pattern.startswith("*."):
            # *.substack.com 匹配 substack.com 和 addyo.substack.com
            suffix = pattern[2:]
            if domain == suffix or domain.endswith("." + suffix):
                return True
        elif fnmatch.fnmatch(domain, pattern):
            return True
    return False


def merge_sources() -> List[Dict]:
    """从全局配置合并 base_opml + add - block - block_domains。"""
    sources = get_config().sources
    all_sources = parse_opml(sources.base_opml) + [
        feed.model_dump() for feed in sources.add
    ]

    block_urls = {item.xmlUrl for item in sources.block}
    seen = set()
    result = []

    for feed in all_sources:
        url = feed.get("xmlUrl", "")
        if not url or url in seen or url in block_urls:
            continue
        if _is_domain_blocked(url, sources.block_domains):
            continue
        seen.add(url)
        result.append(feed)

    return result
