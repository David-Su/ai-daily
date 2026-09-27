## Why

当前 LLM 调用只保留响应正文，运行日志缺少供应商返回的 token 用量，无法验证后续优化是否真正节省 token。需要以最小改动将原始 `usage` 输出到现有运行日志，便于统计可观测响应的消耗。

## What Changes

- 在统一 HTTP 响应处理处，为每个 HTTP 200 且 JSON 解析成功的响应输出一条 `LLM usage` 单行日志，字段为 `tier`、本次实际请求的 `model` 和原始 `usage`。
- 保留 `usage` 的全部字段及嵌套明细；供应商未返回该字段时输出 JSON `null`。
- 日志输出发生在读取模型正文之前，覆盖主模型、兜底和启动探测，也保留后续评分解析失败时已返回的计量。
- 沿用现有 `print()` 标准输出，不创建 usage 文件、不增加依赖或配置，也不修改调用签名、请求内容、重试和兜底策略。

## Capabilities

### New Capabilities

- `llm-usage-logging`: 将供应商返回的原始 token 用量连同档位和实际请求模型输出到现有运行日志。

### Modified Capabilities

## Impact

- `src/llm.py`: 在内部 `request_once()` 解析响应 JSON 后增加单行日志，复用 `compact_json()`。
- `tests/test_flow.py`: 复用 HTTP 桩验证日志字段、缺失用量、兜底模型和正文返回行为。
- `docs/tech-spec.md`: 说明日志格式与计量边界。
- 日志新增固定前缀 `LLM usage`；不输出 prompt、正文、密钥、请求头或完整响应。
- 无 usage 的错误响应和网络失败不属于本次计量覆盖范围；日志求和不能视为完整账单。
