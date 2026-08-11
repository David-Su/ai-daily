"""AI每日资讯推送系统 - 主程序"""

import asyncio
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

# 加载 .env 文件
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from croniter import croniter

from src.config import get_config, get_timezone, initialize_config, merge_sources
from src.fetcher import fetch_all_feeds
from src.llm import (
    check_llm_available,
    compose_digest,
    generate_immediate_push,
    score_batch,
)
from src.processor import html_to_markdown
from src.push import send_to_platforms
from src.source_sync import sync_opml_sources
from src.storage import (
    add_entry_dedupe_keys,
    append_entries,
    cleanup_old_files,
    extract_push_time,
    get_fetch_file,
    get_last_push_file,
    get_notify_file,
    get_push_file,
    is_duplicate_entry,
    find_rapidfuzz_duplicate_entry,
    load_existing_dedupe_keys,
    load_recent_notify_titles,
    load_recent_push_titles,
    load_recent_push_titles_for_immediate_push,
    read_entries,
    save_notify_file,
    save_push_file,
)

DEFAULT_PUSH_DOMAIN = "未分类"


def is_immediate_push_forbidden() -> bool:
    config = get_config()
    curr_time = now_local().time()
    return any(
        start <= curr_time < end
        for start, end in config.schedule.hot_push_block_periods
    )


def format_fuzzy_dedupe_details(pairs: list[dict]) -> str:
    """把模糊去重明细格式化为便于阅读的表格。"""
    if not pairs:
        return ""

    headers = ("排除链接", "比对链接")
    rows = [(str(pair.get("new", "")), str(pair.get("old", ""))) for pair in pairs]
    widths = [
        max(len(header), *(len(row[index]) for row in rows))
        for index, header in enumerate(headers)
    ]

    def format_row(row: tuple[str, str]) -> str:
        return "  ".join(value.ljust(widths[index]) for index, value in enumerate(row))

    return "\n".join((format_row(headers), *(format_row(row) for row in rows)))


