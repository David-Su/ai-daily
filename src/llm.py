"""LLM模块 - 评分和汇总"""

import asyncio
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.config import LLMConfig, ModelTier, get_config


# 仅重试临时性 HTTP 故障；认证、请求参数和上下文超限等 4xx 错误需要人工修复。
RETRYABLE_STATUS_CODES = frozenset(
    {
        408,  # Request Timeout
        429,  # Too Many Requests
        500,  # Internal Server Error
        502,  # Bad Gateway
        503,  # Service Unavailable
        504,  # Gateway Timeout
        520,  # Cloudflare: Unknown Error
        521,  # Cloudflare: Web Server Is Down
        522,  # Cloudflare: Connection Timed Out
        523,  # Cloudflare: Origin Is Unreachable
        524,  # Cloudflare: A Timeout Occurred
    }
)


def compact_json(data) -> str:
    """Serialize JSON for LLM prompts without whitespace overhead."""
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _count_digest_tokens(prompt: str) -> int:
    """使用 tiktoken 统计完整 digest prompt 的 token 数。"""
    import tiktoken

    return len(tiktoken.get_encoding("o200k_base").encode(prompt))


def _digest_entry_removal_key(entry: Dict) -> Tuple[str, float]:
    """按最早发布时间、最低分数确定超额时的移除顺序。"""
    published = str(entry.get("published") or entry.get("fetched_at") or "")
    try:
        score = float(entry.get("score") or 0)
    except (TypeError, ValueError):
        score = 0
    return published, score


def load_prompt(prompt_path: str, **kwargs) -> str:
    """加载提示词模板并填充变量"""
    path = Path(prompt_path)
    if not path.exists():
        raise FileNotFoundError(f"提示词文件不存在: {prompt_path}")

    with open(path, "r", encoding="utf-8") as f:
        template = f.read()

    # 先把模板中的 {{ 和 }} 替换成占位符，避免与format冲突
    template = template.replace("{{", "\x00LEFT_BRACE\x00").replace(
        "}}", "\x00RIGHT_BRACE\x00"
    )

    # 替换变量
    for key, value in kwargs.items():
        template = template.replace(f"{{{key}}}", str(value))

    # 恢复 {{ 和 }}
    template = template.replace("\x00LEFT_BRACE\x00", "{").replace(
        "\x00RIGHT_BRACE\x00", "}"
    )

    return template


async def call_llm(
    prompt: str,
    tier: ModelTier,
    response_format: Optional[Dict] = None,
    allow_fallback: bool = True,
) -> str:
    """调用LLM API - 统一使用OpenAI兼容接口

    Args:
        prompt: 完整提示词
        tier: 模型档位；调用方必须显式声明，失败不会跨档回落
        response_format: 可选的结构化输出配置
        allow_fallback: 主模型失败后是否改用 llm.fallback 再请求一次
    """
    config = get_config().llm
    model = config.model_for(tier)
    fallback = config.fallback
    base_url = config.baseUrl
    max_retries = config.max_retries

    api_key = os.environ.get(config.apiKeyName)
    if not api_key:
        raise ValueError(f"未设置{config.apiKeyName}环境变量")

    import aiohttp

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
    }
    if response_format is not None:
        payload["response_format"] = response_format

    url = f"{base_url}/chat/completions"

    last_error = None

    def generate_error(msg):
        return RuntimeError(f"LLM API错误: {msg}")

    async def request_once(session, model_name: str):
        request_payload = {**payload, "model": model_name}
        async with session.post(url, headers=headers, json=request_payload) as resp:
            if resp.status != 200:
                text = await resp.text()
                return None, generate_error(f"{resp.status} - {text}"), resp.status
            data = await resp.json()
            return data["choices"][0]["message"]["content"], None, resp.status

    async with aiohttp.ClientSession() as session:
        for attempt in range(max_retries):
            content, last_error, status = await request_once(session, model)
            if content is not None:
                return content
            if status in RETRYABLE_STATUS_CODES and attempt < max_retries - 1:
                print(f"⚠️ LLM API错误{status}: 第{attempt + 1}次重试")
                await asyncio.sleep(2 ** attempt)
                continue
            break

        if allow_fallback and fallback and fallback != model:
            content, fallback_error, _ = await request_once(session, fallback)
            if content is not None:
                print(
                    f"⚠️ LLM 已切换到兜底模型 | 档位: {tier.value}, "
                    f"主模型: {model}, 兜底: {fallback}"
                )
                return content
            if fallback_error is not None:
                last_error = fallback_error

    raise last_error


