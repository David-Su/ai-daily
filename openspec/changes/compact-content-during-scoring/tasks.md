## 1. 配置与评分提示词契约

- [ ] 1.1 在 `LLMConfig` 与 `config.yaml` 增加必填的 `content_compaction_threshold`（Unicode 字符、正整数，初始值 2,000），并验证缺失、非正数和未知字段均由配置校验拒绝。
- [ ] 1.2 更新 `prompts/score/score_batch.md`：明确分类、评分和高保真压缩是独立任务；要求完整正文为事实依据，并验证 prompt 含 `lowest_retained_score`、长度阈值和 `needs_content_compaction` 的输入/输出契约。
- [ ] 1.3 在评分入口显式计算 `min(filter.min_score, filter.hot_threshold)` 并传给 prompt；验证低分 item 仍返回评分元数据但禁止模型 `content`，达到门槛且长度严格超过阈值时才可输出 `content`。

## 2. 完整正文评分与安全分批

- [ ] 2.1 抽取评分输入的单一序列化 helper，使 prompt 构造和批次大小估算共同使用完整 `content`、全局 id 及 transient `needs_content_compaction`；验证超过 2,000 字符的尾部 sentinel 会进入实际评分 prompt。
- [ ] 2.2 改造评分分批以按完整序列化条目和模板开销装箱，保持跨批次 id 不冲突；验证普通多批次的实际 prompt 不超过 `max_prompt_chars` 且结果合并不串条目。
- [ ] 2.3 实现超大单条的独立批次和明确告警，不静默截断；验证超预算单条保留完整正文、不会与其他条目拼批，供应商失败时不产生伪造压缩正文。

## 3. 评分结果合并、压缩与观测

- [ ] 3.1 为评分响应增加批次内唯一整数 id 校验，拒绝重复、越界或类型错误的结果；验证无效结果不会把元数据或正文写入错误条目。
- [ ] 3.2 修改评分结果合并：始终合并有效的 domain/score/tags/summary；仅在分数达到最低门槛、原文超过阈值、返回值为非空字符串且严格更短时覆盖同名 `content`，并验证低分违规返回、短正文、空值、非字符串、等长和更长结果全部回退原文。
- [ ] 3.3 对每个实际采用的压缩结果打印 `link`、原文字数、压缩后字数和一位小数的节省百分比；验证只对严格变短的条目打印日志，百分比计算正确，其他回退路径无日志。
- [ ] 3.4 维持下游只使用 `content`：将 digest/即时推送的输入改为 prompt 字段白名单构造，排除评分摘要、内部控制字段和私有元数据；验证压缩后的正文仍进入下游 `content`，且不引入 `compressed_content` 或状态字段。

## 4. 原文去重兼容

- [ ] 4.1 在有效压缩前计算并持久化 `_source_content_hash`，扩展存储层去重键以优先比较原文指纹，并验证新抓取的相同原文能匹配已压缩的历史条目。
- [ ] 4.2 为没有 `_source_content_hash` 的历史 fetch 文件保留现有 link/title/content 回退逻辑，并验证历史读取、精确去重和 RapidFuzz 近似去重不因字段缺失失败。
- [ ] 4.3 验证 `_source_content_hash` 永不进入评分、digest 或即时推送 prompt，且该私有字段不改变下游对 `content` 的读取契约。

## 5. 回归验证与文档

- [ ] 5.1 扩展 `tests/test_flow.py` 与相关测试，覆盖完整正文、阈值边界、最低分数注入、压缩覆盖/回退、日志、批次 id 校验、原文哈希去重及下游 prompt 白名单；运行 `./.venv/bin/pytest -q tests/test_flow.py tests/test_digest_token_limit.py tests/test_push_time.py` 并通过。
- [ ] 5.2 使用 AI 和 Investment 的真实长正文样本人工比对压缩前后主体、时间、数字、来源、条件与不确定性；记录任何不安全压缩并确认回退或 prompt 调整后才启用默认阈值。
- [ ] 5.3 更新 `README.md` 和 `docs/tech-spec.md`，说明新的压缩阈值、完整正文评分、最低分数门槛、同名 `content` 覆盖、原文去重指纹、日志格式和超大单条处理策略，并验证配置示例与模型字段一致。
