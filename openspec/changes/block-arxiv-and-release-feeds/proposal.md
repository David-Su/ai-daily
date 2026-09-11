## Why

AI 日报和快讯要偏时事（监管、产品发布、商业落地），不要学术预印本和软件版本说明。现有订阅把 arXiv 日更和 GitHub Releases 整包送进评分：工作日一次可灌入上千条论文摘要，OpenClaw 一类 changelog 单条可达十余万字，既抬高 token 账单，又把第 5、6 条写成论文簇或补丁说明。源层屏蔽即可兑现口味，不必先改评分流水线。

## What Changes

- 用现有 `sources.block_domains` 屏蔽 `*.arxiv.org`，使 `rss.arxiv.org` 与 `arxiv.org` 上的论文 RSS 不再进入抓取。
- 用现有 `sources.block` 按 xmlUrl 屏蔽当前 OPML 中全部 GitHub `releases.atom` 源（含 OpenClaw / Codex / Claude Code / Gemini CLI / LangChain / Zed 及 RSS 阅读器类）。
- **保留** `github.blog/changelog` 产品公告源；它们是 GitHub 官方产品新闻，不是版本文件。
- 不改 `merge_sources` 算法，不新增 URL 后缀匹配，不改 OPML 同步逻辑；周日远端覆盖 OPML 后，屏蔽配置仍然生效。
- 改写 AI 评分标准与 AI 汇总 prompt：选题以时事为准，论文预印本和软件版本说明不得作为日报/快讯条目；Hacker News 等漏网论文帖按同一标准处理。
- 不改 Investment 专用 prompt（论文会在源层消失）；不改即时推送格式；不在本次变更中压缩正文或调整 token 上限。

## Capabilities

### New Capabilities

- `current-events-source-filter`: 在抓取前屏蔽学术预印本源和 GitHub Releases 源，并让 AI 评分/汇总把时事作为选题标准，从而不再把论文簇和版本说明写成日报或快讯。

### Modified Capabilities

<!-- 当前仓库没有已发布的主 spec；行为契约由上述新能力承载。 -->

## Impact

- `config.yaml`：扩展 `sources.block` 与 `sources.block_domains`。
- `docs/tech-spec.md`、`README.md`：配置示例与源屏蔽说明与 `config.yaml` 同步。
- `prompts/score/ai/score_standard.md`、`prompts/digest/ai/digest.md`：时事选题要求；digest 样稿中以论文为主体的示范需一并改成时事口径。
- `tests/test_flow.py` 或相邻测试：断言 arXiv 域名与 `releases.atom` 不出现在 `merge_sources()` 结果中，且 GitHub Changelog 博客仍保留。
- 不改 `src/config.py` 的屏蔽语义，除非现有测试需要补断言。
