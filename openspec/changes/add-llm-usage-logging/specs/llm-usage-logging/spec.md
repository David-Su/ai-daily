## Purpose

将 LLM 供应商响应中的原始 token 用量输出到现有运行日志，并携带档位和实际请求的模型名，使用户能够统计可观测响应的消耗，评估节省 token 的效果，同时明确缺失计量不代表零消耗。

## ADDED Requirements

### Requirement: 可观测响应的单行用量日志

系统 SHALL 为每个 HTTP 200 且响应 JSON 解析成功的 LLM 响应输出恰好一条用量日志。日志 MUST 使用格式 `LLM usage | tier=<档位> | model=<本次请求模型> | usage=<紧凑 JSON 值>`，其中档位为 `low`、`medium` 或 `high`，模型名 MUST 对应本次实际发出的请求。

#### Scenario: 主模型响应
- **WHEN** 主模型返回 HTTP 200 且响应 JSON 解析成功
- **THEN** 系统输出一条包含调用档位、本次请求模型名及响应用量的 `LLM usage` 日志

#### Scenario: 兜底模型响应
- **WHEN** 主模型失败后兜底模型返回 HTTP 200 且响应 JSON 解析成功
- **THEN** 用量日志保留原调用档位，模型名为本次请求的兜底模型名

#### Scenario: 启动探测响应
- **WHEN** 任一档位的启动探测收到 HTTP 200 且响应 JSON 解析成功
- **THEN** 系统按相同格式输出该档位主模型的用量日志

### Requirement: 原始用量与缺失值

系统 MUST 保留响应 `usage` 值中的所有字段、数值和嵌套明细，包括供应商扩展字段。响应未包含 `usage` 或其值为 `null` 时，系统 MUST 输出 `usage=null`，不得用零值、空对象或估算 token 数代替。

#### Scenario: 包含嵌套与扩展字段
- **WHEN** 响应的 `usage` 包含 token 总量、缓存或推理明细以及供应商扩展字段
- **THEN** 日志中的 JSON 值与供应商返回的 `usage` 在数据内容上相同，所有嵌套字段均被保留

#### Scenario: 未返回用量
- **WHEN** 响应未包含 `usage` 字段，或该字段为 `null`
- **THEN** 日志输出 `usage=null`，调用仍按原流程处理模型正文

#### Scenario: 供应商明确报告零用量
- **WHEN** 响应的 `usage` 中某个 token 数为数值 `0`
- **THEN** 日志保留该数值，与缺失用量的 `null` 明确区分

### Requirement: 先记录计量再处理正文

系统 MUST 在成功解析响应 JSON 后、读取或解析模型正文之前输出用量日志。后续正文处理失败 MUST NOT 导致已返回的用量记录被省略。

#### Scenario: 评分正文不是有效评分 JSON
- **WHEN** LLM 响应 JSON 解析成功且包含 `usage`，但模型正文不能解析为评分结果
- **THEN** 用量日志出现在评分失败日志之前，评分失败仍按原流程处理

### Requirement: 仅增加标准输出观测

系统 MUST 将用量日志写入标准输出，不得为该功能创建或追加本地 usage 文件。该日志 MUST 仅包含固定前缀、档位、请求模型名和响应的 `usage` 值，不得输出 prompt、模型正文、密钥、请求头或完整响应。新增观测 MUST 保持原请求、模型正文返回值、重试及兜底行为。

#### Scenario: 正文返回行为
- **WHEN** LLM 返回正常正文和 `usage`
- **THEN** 系统输出用量日志，返回正文的内容、空格和换行保持原样，且日志不包含该正文或 prompt

#### Scenario: 错误响应或网络异常
- **WHEN** LLM 请求返回非 HTTP 200、响应 JSON 解析失败或发生网络异常
- **THEN** 系统沿用原错误处理流程，不生成本功能的用量日志，也不将未知消耗报告为零
