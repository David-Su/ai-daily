# 开发计划

## 技术决策

- `add-llm-usage-logging`：在统一 LLM 响应路径向标准输出记录档位、实际请求模型和原始 usage；不保存 usage 文件，不改变请求或正文处理。
- `reduce-scoring-tokens`：主模型的 `asyncio.TimeoutError` 和 `aiohttp.ClientError` 沿用 `max_retries` 总尝试次数与指数退避，耗尽后在允许且配置兜底时请求兜底一次；兜底不重试，其他响应格式异常直接抛出。评分、即时快讯和汇总统一记录 `异常类型名: 消息`，异常通知与日志复用同一错误文本。
- `reduce-scoring-tokens`：成功批次中模型未返回结果的链接，以及 domain 未配置的链接，在评分完成时记为被拒；失败批次和已入库条目不记录。记录仅在进程内存中保存，去重前单独跳过并计数，达到或超过有效期就移除，重新被拒时刷新时间，重启清空，fetch 文件结构不变。`dedupe.rejected_ttl_hours` 为必填 `PositiveInt`，部署值为 24 小时；接受模型漏选的条目在有效期内失去重评机会的取舍，估算约影响 1% 的入库条目。
- `reduce-scoring-tokens`：`llm.max_prompt_chars` 从 64000 调整为 30000；评分 prompt 使用单行紧凑 JSON 示例，字段顺序为 `id`、`domain`、`score`、`tags`、`summary`，解析继续兼容缩进格式。`sources.block` 新增精确 RSS 地址 `http://engineering.khanacademy.org/rss` 和 `https://browser.engineering/rss.xml`。上线后根据 `LLM usage` 的评分输入总量、每条输出 token 和评分失败次数评估效果。
- `reduce-reasoning-tokens`：09-27 至 09-29 运行日志显示评分占 74% 费用，其中约 70% 为推理 token，且长推理导致 37 次超时、11 个评分批次失败。`low` 档（评分、即时快讯）在代码中固定传 `reasoning_effort=low`，其他档位不传；不设置显式请求超时。`llm.max_prompt_chars` 按实测单条约 480 字符（p90 约 930）、模板约 2100 字符估算，调整为 40000，每批约 80 条、每轮 2~4 批。上线后根据评分调用的 `reasoning_tokens` 与评分失败次数评估效果。

## 开发进度

- 已完成 usage 日志接入及技术说明，25 个相关本地桩测试通过。
- `reduce-scoring-tokens`：已完成超时与网络异常重试、异常类型日志、被拒链接内存记录、紧凑评分输出及配置调整，README 和技术规格已同步。全量 `pytest tests` 为 112 项通过、5 项真实服务调试用例跳过；`openspec-cn validate reduce-scoring-tokens --strict` 通过。
- `reduce-reasoning-tokens`：已完成 low 档 `reasoning_effort` 与评分批次大小调整，README 和技术规格已同步。全量 `pytest tests` 为 114 项通过、5 项跳过、1 项失败（`test_successful_omissions_and_unknown_domains_are_rejected_only_in_memory`，改动前已存在）。
