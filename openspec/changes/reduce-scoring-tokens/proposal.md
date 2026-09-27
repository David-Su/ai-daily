## Why

评分占 LLM 输入的 80% 以上。按 2026-09-20 至 09-25 的运行日志估算（64 轮抓取，tiktoken o200k），评分输入约 3.58M token，其中两类浪费不产出任何有效结果：

- 约 30% 的评分批次失败（47/154）。按每批约 23k token 计，失败批次浪费约 1.1M token，涉及约 4900 条条目未能评分。多数失败的错误信息为空，推测为请求超时：`call_llm()` 只按 HTTP 状态码重试，超时和网络异常直接抛出，既不重试也不走兜底；另有一次失败是大批次的评分 JSON 输出被截断。
- 被拒条目在后续轮次重复评分，约 4000–5500 次、250k–470k token。其中约 12 万 token 来自两个日期无效的源：`engineering.khanacademy.org` 的 `pubDate` 无法解析，时间过滤失效，每轮都会重新评分同样 59 篇 2020 年的旧文；`browser.engineering` 的条目没有发布日期。其余来自抓取回溯窗口与抓取间隔的 60 分钟重叠。

评分输出沿用了 prompt 示例的缩进格式，每条约 60 token，紧凑格式约 42 token。输出越长，生成越慢，也越容易触发超时和截断。

## What Changes

- 超时和网络异常视为临时故障，与可重试的 HTTP 状态码一样按 `max_retries` 重试，失败后走 `llm.fallback`。
- LLM 失败日志（评分、即时快讯、汇总）包含异常类型名，空消息的异常不再只显示为空白，用于确认批次失败的真实原因。
- `llm.max_prompt_chars` 从 64000 下调到 30000，单批从约 116 条降到约 52 条，输出更短，降低超时和截断的概率。批次数约翻倍（按日志回放，154 → 约 340），每批固定 prompt（约 1.35k token）的总开销随之上升，预计每 5 天约增加 250k token，远小于失败批次约 1.1M 的浪费。
- 进程内记录被拒链接，在有效期内跳过对这些链接的评分：
  - 评分成功的批次中，模型未返回的条目和 domain 不在已配置 domain 中的条目，其链接记为被拒。
  - 评分失败的批次一律不记录，下一轮照常评分。
  - 有效期为 24 小时，通过新增配置项调整。
  - 记录只保存在内存中。进程重启后记录清空，重启后的第一轮会重新评分。
  - 日志输出本轮跳过的被拒条目数。
- 评分 prompt 的输出示例改为单行紧凑 JSON，字段顺序与字段说明保持一致；两处重复的"只输出 JSON"要求合并为一处。
- `sources.block` 新增 `engineering.khanacademy.org` 和 `browser.engineering` 两个源。

已接受的取舍：模型偶尔会漏掉本应入选的条目，被拒记录会让这类条目在有效期内失去重新评分的机会。按日志估算，约影响 1% 的入库条目。

## Capabilities

### New Capabilities

- `llm-transient-error-retry`: LLM 请求超时和网络异常按临时故障重试并走兜底，失败日志包含异常类型名。
- `rejected-link-skip`: 在内存中记录评分成功批次里的被拒链接，有效期内跳过对这些链接的评分，评分失败的批次不记录。
- `score-compact-output`: 评分 prompt 要求模型输出单行紧凑 JSON。

### Modified Capabilities

## Impact

- `src/llm.py`：`call_llm()` 将超时和网络异常纳入重试和兜底；`score_batch()` 在返回评分结果的同时返回成功批次中的被拒链接。
- `src/main.py`：抓取去重前先跳过有效期内的被拒链接，并在日志中输出跳过数；[main.py:263](../../../src/main.py) 按 domain 过滤掉的条目也计入被拒。
- `src/config.py`、`config.yaml`：新增被拒记录有效期配置，`max_prompt_chars` 改为 30000，`sources.block` 新增两个源。
- `src/llm.py`、`src/main.py`：评分和即时快讯的失败日志（`llm.py`）、汇总的失败日志（`main.py`）加上异常类型名。
- `prompts/score/score_batch.md`：输出格式改为单行紧凑 JSON。
- `docs/tech-spec.md`：同步更新配置详解、重试边界和被拒记录规则；`docs/plan.md` 记录这次技术决策。
- `tests/`：补充超时重试、被拒记录和失败批次不记录的用例。
- 效果以 `LLM usage` 日志验证：评分调用的 prompt_tokens 总量、每条条目的 completion_tokens，以及评分失败次数。
- 不在本次范围内：汇总字段瘦身、低分条目精简输出、零产出源的批量屏蔽。
