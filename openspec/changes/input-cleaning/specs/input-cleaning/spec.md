## Purpose

在抓取内容送进 LLM 评分与汇总之前，去除图片标记、广告与推广残留、导购链接等多余成分，在不改变正文语义的前提下减少 token 消耗。

## ADDED Requirements

### Requirement: 图片标记清除

系统在构造 LLM 输入时 SHALL 移除内容中的 Markdown 图片标记，被移除图片周围的正文语义 SHALL 保持完整。

#### Scenario: 含图正文送评分

- **WHEN** 一条抓取内容包含 Markdown 图片标记与正文段落
- **THEN** 评分输入中不含任何图片标记，且正文段落文字完整保留

### Requirement: 推广与广告残留清除

系统在构造 LLM 输入时 SHALL 移除可判定为推广或广告残留的成分，包括推广签名行与导购链接， SHALL NOT 删除正文中的事实性语句。

#### Scenario: 含导购链接的正文送汇总

- **WHEN** 一条内容包含导购链接与推广签名
- **THEN** Digest 输入中不含该链接与签名，且事件事实描述完整保留

### Requirement: 清洗覆盖评分与推送输入

清洗 SHALL 同时作用于评分输入与推送输入（定时汇总与即时快讯），存盘的原始内容 SHALL 保持清洗前的原样。

#### Scenario: 同一条目评分与汇总一致清洗

- **WHEN** 同一条目分别进入评分与 Digest 输入构造
- **THEN** 两处输入中的噪音成分均被清除，且存盘文件中的原始内容保持不变

### Requirement: 链接字段不受影响

清洗 SHALL NOT 改动条目的 `link` 字段，日报考证用的来源链接 SHALL 与清洗前完全一致。

#### Scenario: 清洗后来源可考证

- **WHEN** 清洗后的条目进入 Digest 生成
- **THEN** 输出的来源链接与该条目原始 `link` 字段逐字符一致