async def _check_tier_available(tier: ModelTier, timeout_seconds: int) -> None:
    """探测单个档位；失败或超时都抛出带档位名的错误。"""
    try:
        response = await asyncio.wait_for(
            call_llm("Reply with OK only.", tier, allow_fallback=False),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError as exc:
        raise RuntimeError(f"{tier.value} 档超时({timeout_seconds}s)") from exc
    except Exception as exc:
        raise RuntimeError(f"{tier.value} 档调用失败: {exc}") from exc

    if not response.strip():
        raise RuntimeError(f"{tier.value} 档返回空响应")


async def check_llm_available() -> None:
    """启动时检查所有档位可用性；任一档不可用即抛错中断启动。"""
    timeout_seconds = get_config().llm.startup_timeout_seconds

    results = await asyncio.gather(
        *(_check_tier_available(tier, timeout_seconds) for tier in ModelTier),
        return_exceptions=True,
    )

    failures = [str(r) for r in results if isinstance(r, BaseException)]
    if failures:
        raise RuntimeError("LLM可用性检查失败: " + "; ".join(failures))


def _build_batch_prompt(config: LLMConfig, entries: List[Dict]) -> str:
    """构建批量评分prompt"""
    # 构建评分标准
    score_standard = _build_score_standard(config)
    # 构建领域列表
    domain_list = _build_domain_list(config)

    # 构建entries JSON列表（只包含必要字段）
    entries_for_llm = [
        {
            "id": e["id"],
            "title": e.get("title", "无标题"),
            "source": e.get("source", "未知来源"),
            "published": e.get("published", ""),
            "content": e.get("content", "")[:2000],  # 限制内容长度
        }
        for e in entries
    ]
    entries_json = compact_json(entries_for_llm)

    return load_prompt(
        config.prompts.score_batch,
        entries_json=entries_json,
        score_standard=score_standard,
        domain_list=domain_list,
    )


def _build_domain_list(config: LLMConfig) -> str:
    return compact_json(list(config.prompts.domains))


def _build_score_standard(config: LLMConfig) -> str:
    """Build enabled domain score standards from prompt files."""
    standards = []

    for domain, prompts in config.prompts.domains.items():
        standard_content = load_prompt(prompts.score_standard).strip()
        standards.append(f"### {domain}\n{standard_content}")

    return "\n".join(standards)


def _parse_score_response(response: str) -> List[Dict]:
    """解析评分响应，兼容 json_object 模式和旧数组格式。"""
    text = response.strip()

    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]

    if text.endswith("```"):
        text = text[:-3]

    text = text.strip()

    parsed = None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        for pattern in (r"\{.*\}", r"\[.*\]"):
            match = re.search(pattern, text, re.DOTALL)
            if not match:
                continue
            try:
                parsed = json.loads(match.group())
                break
            except json.JSONDecodeError:
                continue

    if parsed is None:
        print(f"无法从响应中解析JSON: {response}")
        raise ValueError(f"无法从响应中解析JSON: {response[:200]}...")

    if isinstance(parsed, list):
        return parsed

    if isinstance(parsed, dict):
        for key in ("items", "results", "data", "scores"):
            if isinstance(parsed.get(key), list):
                return parsed[key]

        list_values = [v for v in parsed.values() if isinstance(v, list)]
        if len(list_values) == 1:
            return list_values[0]

    print(f"无法从响应中提取评分数组: {response}")
    raise ValueError(f"无法从响应中提取评分数组: {response[:200]}...")


def _split_entries_for_batch(
        entries: List[Dict],
        max_prompt_chars: int,
        prompt_chars: int,
) -> List[List[Dict]]:
    """将entries分成多个批次，每批不超过max_prompt_chars字符"""
    if not entries:
        return []

    batches = []
    current_batch = []
    current_chars = 0

    # 预留prompt模板和JSON包装的空间
    overhead = prompt_chars + 500

    for index, entry in enumerate(entries):
        new_entry = {
            **entry,
            "id": index,
        }
        # 估算该entry在JSON中的字符数
        entry_chars = len(
            json.dumps(
                {
                    "id": new_entry.get("id", 0),
                    "title": new_entry.get("title", ""),
                    "source": new_entry.get("source", ""),
                    "published": new_entry.get("published", ""),
                    "content": new_entry.get("content", "")[:2000],
                },
                ensure_ascii=False,
            )
        )

        # 如果当前批次加上这个entry会超出限制，且当前批次不为空，则创建新批次
        if current_chars + entry_chars + overhead > max_prompt_chars and current_batch:
            batches.append(current_batch)
            current_batch = [new_entry]
            current_chars = entry_chars
        else:
            current_batch.append(new_entry)
            current_chars += entry_chars

    # 添加最后一个批次
    if current_batch:
        batches.append(current_batch)

    return batches


