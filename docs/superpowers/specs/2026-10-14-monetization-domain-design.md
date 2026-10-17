# Monetization domain 设计

## 目标

新增 `Monetization` domain，从非正式内容（个人言论、经验分享、自媒体）中聚合个人或小团队通过互联网、AI 赚钱的方法，并在评分和汇总两个阶段判断可行性，每天随定时汇总推送。

## 决策

- 非正式内容的限制只靠 prompt 判断，不做信源白名单。
- 归类冲突时变现优先：主要信息是"怎么赚到钱"（收入、渠道、获客、定价）就归 `Monetization`，AI 只是手段时不归 `AI`。
- 可行性在两个阶段都要判断：评分阶段把不可行的内容压到 `min_score` 以下，汇总阶段每条单独写可行性评估。
- 不走即时推送。评分照常用 0-100 分，只有达到 `filter.min_score` 的条目才进每日汇总。
- domain 键名为 `Monetization`（与 `AI`、`Investment` 的大小写一致），prompt 目录名为 `monetization`。

## 配置与代码

- `config.yaml` 的 `llm.prompts.domains` 在 `Investment` 之后新增 `Monetization`，只配 `domain_standard`、`score_standard`、`digest`。
- `src/config.py`：`DomainPromptConfig.immediate_push` 改为可选，默认 `None`。
- `src/main.py`：即时推送按 domain 分组后，跳过没有配置 `immediate_push` 的 domain。
- `sources.add` 新增以下信源，category 统一为 `Monetization`：

| title | xmlUrl |
|---|---|
| V2EX 分享创造 | https://www.v2ex.com/feed/create.xml |
| V2EX 独立开发者 | https://www.v2ex.com/feed/isv.xml |
| V2EX 创造者 | https://www.v2ex.com/feed/starter.xml |
| V2EX 商业模式 | https://www.v2ex.com/feed/business.xml |
| V2EX 奇思妙想 | https://www.v2ex.com/feed/ideas.xml |
| V2EX 创业组队 | https://www.v2ex.com/feed/meet.xml |
| V2EX AI SaaS 产品推荐 | https://www.v2ex.com/feed/aisaas.xml |
| V2EX 搜索引擎优化 | https://www.v2ex.com/feed/seo.xml |
| Pieter Levels | https://levels.io/rss/ |
| Justin Jackson | https://justinjackson.ca/feed |
| Niche Pursuits | https://www.nichepursuits.com/feed/ |
| Creator Science | https://www.creatorscience.com/feed |
| DecoHack 独立产品灵感周刊 | https://decohack.com/feed |
| HN mentions MRR | https://hnrss.org/newest?q=MRR |
| Reddit - SideProject | https://www.reddit.com/r/SideProject/.rss |
| Reddit - Entrepreneur | https://www.reddit.com/r/Entrepreneur/.rss |

以上信源已于 2026-10-14 验证可访问，且不在 `resources/rss.opml` 中。X 和新的微信公众号暂无可用公开源，不纳入本次范围。Reddit 有频率限制，先观察抓取日志，不改抓取逻辑。

## Prompt

### `prompts/score/monetization/domain_standard.md`

主要信息是个人或小团队通过互联网、AI 赚钱的方法、案例、渠道和收入数据，例如独立开发、SaaS、内容创作与自媒体、AI 工具与服务、电商与出海、SEO 流量站、接单与咨询。内容形态是个人言论、经验分享、社区讨论或自媒体文章；正式新闻报道和机构研报不属于本领域。主要信息是"怎么赚到钱"时归入本领域，即使其中用到了 AI。

### `prompts/score/monetization/score_standard.md`

按可行性和信息密度分档：

- 90-100：有完整可复制的路径和真实数据（启动成本、获客渠道、收入或转化数据、时间投入），个人或小团队可直接上手。
- 80-89：路径清晰、有部分真实数据，或对某个变现渠道有扎实的复盘与拆解。
- 70-79：提供了可行的思路、渠道或工具，但数据或细节不完整。
- 60-69：只有想法或简短讨论，缺少验证。
- <60：需要大资本、牌照或较大团队规模；灰产或违规；只晒收入不讲方法；卖课引流和软文；纯情绪或闲聊。

### `prompts/digest/monetization/digest.md`

每条由三部分组成：

1. 做法概述：讲清赚钱的方式、目标用户、获客渠道和已披露的收入数据。
2. 可行性评估：启动成本、所需技能、获客难度、变现周期、主要风险、可复制性，最后给出对个人或小团队是否值得尝试的明确结论。
3. 来源。

同一种变现方式的多条内容合并为一条。具体写法沿用 `prompts/digest/investment/digest.md` 的结构约定（数据不编造、口径不明时写明）。

## 文档

- README：更新领域列表、配置示例、新增 domain 步骤（`immediate_push` 变为可选）和 prompt 目录树。
- `docs/tech-spec.md` 和 `docs/plan.md` 当前不存在，本次不新建。

## 测试

- 不带 `immediate_push` 的 domain 配置能通过校验。
- 未配置 `immediate_push` 的 domain 即使有高分条目也不触发即时推送。
- 现有测试全部通过。
