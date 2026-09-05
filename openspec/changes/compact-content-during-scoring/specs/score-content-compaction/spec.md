## Purpose

在一次评分请求中阅读完整正文并完成分类、评分与高保真压缩，减少后续摘要和即时推送携带的上下文，同时保持下游继续使用既有 `content` 字段。

## ADDED Requirements

### Requirement: Full content is available to scoring

评分流程 MUST 在批次安全预算允许的范围内向模型传入每条输入的完整 `content`，不得再固定截断为前 2,000 个字符。普通批次划分 MUST 避免评分 prompt 超过配置的字符或上下文预算；无法容纳的单条正文 MUST 单独处理并显式告警，不得静默截断。

#### Scenario: Content tail is visible to the model

- **WHEN** 一条正文长度超过 2,000 个字符且其尾部包含事实信息
- **THEN** 评分请求中的该条输入包含正文尾部，不因固定 2,000 字符截断而丢失

#### Scenario: Large inputs are split safely

- **WHEN** 多条完整正文合计超过单次评分 prompt 预算
- **THEN** 系统将输入拆分为多个批次，且每个批次的实际 prompt 大小不超过配置预算

#### Scenario: Oversized single content is not silently truncated

- **WHEN** 单条完整正文自身超过普通批次预算
- **THEN** 系统将该条单独处理并记录超预算告警，不截断正文；若供应商拒绝请求，则按评分失败回退且不生成压缩正文

### Requirement: Classification, scoring, and compaction are independent tasks

评分提示词 MUST 明确要求模型分别执行分类、评分（含 tags 与 summary）和内容压缩。分类与评分 MUST 基于原始标题和完整正文；压缩 MUST 只基于该条原始标题和完整正文，不得依据 summary、tags、分数或领域判断改写事实内容。领域结果仅可用于选择评分标准以及判断是否属于已配置领域。

#### Scenario: Scoring judgment does not rewrite content

- **WHEN** 模型认为一条文章分数较低或其领域为“其他”
- **THEN** 该判断不会改变压缩任务对原文事实、顺序和限定条件的保留规则

#### Scenario: Compression follows source wording

- **WHEN** 一条达到压缩门槛的正文包含多个事件、数字、时间、来源口径或限制条件
- **THEN** 输出的 `content` 尽量保持原文结构和语义，并保留所有对理解事件有关键作用的信息，不新增原文不存在的事实、数字、归因或结论

### Requirement: Minimum score gates output and compaction

系统 MUST 向评分提示词传入 `lowest_retained_score`，其值为 `min(min_score, hot_threshold)`。分数低于该值的条目 MUST 不执行压缩且 MUST 不在评分响应中输出由模型生成的 `content` 字段；其分类、评分、标签和摘要结果仍应按现有评分流程返回，以便程序保留原始正文并维持下游行为。分数达到该值的条目才可输出压缩正文，正文是否压缩再由内容长度阈值决定。

#### Scenario: Below-threshold content is omitted

- **WHEN** 模型为一条输入判定的分数低于 `lowest_retained_score`
- **THEN** 评分响应仍包含该条目的分类、分数、标签和摘要，但不包含模型生成的 `content` 字段，也不执行内容压缩

#### Scenario: Threshold item remains eligible

- **WHEN** 模型为一条输入判定的分数等于或高于 `lowest_retained_score`
- **THEN** 评分响应包含该条目的分类、分数、标签和摘要；若正文超过压缩阈值，则同时包含压缩后的 `content`

### Requirement: Compaction reuses the existing content field

评分结果 MUST 继续使用 `content` 作为唯一正文属性，不得要求下游识别 `compressed_content`、状态字段或新的正文属性。合并评分结果时，只有非空且严格短于原文的有效返回 `content` 才能覆盖原文；缺失、为空、无效或不短的返回 MUST 保留原始 `content`。

#### Scenario: Valid shorter content replaces source

- **WHEN** 达到门槛的条目返回非空且字符数少于原始正文的 `content`
- **THEN** 持久化条目的 `content` 被该高保真压缩正文替换，下游继续按原有字段读取

#### Scenario: Unsafe compaction falls back

- **WHEN** 返回的 `content` 为空、格式错误、比原文更长或无法通过有效性校验
- **THEN** 系统保留原始 `content`，不丢弃该条目且不改变下游字段契约

#### Scenario: Program enforces the compaction gate

- **WHEN** 低于 `lowest_retained_score` 的条目，或未超过压缩阈值的条目，违规返回模型生成的 `content`
- **THEN** 系统忽略该 `content` 并保留原始正文

### Requirement: Original content remains available for exact deduplication

当有效压缩正文覆盖持久化 `content` 时，系统 MUST 保留一个只供去重使用的稳定原始正文字段指纹。后续抓取的相同原始正文 MUST 仍能命中精确正文去重；没有该指纹的历史条目 MUST 保持当前基于链接、标题和正文的兼容去重行为。该内部指纹 MUST 不出现在评分、digest 或即时推送的 LLM 输入中。

#### Scenario: Compressed stored entry matches a later identical source

- **WHEN** 一条正文被有效压缩后持久化，随后有不同链接的条目携带相同原始正文
- **THEN** 后续条目仍命中精确正文去重，而不依赖压缩后的 `content` 与原文完全相同

#### Scenario: Historical entry without a source fingerprint remains usable

- **WHEN** 去重读取的历史 fetch 条目没有原始正文指纹
- **THEN** 系统继续使用现有链接、标题和持久化正文规则判断重复，且不因缺少该字段失败

### Requirement: Effective compaction is observable

评分结果合并后，系统 MUST 仅针对实际采用且字符数严格少于原文的 `content` 打印压缩日志。日志 MUST 包含条目链接、原文字数、压缩后字数和相对于原文的节省百分比；未变短的条目 MUST 不打印该日志。

#### Scenario: Log a shorter result

- **WHEN** 条目的新 `content` 被采用且其字符数小于原文
- **THEN** 日志打印该条目链接，并按 `(原文字数-压缩后字数)/原文字数×100%` 输出节省百分比

#### Scenario: Do not log non-compaction

- **WHEN** 条目没有返回压缩正文，或新正文字符数等于或大于原文
- **THEN** 系统不打印压缩日志