async def notify_llm_errors(stage: str, errors: List[str]):
    """发送简单的 LLM 异常通知"""
    if not errors:
        return

    lines = [
        "## LLM异常",
        "",
        f"stage: {stage}",
        f"time: {now_local().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]
    lines.extend(f"- {error}" for error in errors)

    try:
        print(f"⚠️ LLM异常 推送到平台")
        content = "\n".join(lines)
        # print(content)
        await send_to_platforms("\n".join(lines), title="AI Daily 异常警报")
    except Exception as e:
        print(f"⚠️ LLM异常通知发送失败: {e}")


def now_local() -> datetime:
    """获取配置时区的当前时间"""
    return datetime.now(get_timezone())


def parse_time_to_local(time_str: str) -> Optional[datetime]:
    """解析时间字符串为配置时区的datetime"""
    try:
        dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        return dt.astimezone(get_timezone())
    except (ValueError, TypeError):
        return None


def normalize_entry_domain(entry: Dict) -> str:
    """读取 entry 的 domain，缺失时归到未分类。"""
    domain = str(entry.get("domain") or "").strip()
    return domain or DEFAULT_PUSH_DOMAIN


def get_domain_order() -> List[str]:
    """从配置读取 domain 顺序，用于稳定推送顺序。"""
    config = get_config()
    domain_config = config.llm.prompts.domain
    configured_domains = [item.key for item in domain_config.domains]

    order = []
    for domain in [
        *domain_config.activity_domains,
        *configured_domains,
        DEFAULT_PUSH_DOMAIN,
    ]:
        if domain not in order:
            order.append(domain)
    return order


def sort_domains(domains: List[str]) -> List[str]:
    """按配置顺序排列 domain，其余 domain 放在最后。"""
    order = get_domain_order()
    order_index = {domain: index for index, domain in enumerate(order)}
    return sorted(domains, key=lambda d: (order_index.get(d, len(order_index)), d))


def calculate_push_times(cron_list: List[str], offset_days: int = 0) -> List[datetime]:
    base_date = datetime.now(get_timezone()).date() + timedelta(days=offset_days)
    times = []
    for cron in cron_list:
        try:
            minute, hour, _, _, _ = cron.split()
            t = datetime.combine(
                base_date,
                datetime.strptime(f"{hour}:{minute}", "%H:%M").time(),
                tzinfo=get_timezone(),
            )
            times.append(t)
        except ValueError:
            continue
    return sorted(times)


def collect_entries_for_domain_pushes(data_dir: str = "news-data") -> Dict[str, Dict]:
    """按 domain 收集推送条目，返回每个 domain 独立的待推送与上下文。"""
    config = get_config()
    context_days = config.filter.context_days
    min_score = config.filter.min_score
    tz = get_timezone()
    now = datetime.now(tz)
    today = now.date()

    all_entries = []
    for i in range(context_days):
        d = today - timedelta(days=i)
        fetch_file = get_fetch_file(d, data_dir)
        all_entries.extend(read_entries(fetch_file))

    print(
        f"📋 收集总条目: {len(all_entries)} 条 , context_days: {context_days}, min_score:{min_score}"
    )

    qualified_entries = [e for e in all_entries if (e.get("score") or 0) >= min_score]
    print(f"📋 过滤后条目: {len(qualified_entries)} 条 ")

    # 获取{domain:domain对应的entries}
    grouped_entries: Dict[str, List[Dict]] = {}
    for entry in qualified_entries:
        domain = entry.get("domain")
        if not domain or domain.strip() == "": continue
        grouped_entries.setdefault(domain, []).append(entry)

    domain_pushes = {}
    past_24h = now - timedelta(hours=24)
    for domain, entries in grouped_entries.items():
        last_push_file = get_last_push_file(data_dir=data_dir, domain=domain)
        last_push_time = extract_push_time(last_push_file) if last_push_file else None
        push_cutoff = (
            last_push_time if last_push_time and last_push_time > past_24h else past_24h
        )

        to_push = []
        context = []
        for entry in entries:
            entry_time = parse_time_to_local(entry.get("fetched_at", ""))
            if entry_time and entry_time > push_cutoff:
                to_push.append(entry)
            else:
                context.append(entry)

        context = sorted(context, key=lambda x: x.get("score", 0), reverse=True)[:50]
        domain_pushes[domain] = {
            "to_push": to_push,
            "context": context,
            "last_push_time": last_push_time,
            "push_cutoff": push_cutoff,
        }

    return domain_pushes


async def run_fetch_job():
    config = get_config()
    print(f"\n{'=' * 50}")
    print(f"🔄 Fetch Job | {now_local().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 50}")

    interval = config.schedule.fetch_interval_minutes
    lookback = config.schedule.fetch_lookback_minutes
    threshold = lookback + interval
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=lookback)

    sources = merge_sources()
    print(f"📂 共 {len(sources)} 个订阅源")

    if not sources:
        print("⚠️ 没有可用的订阅源")
        return

    entries = await fetch_all_feeds(sources, cutoff)
    print(f"📥 抓取到 {len(entries)} 条原始消息")

    if not entries:
        return

    for entry in entries:
        entry["content"] = html_to_markdown(
            entry.get("content", ""), entry.get("link", "")
        )

    fetch_file = get_fetch_file()

    existing_keys = load_existing_dedupe_keys(fetch_file, threshold)

    fuzzy_enabled = config.dedupe.fuzzy_enabled
    content_threshold = config.dedupe.content_threshold

    existing_count = len(existing_keys)
    exact_duplicate_count = 0
    rapidfuzz_duplicate_pair: list[dict[str, str]] = []

    new_entries = []

    for entry in entries:
        if not entry.get("link"):
            continue
        if is_duplicate_entry(entry, existing_keys):
            exact_duplicate_count += 1
            continue
        if fuzzy_enabled and (dup := find_rapidfuzz_duplicate_entry(entry, existing_keys, content_threshold)):
            rapidfuzz_duplicate_pair.append({"new": entry.get("link"), "old": dup.get("link")})
            continue
        new_entries.append(entry)
        add_entry_dedupe_keys(entry, existing_keys)

    print(
        f"🆕 新消息 {len(new_entries)} 条 | "
        f"精确去重：{exact_duplicate_count} 条 | "
        f"模糊去重：{len(rapidfuzz_duplicate_pair)} 条 | "
        f"历史条目：{existing_count}"
    )
    if rapidfuzz_duplicate_pair:
        print("⚠️ 模糊去重明细:")
        print(format_fuzzy_dedupe_details(rapidfuzz_duplicate_pair))

    if not new_entries:
        return

    print("🤖 LLM评分中...")
    # 预处理：将所有 datetime 转换为字符串，避免 JSON 序列化错误
    for entry in new_entries:
        if isinstance(entry.get("published"), datetime):
            entry["published"] = (
                entry["published"].astimezone(get_timezone()).isoformat()
            )

    scored = await score_batch(new_entries)

    # 筛选出符合domain要求的entry,llm已经只输出domain在activity_domains中的元素,保险起见再清理一遍
    activity_domains = set(config.llm.prompts.domain.activity_domains)
    scored = [entry for entry in scored if entry["domain"] in activity_domains]

    is_new_file = not os.path.exists(fetch_file)
    if is_new_file:
        cleanup_old_files(days=config.filter.keep_days)

    # 添加 fetched_at 时间戳
    for entry in scored:
        entry["fetched_at"] = now_local().isoformat()
        if isinstance(entry.get("published"), datetime):
            entry["published"] = (
                entry["published"].astimezone(get_timezone()).isoformat()
            )

    meta = {"date": date.today().isoformat()}
    append_entries(fetch_file, scored, meta)

    print(f"💾 已保存到 {fetch_file}")

    hot_threshold = config.filter.hot_threshold
    no_content_marker = config.filter.no_content_marker
    hot_entries = [e for e in scored if (e.get("score") or 0) >= hot_threshold]
    if hot_entries and is_immediate_push_forbidden():
        print(f"⏰ 当前时间处于即时推送禁止时间段, 跳过即时推送")
    elif hot_entries:
        hot_entries_by_domain: Dict[str, List[Dict]] = {}
        for entry in hot_entries:
            domain: str = entry.get("domain")
            if not domain or domain.strip() == "": continue
            hot_entries_by_domain.setdefault(domain, []).append(entry)

        print(
            f"🔥 发现 {len(hot_entries)} 条热点消息，按 {len(hot_entries_by_domain)} 个 domain 即时推送..."
        )

        # 加载近期已推送事件清单（仅供 LLM 查重，避免风格趋同）
        for domain in sort_domains(list(hot_entries_by_domain.keys())):
            domain_hot_entries = hot_entries_by_domain[domain]
            print(f"🤖 [{domain}] 生成即时快讯 | 热点: {len(domain_hot_entries)} 条")

            recent_notify = load_recent_notify_titles(domain=domain)
            recent_push = load_recent_push_titles_for_immediate_push(domain=domain)
            recent_context = (
                f"=== 近期即时推送事件 ===\n{recent_notify}\n\n"
                f"=== 近期汇总推送事件 ===\n{recent_push}"
            )

            push_content, immediate_push_error = await generate_immediate_push(
                domain_hot_entries,
                recent_push_context=recent_context,
                domain=domain,
            )

            if immediate_push_error:
                await notify_llm_errors(
                    f"generate_immediate_push:{domain}",
                    [immediate_push_error],
                )

            if not push_content:
                print(f"⚠️ [{domain}] 即时推送内容生成失败，跳过本组热点推送")
                continue

            # 检查是否有实际内容需要推送
            if no_content_marker in push_content:
                print(f"ℹ️ [{domain}] 无新内容需要推送 (LLM判定为重复内容)")
            else:
                await send_to_platforms(push_content, title="AI Daily 快讯")
                # 保存即时推送内容到notify文件
                notify_file = get_notify_file(domain=domain)
                save_notify_file(notify_file, push_content, domain=domain)
                print(f"💾 [{domain}] 已保存即时推送到 {notify_file}")

    print(f"✅ Fetch Job 完成 | 新消息: {len(scored)} 条 | 热点: {len(hot_entries)} 条")


