## 1. 超时重试与失败日志

- [x] 1.1 在 `tests/test_flow.py` 让 `_install_llm_http()` 支持按队列抛出异常（`asyncio.TimeoutError`、`aiohttp.ClientError` 子类），并在桩的 `aiohttp` 命名空间中提供 `ClientError`；补充用例：超时后重试成功、持续超时后走兜底且兜底只请求一次、兜底也超时时抛出兜底异常、未声明兜底时抛出最后一次异常、404 行为不变、重试日志含 `TimeoutError` 和序号。先运行新用例，确认在当前实现下失败。
- [x] 1.2 在 `src/llm.py` 的 `call_llm()` 主模型循环中捕获 `asyncio.TimeoutError` 与 `aiohttp.ClientError`，按 design 决策 1 记录 `last_error`、打印重试日志、退避后重试，耗尽后走原有兜底；兜底请求不加捕获。运行 1.1 用例及现有 `test_call_llm_*` 用例，确认全部通过。
- [x] 1.3 补充用例：评分批次因空消息超时失败时日志含 `TimeoutError`，解析失败时日志以 `ValueError` 开头，即时快讯失败的 `error_message` 与汇总失败日志、异常通知都含异常类型名。然后在 `_score_single_batch()`、`generate_immediate_push()`（`src/llm.py`）和 `run_push_job()` 的 `except`（`src/main.py`）中改为 `{type(e).__name__}: {e}`，运行用例确认通过。

## 2. 被拒链接记录

- [x] 2.1 在 `src/config.py` 的 `DedupeConfig` 新增 `rejected_ttl_hours: PositiveInt`，`config.yaml` 的 `dedupe` 节写入 `rejected_ttl_hours: 24` 并附注释；运行配置加载相关用例，确认缺失或非正整数时校验失败、现有配置可加载。
- [x] 2.2 补充 `score_batch()` 用例：成功批次中未返回的条目进入被拒链接，失败批次的条目不进入，单批和多批路径结果一致。然后按 design 决策 3 让 `_score_single_batch()` 失败时返回 `None`，`score_batch()` 返回 `(scored, rejected_links)`，`_merge_scores()` 的过滤日志只统计成功批次；同步修改现有调用 `score_batch()` 的测试，运行确认通过。
- [x] 2.3 补充 `run_fetch_job()` 用例（复用 `test_fetch_job_excludes_unconfigured_domain_results` 的桩）：domain 未配置的条目被记为被拒；有效期内再次抓取到的被拒链接不进入评分输入、不入库，且去重日志单独列出被拒跳过数；超过有效期的链接重新评分；再次被拒时刷新时间；失败批次的条目下一轮照常评分；fetch 文件中没有新增字段。
- [x] 2.4 在 `src/main.py` 按 design 决策 4 实现模块级 `_rejected_links`：每轮开始删除过期记录，去重前跳过有效期内的链接并计数，评分后合并 domain 过滤掉的链接并写入记录；去重日志加上被拒跳过数。测试之间需重置 `_rejected_links`。运行 2.3 用例及现有抓取相关用例确认通过。

## 3. 评分 prompt 与配置

- [x] 3.1 修改 `prompts/score/score_batch.md`：输出格式示例改为单行紧凑 JSON，字段顺序为 `id`、`domain`、`score`、`tags`、`summary`；两处"只输出 JSON"合并为输出格式章节中的一处正面要求。补充用例：渲染后的评分 prompt 中示例 JSON 在同一行且可解析、字段顺序正确；`_parse_score_response()` 对缩进 JSON 与紧凑 JSON 解析结果相同。运行确认通过。
- [x] 3.2 修改 `config.yaml`：`llm.max_prompt_chars` 改为 30000；`sources.block` 追加 `http://engineering.khanacademy.org/rss` 和 `https://browser.engineering/rss.xml`。运行 `merge_sources()` 相关用例，并用真实配置确认 `merge_sources()` 的结果不再包含这两个 `xmlUrl`。

## 4. 文档与验证

- [x] 4.1 更新文档：`docs/tech-spec.md` 的 `## 配置详解` 同步 `max_prompt_chars`、`dedupe.rejected_ttl_hours` 与 `sources.block`，LLM 模块章节补充超时与网络异常的重试边界、失败日志格式和被拒记录规则；`README.md` 的配置示例与字段表同步 `max_prompt_chars` 和新配置项；`docs/plan.md` 的 `## 技术决策` 与 `## 开发进度` 记录本次决策与进度。对照三份 spec 审阅文档。
- [x] 4.2 运行 `pytest tests` 确认全部通过，运行 `openspec-cn validate reduce-scoring-tokens --strict` 确认通过。
