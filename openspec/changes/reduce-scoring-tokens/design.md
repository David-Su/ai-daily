## Context

动机和估算参见 [proposal.md](proposal.md) 的 Why；行为契约参见 `specs/` 下的三份 spec。

与方案相关的现状：

- `call_llm()` 的 `request_once()` 只在返回非 200 时给出状态码；超时和连接异常直接从 `session.post()` 抛出，绕过了重试循环和兜底。`ClientSession` 使用 aiohttp 默认超时（总计 300 秒）。
- `_score_single_batch()` 失败时返回 `[]`，与"成功但全部被拒"无法区分。`_merge_scores()` 打印的"评分过滤链接"因此混入了失败批次的条目。
- 按 domain 过滤发生在 `run_fetch_job()` 中（`scored` 只保留已配置 domain）。
- 抓取去重在 `run_fetch_job()` 中逐条调用 `is_duplicate_entry()`，它对 `existing_keys` 做线性扫描。
- `fetch_loop()` 在同一进程内串行调用 `run_fetch_job()`，不存在并发抓取。
- 测试用 `_install_llm_http()` 把 `sys.modules["aiohttp"]` 替换为只含 `ClientSession` 的 `SimpleNamespace`。

## Goals / Non-Goals

**Goals:**

- 每项改动集中在一个接入点，改动后评分结果的字段、fetch 文件结构和推送行为保持不变。
- 让批次失败的真实原因能从日志直接读出，以便后续用 `LLM usage` 和失败日志评估 30000 是否合适。

**Non-Goals:**

- 不设置显式的 HTTP 超时时长，不改退避间隔和 `max_retries` 默认值。
- 不持久化被拒记录，不按源统计零产出，不修复 `pubDate` 解析。
- 不改动汇总和即时快讯的 prompt 与输入字段。

## Decisions

### 1. 在主模型重试循环里捕获超时与连接异常

在 `call_llm()` 的主模型循环中，用 `try/except (asyncio.TimeoutError, aiohttp.ClientError)` 包住 `request_once()`。捕获后把异常存为 `last_error`：未到最后一次尝试时打印带异常类型名和重试序号的日志、退避后继续；否则跳出循环，走已有的兜底逻辑。兜底请求不加捕获，异常原样抛出，满足"兜底只请求一次"。循环结束后的 `raise last_error` 不变，异常类型得以保留。

`aiohttp.ServerTimeoutError` 同时是这两类的子类，已被覆盖。其他异常（例如响应缺少 `choices` 引起的 `KeyError`）属于响应格式问题，重试通常无效，保持直接抛出。

备选方案：在 `request_once()` 内部把异常转成 `(None, error, status=None)` 返回。这样需要为"无状态码"另设可重试判断，改动面更大。

### 2. 失败日志统一使用 `类型名: 消息`

评分批次（`_score_single_batch`）、即时快讯（`generate_immediate_push`）和汇总（`run_push_job` 的 `except`）三处，把 `{e}` 改为 `{type(e).__name__}: {e}`。即时快讯的 `error_message` 和汇总的异常通知直接复用同一字符串，确保日志与通知一致。

不新增辅助函数：三处各一行 f-string，比引入公共函数更直观。

### 3. `score_batch()` 返回评分结果和被拒链接

`_score_single_batch()` 失败时返回 `None`，成功时返回结果列表（可能为空）。`score_batch()` 汇总成功批次里的条目，经 `_merge_scores()` 合并后，把"属于成功批次但不在合并结果中"的条目链接作为被拒链接，返回 `(scored, rejected_links)`。

`run_fetch_job()` 在按 domain 过滤时，把被过滤掉条目的链接追加到 `rejected_links`。这样两类被拒都在同一处记录，失败批次天然被排除。

`_merge_scores()` 中"评分过滤链接"日志改为只统计成功批次，避免把失败批次误报为被拒。

备选方案：由 `score_batch()` 返回失败链接，由调用方反推被拒。两种方式等价，但返回被拒链接能让调用方直接使用，不必重复计算集合差。

### 4. 被拒记录用模块级 dict，在去重前单独判断

在 `src/main.py` 中用模块级 `_rejected_links: Dict[str, datetime]` 保存链接和被拒时间（UTC）。`run_fetch_job()` 的执行顺序：

```
 开始  ─▶ 删除过期记录（now - t >= ttl）
 去重  ─▶ link in _rejected_links ? 计入"被拒跳过"并跳过
       ─▶ is_duplicate_entry / 模糊去重（不变）
 评分  ─▶ score_batch → (scored, rejected_links)
       ─▶ domain 过滤，被过滤的链接并入 rejected_links
 记录  ─▶ _rejected_links[link] = now（覆盖旧时间）
```

使用 dict 查找，不塞进 `existing_keys`，避免让 `is_duplicate_entry()` 的线性扫描变长，也让"被拒跳过"可以单独计数。`fetch_loop()` 串行执行，不需要加锁。

配置项 `dedupe.rejected_ttl_hours`（`PositiveInt`，默认写在 `config.yaml` 中为 24），放在 `dedupe` 节，因为它与抓取去重同属一类行为。

备选方案：写进 fetch 文件的顶层字段。它能跨重启保留，但要改文件结构，且受跨天读取规则限制；按日志估算，内存方案的收益与之相当。

### 5. 紧凑 JSON 示例只改 prompt

`prompts/score/score_batch.md` 的输出格式章节改为单行示例，字段顺序与"输出要求"中的字段说明一致；第 20 行和第 53 行的两处"只输出 JSON"合并为输出格式章节中的一处正面要求。`_parse_score_response()` 已能解析紧凑和缩进两种格式，不改代码。

### 6. 配置变更

- `llm.max_prompt_chars`: 64000 → 30000。
- `dedupe.rejected_ttl_hours: 24`。
- `sources.block` 追加 `http://engineering.khanacademy.org/rss` 和 `https://browser.engineering/rss.xml`（与 `resources/rss.opml` 中的 `xmlUrl` 完全一致）。

## Risks / Trade-offs

- [超时重试拉长单轮耗时：最坏情况下一个批次为 3 × 300 秒加一次兜底，约 20 分钟] → 并发为 3，约 7 个批次时最坏约 1 小时，仍在 120 分钟的抓取间隔内。上线后按失败日志中的异常类型判断是否需要显式超时，留作后续调整。
- [被拒记录让模型漏掉的条目在 24 小时内失去重评机会，约 1% 的入库条目] → proposal 已接受；可通过调小 `rejected_ttl_hours` 缓解。
- [重启后第一轮会重评此前被拒的条目] → 日志显示 5 天只重启过 1 次，影响可忽略。
- [批次数翻倍，固定 prompt 开销每 5 天约增加 250k token] → 若失败率下降不明显，可用 `LLM usage` 数据回调 `max_prompt_chars`。
- [模型不遵守单行格式] → 解析器兼容缩进输出；效果用每条 completion_tokens 验证。
- [`score_batch()` 返回值变化] → 调用方只有 `run_fetch_job()` 和测试，同步修改。

## Migration Plan

部署新代码与配置即可，没有数据迁移。fetch 文件结构不变，旧文件照常读取。回滚时恢复代码和 `config.yaml`；被拒记录在进程重启后自然清空。