async def run_push_job():
    config = get_config()
    print(f"\n{'=' * 50}")
    print(f"📤 Push Job | {now_local().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 50}")

    min_score = config.filter.min_score
    domain_pushes = collect_entries_for_domain_pushes()

    total_to_push = sum(len(group["to_push"]) for group in domain_pushes.values())
    total_context = sum(len(group["context"]) for group in domain_pushes.values())
    total_qualified = total_to_push + total_context
    print(
        f"📋 符合标准条目: {total_qualified} 条 (待推送: {total_to_push}, 上下文参考: {total_context})"
    )

    if not total_to_push:
        print("ℹ️ 没有新消息需要推送")
        return

    print(f"✅ 符合推送标准(≥{min_score}分): {total_to_push} 条")

    pushed_domains = 0
    pushed_entries = 0

    for domain in sort_domains(list(domain_pushes.keys())):
        group = domain_pushes[domain]
        to_push = group["to_push"]
        context = group["context"]
        if not to_push:
            continue

        last_push_time = group["last_push_time"]
        if last_push_time:
            print(f"📌 [{domain}] 上次推送: {last_push_time.strftime('%Y-%m-%d %H:%M')}")
        print(
            f"🤖 [{domain}] 生成推送内容 | 待推送: {len(to_push)} 条, 上下文: {len(context)} 条"
        )

        recent_push_context_str = load_recent_push_titles(domain=domain)
        try:
            push_content = await compose_digest(
                to_push,
                context,
                recent_push_context=recent_push_context_str,
                domain=domain,
            )
        except Exception as e:
            print(f"[{domain}] 生成汇总推送失败: {e}")
            await notify_llm_errors(f"compose_digest:{domain}", [str(e)])
            continue

        if not push_content.strip():
            print(f"⚠️ [{domain}] 推送内容为空，跳过")
            continue

        await send_to_platforms(push_content, title="AI Daily 资讯汇总")

        push_time = now_local()
        push_file = get_push_file(push_time=push_time, domain=domain)
        save_push_file(
            push_file,
            push_content,
            len(to_push),
            len(to_push),
            domain=domain,
            push_time=push_time,
        )
        print(f"💾 [{domain}] 已保存到 {push_file}")

        pushed_domains += 1
        pushed_entries += len(to_push)

    if not pushed_domains:
        print("⚠️ 所有 domain 的推送内容都未成功生成")
        return

    print(f"✅ Push Job 完成 | domain: {pushed_domains} 个 | 推送: {pushed_entries} 条")


