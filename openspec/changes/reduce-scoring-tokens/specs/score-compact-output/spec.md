## Purpose

让评分 prompt 要求模型输出单行紧凑 JSON，缩短评分输出的 token 数和生成时间，降低大批次输出超时和截断的概率。

## ADDED Requirements

### Requirement: 评分 prompt 要求单行紧凑 JSON

评分 prompt MUST 要求模型输出一个单行、无缩进、无换行的 JSON 对象，且不包含 JSON 以外的文字。输出示例 MUST 是单行紧凑 JSON，其中字段顺序与字段说明一致：`id`、`domain`、`score`、`tags`、`summary`。"只输出 JSON" 这一要求在 prompt 中 MUST 只声明一次。

输出字段的名称和含义保持不变。

#### Scenario: 渲染后的评分 prompt
- **WHEN** 系统为一个批次渲染评分 prompt
- **THEN** 输出格式章节中的 JSON 示例位于同一行，可被解析为包含 `items` 数组的 JSON 对象，且示例条目的字段依次为 `id`、`domain`、`score`、`tags`、`summary`

### Requirement: 解析兼容非紧凑输出

模型未遵守单行要求、返回带缩进或换行的 JSON 时，系统 MUST 仍能解析评分结果，结果与紧凑格式的解析结果相同。

#### Scenario: 模型返回缩进 JSON
- **WHEN** 模型返回带缩进的 `{"items": [...]}` 评分结果
- **THEN** 系统正常解析出全部评分条目，不判定为评分失败
