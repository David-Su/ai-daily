## Purpose

在抓取前排除学术预印本源和 GitHub Releases 源，并让 AI 评分与汇总按时事选题，使日报和快讯不再以论文或软件版本说明为主体。

## ADDED Requirements

### Requirement: ArXiv feeds are excluded from fetch

系统 MUST 在合并订阅源时排除托管在 arXiv 域名上的 RSS 源，包括 `rss.arxiv.org` 与 `arxiv.org`。排除 MUST 在远端 OPML 同步覆盖本地源列表之后仍然生效，不得要求手工改写 OPML 才能保持屏蔽。

#### Scenario: Current arXiv category feeds never enter fetch

- **WHEN** 合并后的订阅源包含 `https://rss.arxiv.org/rss/cs.AI` 或 `http://arxiv.org/rss/cs.LG` 这类 arXiv RSS
- **THEN** `merge_sources()` 的结果中不包含这些 xmlUrl，抓取任务不会请求它们

#### Scenario: Weekly OPML sync cannot re-enable arXiv

- **WHEN** 周日源同步用远端 OPML 覆盖 `base_opml`，且覆盖后的文件再次列出 arXiv 源
- **THEN** 随后的源合并仍然排除这些源

### Requirement: GitHub Releases feeds are excluded from fetch

系统 MUST 在合并订阅源时排除当前已配置的 GitHub `releases.atom` 源。排除 MUST 按源地址精确匹配，不得把 `github.blog` 上的产品公告源一并排除。

#### Scenario: Known releases.atom feeds never enter fetch

- **WHEN** OPML 含有 `https://github.com/openclaw/openclaw/releases.atom` 或同仓库列表中的其他 `releases.atom`
- **THEN** `merge_sources()` 的结果中不包含这些 xmlUrl

#### Scenario: GitHub Changelog blog remains subscribed

- **WHEN** OPML 含有 `https://github.blog/changelog/feed/` 或 `https://github.blog/changelog/label/copilot/feed/`
- **THEN** 合并后的订阅源仍包含这些 xmlUrl，抓取与评分可继续消费它们

### Requirement: AI scoring prefers current events over papers and version notes

AI 领域评分标准 MUST 把监管、产品发布、商业与落地类时事作为高分依据。学术预印本、论文摘要，以及软件版本说明、alpha/nightly 发布笔记 MUST 不得仅因其中含有性能数字或功能列表而进入汇总门槛或热点门槛。Hacker News 等非 arXiv 源上的同类条目 MUST 适用同一标准。

#### Scenario: Preprint abstract stays below digest threshold

- **WHEN** 一条输入是论文预印本摘要，且没有伴随已落地产品、监管或商业事件
- **THEN** 其 AI 领域分数低于汇总最低分，该条不会进入定时汇总素材池

#### Scenario: Software release notes stay below digest threshold

- **WHEN** 一条输入是 GitHub 版本说明或工具补丁列表，且没有被媒体或官方产品渠道写成独立时事
- **THEN** 其 AI 领域分数低于汇总最低分，该条不会进入定时汇总素材池

#### Scenario: Official product news can still score high

- **WHEN** 一条输入是厂商或平台对产品可用性、定价、监管或重大发布的时事报道（包括 GitHub Changelog 博客）
- **THEN** 评分仍可按其时事重要性给分，不受「论文与版本说明」规则牵连

### Requirement: AI digest and hot push select current events

AI 汇总与即时快讯 MUST 只把时事写成条目。条目主体 MUST 不是论文预印本簇，也 MUST 不是软件版本说明。若剩余素材里出现论文或 changelog，只允许在已经成立的时事条目中作为佐证，且不得因此单独成条。

#### Scenario: Digest does not emit a paper-cluster item

- **WHEN** 当日剩余素材含有多篇指向同一技术问题的预印本或 HN 论文帖，且没有对应的产品、监管或商业时事
- **THEN** 生成的 AI 汇总不把这些论文合并或拆成独立条目

#### Scenario: Digest does not emit a version-notes item

- **WHEN** 当日剩余素材含有某工具的版本号、PR 列表或 changelog 正文，且没有对应的产品时事报道
- **THEN** 生成的 AI 汇总不以该版本说明作为独立条目

#### Scenario: Hot push does not fire on preprint self-report

- **WHEN** 一条预印本宣称重大实验室结果但没有官方产品或媒体时事背书
- **THEN** 该条不会仅凭自评达到热点阈值并触发即时快讯