def _reconcile_batch_results(
    entries: List[Dict], results: List[Dict], batch_index: int
) -> Tuple[List[Dict], List[str]]:
    """对单批评分结果按 link 过滤，保留可回收结果"""
    entry_links = {entry.get("link") for entry in entries if entry.get("link")}
    error_links = set()
    matched_results = []

    for item in results:
        if not isinstance(item, dict):
            continue
        link = item.get("link")
        if link in entry_links:
            matched_results.append(item)
        else:
            error_links.add(link)

    errors = []
    if error_links:
        error_message = (
            f"批次{batch_index + 1} 评分结果异常:"
            f"生成不存在的链接{error_links}"
        )
        errors.append(error_message)

    return matched_results, errors


async def _score_single_batch(
    entries: List[Dict], config: LLMConfig, batch_index: int = 0
) -> List[Dict]:
    """对单批entries进行评分"""
    # 从config获取批量评分提示词路径

    prompt = _build_batch_prompt(config, entries)

    try:
        response = await call_llm(
            prompt, ModelTier.LOW, response_format={"type": "json_object"}
        )
        results = _parse_score_response(response)

        if not isinstance(results, list):
            raise ValueError(f"LLM返回的不是数组: {type(results)}")

        return results

    except Exception as e:
        error_message = f"批次{batch_index + 1} 评分失败: {e}"
        print(f"⚠️ {error_message}")
        return []


async def score_batch(entries: List[Dict]) -> List[Dict]:
    """
    批量评分 - 智能分批处理

    根据数据量自动决定分批策略：
    - 小批量：一次性发送
    - 大批量：分成多个批次并行处理
    """
    config = get_config().llm

    if not entries:
        return []

    # 获取分批配置
    max_prompt_chars = config.max_prompt_chars
    max_concurrent_batches = config.max_concurrent_batches
    # 分批
    prompt_chars = len(_build_batch_prompt(config, []))
    batches = _split_entries_for_batch(entries, max_prompt_chars, prompt_chars)
    print(f"📦 分成 {len(batches)} 个批次评分 (共 {len(entries)} 条)")

    # 如果只有一批，直接处理
    if len(batches) == 1:
        scores = await _score_single_batch(batches[0], config, batch_index=0)
        return _merge_scores(entries, scores)

    # 多批并行处理（限制并发数）
    semaphore = asyncio.Semaphore(max_concurrent_batches)

    async def score_with_limit(batch_index: int, batch: List[Dict]):
        async with semaphore:
            return await _score_single_batch(batch, config, batch_index=batch_index)

    # 并发处理所有批次
    batch_tasks = [
        score_with_limit(batch_index, batch)
        for batch_index, batch in enumerate(batches)
    ]
    batch_results = await asyncio.gather(*batch_tasks)

    # 合并所有评分结果
    all_scores = []
    for scores in batch_results:
        all_scores.extend(scores)

    return _merge_scores(entries, all_scores)


def _merge_scores(entries: List[Dict], scores: List[Dict]) -> List[Dict]:
    """将评分结果合并到原始entries中"""
    # 构建 id:score 映射
    score_map = {
        _id: s
        for s in scores
        if (_id := s.get("id")) is not None and isinstance(_id, int)
    }

    merged = []
    exclude_link = []
    for index, entry in enumerate(entries):
        link = entry.get("link")
        score_data = score_map.get(index)
        if not score_data:
            exclude_link.append(link)
            continue
        # 确保 score 为整数类型
        score_value = score_data.get("score", entry.get("score"))
        if isinstance(score_value, str):
            try:
                score_value = int(score_value)
            except (ValueError, TypeError):
                score_value = 0

        merged.append(
            {
                **entry,
                "tags": score_data.get("tags", entry.get("tags", [])),
                "domain": score_data.get("domain", entry.get("domain", "")),
                "score": score_value,
                "summary": score_data.get("summary", entry.get("summary", "")),
            }
        )
    if exclude_link:
        print(f"🧹 评分过滤链接共 {len(exclude_link)} 条 | 无效 id : {len(scores) - len(score_map)} 条 : ")
        print("\n".join(exclude_link))
    return merged