async def fetch_loop():
    """Fetch循环 - 修复时间漂移并支持优雅退出"""
    import time

    config = get_config()
    interval_seconds = config.schedule.fetch_interval_minutes * 60
    print(f"🔄 Fetch循环已启动 | 严格间隔: {interval_seconds / 60}分钟")

    while True:
        start_time = time.monotonic()  # 使用 monotonic 避免系统时间修改影响

        try:
            await run_fetch_job()
        except asyncio.CancelledError:
            print("⚠️ Fetch循环被外部取消，正在安全退出...")
            break  # 允许外部取消任务
        except Exception as e:
            print(f"❌ Fetch Job 失败: {e}")

        # 计算任务耗时
        elapsed = time.monotonic() - start_time
        # 计算还需要睡多久（如果任务耗时超过间隔，则不睡，立刻进入下一次）
        sleep_time = max(0.0, interval_seconds - elapsed)

        if sleep_time > 0:
            print(f"⏰ 下次抓取: {sleep_time / 60:.1f}分钟后")

        try:
            await asyncio.sleep(sleep_time)
        except asyncio.CancelledError:
            print("⚠️ 睡眠被中断，Fetch循环安全退出...")
            break


async def push_loop():
    """Push循环 - 无状态 croniter + 原生异步睡眠"""
    config = get_config()
    valid_crons = config.schedule.push_cron
    tz = get_timezone()

    print(f"📤 Push循环已启动 | 定时: {', '.join(valid_crons)} | 时区: {tz}")

    while True:
        try:
            now = datetime.now(tz)

            # 💡 核心优化：无状态计算。
            # 每次都基于此刻的真实时间，动态计算所有有效 cron 的下一次时间，取最近的一个。
            # 这样无论 run_push_job 执行多久，或者系统休眠过，永远都不会算错。
            next_push = min(
                croniter(cron, now).get_next(datetime) for cron in valid_crons
            )

            wait_seconds = (next_push - datetime.now(tz)).total_seconds()

            if wait_seconds > 0:
                print(
                    f"⏰ 下次推送: {next_push.strftime('%Y-%m-%d %H:%M:%S')} (等待 {wait_seconds / 60:.1f} 分钟)"
                )

                # 💡 核心优化：直接 Sleep。asyncio 天生支持被 CancelledError 瞬间打断
                await asyncio.sleep(wait_seconds)

            # 到达推送时间，执行推送
            print(f"📤 执行推送: {datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S')}")
            await run_push_job()

            # 增加 1 秒缓冲：防止 run_push_job 执行过快（不到 1 秒），
            # 导致下一个循环的 now 仍停留在当前秒，croniter 算出重复的时间点。
            await asyncio.sleep(1)

        except asyncio.CancelledError:
            print("⚠️ Push循环收到取消信号，安全退出...")
            break  # 直接 break 退出循环即可
        except Exception as e:
            print(f"❌ Push 循环异常: {e}")
            # 遇到未知异常时休眠 60 秒，防止死循环疯狂报错打满日志
            await asyncio.sleep(60)


