## Context

动机见 [proposal.md](proposal.md) - Why。行为契约见 [specs/current-events-source-filter/spec.md](specs/current-events-source-filter/spec.md)。

现状约束：

- 源合并已经是 `base_opml + add - block - block_domains`。`block_domains` 的 `*.example.com` 匹配该域名及其子域；`block` 只做 xmlUrl 精确匹配。
- `resources/rss.opml` 每周日被远端列表覆盖，改 OPML 本身无法持久。
- 配置模型禁止未知字段；本次只扩展已有列表，不新增配置键。
- AI digest 目前用整节规则把预印本收成「不超过 2 条的论文簇」，评分标准把「带性能数字的框架」放在 80–89 分。源挡掉之后，这两处仍会把 HN 论文帖和漏网 changelog 写成条目。

## Goals / Non-Goals

**Goals:**

- 屏蔽生效点停在 `merge_sources()`，抓取、评分、汇总代码路径不感知「论文」或「releases」。
- 用域名规则覆盖 arXiv，避免周日同步引入新的 cs.* 分类源时复发。
- 用精确 xmlUrl 覆盖当前 OPML 里的 `releases.atom`，同时留下 GitHub Changelog 博客。
- 把 AI 评分/汇总的选题要求改成「时事」，而不是追加「禁止以前那种论文簇」的补丁句。

**Non-Goals:**

- 不新增 URL 路径/后缀匹配（例如「凡是 `/releases.atom` 都挡」）。那要改配置模型和合并逻辑，留给同步真的又灌进新 Releases 源时再做。
- 不改 Investment prompt、即时推送版式、token 上限或正文压缩。
- 不屏蔽 Hacker News 关键词源、DeepMind / Google Research 博客。

## Decisions

### 1. arXiv 用 `block_domains: "*.arxiv.org"`，不用逐条 xmlUrl

`*.arxiv.org` 同时匹配 `arxiv.org` 与 `rss.arxiv.org`，覆盖当前 OPML 中的 cs.AI / cs.LG / cs.CL / cs.CV / cs.DB / stat.ML 以及 `http://arxiv.org/rss/...` 的旧主机名。

备选是把每条 arXiv xmlUrl 写入 `block`。列表会在远端 OPML 增加新分类时漏网，且与已有 `*.proceedings.mlr.press` 的学术屏蔽方式不一致。

不把 `arxiv.org` 写进 `block_domains` 的无通配形式：实现里非 `*.` 前缀走 `fnmatch`，`arxiv.org` 不能匹配 `rss.arxiv.org`。

### 2. Releases 用 `block` 精确 xmlUrl，保留 Changelog 博客

当前 OPML 中需写入 `sources.block` 的地址：

- `https://github.com/openclaw/openclaw/releases.atom`
- `https://github.com/openai/codex/releases.atom`
- `https://github.com/anthropics/claude-code/releases.atom`
- `https://github.com/google-gemini/gemini-cli/releases.atom`
- `https://github.com/modelcontextprotocol/specification/releases.atom`
- `https://github.com/modelcontextprotocol/servers/releases.atom`
- `https://github.com/astral-sh/uv/releases.atom`
- `https://github.com/zed-industries/zed/releases.atom`
- `https://github.com/oven-sh/bun/releases.atom`
- `https://github.com/biomejs/biome/releases.atom`
- `https://github.com/langchain-ai/langchain/releases.atom`
- `https://github.com/DIYgod/RSSHub/releases.atom`
- `https://github.com/DIYgod/RSSHub-Radar/releases.atom`
- `https://github.com/yang991178/fluent-reader/releases.atom`
- `https://github.com/Ranchero-Software/NetNewsWire/releases.atom`
- `https://github.com/FreshRSS/FreshRSS/releases.atom`

不得 block：

- `https://github.blog/changelog/feed/`
- `https://github.blog/changelog/label/copilot/feed/`

已存在的 `https://github.com/openclaw/openclaw/commits/main.atom` 保持不变。

备选是 `block_domains: "*.github.com"`，会误伤大量非 Releases 源。备选二是新增 `block_url_suffixes`；本次不扩展配置面。

实现时从 `resources/rss.opml` 再扫一遍 `releases.atom`，若有上表未列的条目一并加入，避免文档与仓库漂移。

### 3. 只改 AI 评分标准与 AI digest，用正向要求替换论文簇规则

`prompts/score/ai/score_standard.md`：高分例子继续绑定官方发布、监管、落地；70 分档是已上线的实用产品/工具新闻，而不是论文摘要或版本文件里的功能列表。预印本和软件版本说明归入低于 `min_score` 的档位，除非该条本身已是时事报道。

`prompts/digest/ai/digest.md`：删除「论文簇不超过 2 条 / 鼓励合并预印本」整段，改成选题必须是时事；论文或版本说明只可给已经成立的时事条目当佐证。第五节样稿里以预印本为主体的那条示范改成时事结构，避免模型继续模仿论文簇。

同一要求只声明一次，不追加「不要再生成以往那种论文簇」的禁令句。

不改 `immediate_push` 模板：热点门槛走评分标准；预印本不再因自评数字打到 90 分。

### 4. 测试挂在现有 `merge_sources()` 契约上

扩展 `tests/test_flow.py` 中已有的源合并测试，或新增紧邻用例：对真实 `get_config()` 合并结果断言 arXiv 主机与 `releases.atom` 不在列表中，且两条 Changelog 博客仍在。不 mock 一整份 OPML，以免与 `config.yaml` 脱节。

Prompt 文本不写快照测试；任务里做人工对照：digest 不再包含论文簇规则，评分标准含时事口径。

## Risks / Trade-offs

- **周日同步新增尚未列入的 `releases.atom`** → 精确 block 漏网。缓解：本次扫全量 OPML；若复发，再单独立项做后缀匹配。
- **HN / 媒体转载论文仍进入评分** → 源层挡 95%，漏网靠评分与 digest 的时事要求。不因此屏蔽 HN。
- **OpenClaw / Claude Code 若只有 Releases、没有媒体稿，日报会少一条工具更新** → 符合本次口味；InfoQ 等媒体稿仍可进入。
- **UBASE / KVMem 一类工程报告不再出现** → 接受。WeatherNext、微信开源等已有官方博客或 IT之家，不受影响。
- **与 `compact-content-during-scoring` 并行** → 超长 changelog 进系统的机会下降，压缩变更的净收益变小，但不阻塞其实现；两变更不改同一配置键。

## Migration Plan

部署即改配置与 prompt，无需迁移历史 `fetch-*.json`。已归档的论文条目仍可能在 `context_days` 窗口内作为汇总上下文出现一到两天，随后自然滚出。回滚：从 `config.yaml` 去掉新增 block 项，并还原两个 prompt 文件。