def _get_push_prompt_entries(entries: List[Dict]) -> List[Dict]:
    """正文为空，用summary内容替代，同时移除summary"""
    result = []
    for entry in entries:
        content = entry.get("content", "")
        summary = entry.get("summary")
        new_entry = {**entry}
        if not content:
            new_entry["content"] = summary
        new_entry.pop("summary", None)
        result.append(new_entry)
    return result


async def generate_immediate_push(
    entries: List[Dict],
    recent_push_context: str = "",
    domain: str = None,
) -> Tuple[str, Optional[str]]:
    """生成即时推送内容

    Args:
        entries: 原始entries列表（调用方已筛选好高分条目）
        recent_push_context: 近期推送上下文，用于去重
        domain: 当前快讯所属 domain，用于选择 domain 专属即时推送 prompt
    """
    config = get_config().llm
    try:
        prompts = config.prompts.domains.get((domain or "").strip())
        if not prompts:
            raise ValueError(f"未配置 domain={domain or ''} 的 immediate_push prompt")

        new_entries = _get_push_prompt_entries(entries)

        # 直接使用传入的entries，转为JSON格式传给prompt
        prompt = load_prompt(
            prompts.immediate_push,
            count=len(new_entries),
            entries=compact_json(new_entries),
            recent_push_context=recent_push_context,
        )

        return await call_llm(prompt, ModelTier.LOW), None
    except Exception as e:
        error_message = f"生成即时推送失败: {e}"
        print(f"⚠️ {error_message}")
        return "", error_message


async def compose_digest(
    entries: List[Dict],
    context: List[Dict],
    recent_push_context: str = "",
    domain: str = None,
) -> str:
    """生成定时汇总推送内容

    Args:
        entries: 原始entries列表
        context: 历史碎片化信息（用于去重参考），只保留 title, published, tags, summary, source
        recent_push_context: 近期汇总推送上下文，用于去重
        domain: 当前汇总所属 domain，用于选择 domain 专属 digest prompt
    """
    config = get_config().llm
    prompts = config.prompts.domains.get((domain or "").strip())
    if not prompts:
        raise ValueError(f"未配置 domain={domain or ''} 的 digest prompt")

    # context 只保留必要字段，拼接成字符串
    context_text = []
    for c in context:
        tags_str = ", ".join(c.get("tags", [])) if c.get("tags") else ""
        context_text.append(
            f"[score: {c.get('score', 0)}] title:{c.get('title', '')}\n"
            f"published: {c.get('published', '')}\n"
            f"tags: {tags_str}\n"
            f"source: {c.get('source', '')}\n"
            f"summary: {c.get('summary', '')}"
        )

    # 裁剪字符数
    digest_entries = list(entries)
    original_entry_count = len(digest_entries)
    max_input_tokens = config.digest_max_input_tokens

    while True:
        new_entries = _get_push_prompt_entries(digest_entries)
        prompt = load_prompt(
            prompts.digest,
            count=len(new_entries),
            entries=compact_json(new_entries),
            context="\n\n".join(context_text),
            recent_push_context=recent_push_context,
            date=datetime.now().strftime("%Y-%m-%d"),
        )

        input_tokens = _count_digest_tokens(prompt)
        if input_tokens <= max_input_tokens:
            break

        if not digest_entries:
            raise ValueError(
                f"digest prompt 超过 token 上限: {max_input_tokens}"
            )

        digest_entries.remove(
            min(digest_entries, key=_digest_entry_removal_key)
        )

    removed_entry_count = original_entry_count - len(digest_entries)
    if removed_entry_count:
        print(
            f"✂️ [{domain or 'digest'}] token裁剪 | 上限: {max_input_tokens}, "
            f"最终: {input_tokens}, 保留: {len(digest_entries)} 条, "
            f"移除: {removed_entry_count} 条"
        )

    try:
        return await call_llm(prompt, ModelTier.MEDIUM)
    except Exception:
        raise