async def run_source_sync_job():
    print(f"\n{'=' * 50}")
    print(f"🔁 Source Sync Job | {now_local().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'=' * 50}")

    result = await sync_opml_sources()
    if result.updated:
        print(
            f"✅ RSS源列表已更新 | 来源: {result.source_count} 个 | 去重后: {result.feed_count} 个 | 文件: {result.target_path}"
        )
        return

    print(f"⚠️ RSS源列表未更新，继续使用现有 OPML: {result.target_path}")
    for failure in result.failures:
        print(f"  - {failure}")


async def source_sync_loop():
    """Source同步循环 - 每周拉取远端 OPML 并生成本地 RSS 源列表。"""
    config = get_config()
    if not config.sources.sync.enabled:
        return

    cron = config.sources.sync.cron
    tz = get_timezone()
    print(f"🔁 RSS源同步循环已启动 | 定时: {cron} | 时区: {tz}")

    while True:
        try:
            now = datetime.now(tz)
            next_sync = croniter(cron, now).get_next(datetime)
            wait_seconds = (next_sync - datetime.now(tz)).total_seconds()

            if wait_seconds > 0:
                print(
                    f"⏰ 下次RSS源同步: {next_sync.strftime('%Y-%m-%d %H:%M:%S')} (等待 {wait_seconds / 3600:.1f} 小时)"
                )
                await asyncio.sleep(wait_seconds)

            print(f"🔁 执行RSS源同步: {datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S')}")
            await run_source_sync_job()

        except asyncio.CancelledError:
            print("⚠️ RSS源同步循环收到取消信号，安全退出...")
            break
        except Exception as e:
            print(f"❌ RSS源同步循环异常: {e}")
            await asyncio.sleep(60)


async def run_startup_source_sync_if_needed():
    """启动抓取循环前先完成一次 RSS 源同步，避免首次抓取使用旧 OPML。"""
    config = get_config()
    if not config.sources.sync.enabled:
        return

    try:
        await run_source_sync_job()
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print(f"❌ RSS源同步启动任务失败: {e}")


async def main():
    print("🚀 AI每日资讯推送系统启动")

    # 配置非法或缺失时 initialize_config 直接退出进程
    initialize_config()
    print("✅ 配置加载成功")

    print("🔍 检查LLM接口可用性...")
    try:
        await check_llm_available()
        print("✅ LLM接口可用")
    except Exception as e:
        logging.getLogger(__name__).error("LLM接口不可用，程序退出: %s", e)
        raise SystemExit(1) from e

    await run_startup_source_sync_if_needed()

    await asyncio.gather(
        fetch_loop(),
        push_loop(),
        source_sync_loop(),
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 程序已退出")
