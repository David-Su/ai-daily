# Monetization Domain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `Monetization` domain，从非正式内容中聚合个人或小团队通过互联网、AI 变现的方法，评分与汇总两阶段判断可行性，只走每日定时汇总。

**Architecture:** `DomainPromptConfig.immediate_push` 改为可选，`run_fetch_job` 跳过未配置即时推送 prompt 的 domain；新增 `prompts/score/monetization/` 与 `prompts/digest/monetization/` 三个 prompt 文件并在 `config.yaml` 注册；`sources.add` 补 16 个变现相关信源；README 同步。

**Tech Stack:** Python 3.10, pydantic, pytest（`.venv/bin/python -m pytest`）

**Spec:** `docs/superpowers/specs/2026-10-14-monetization-domain-design.md`

## Global Constraints

- domain 键名为 `Monetization`，prompt 目录名为 `monetization`。
- `Monetization` 不配置 `immediate_push`；分数照常 0-100，达到 `filter.min_score` 才进汇总。
- 非正式内容的限制只靠 prompt 判断，不做信源白名单。
- 归类冲突时变现优先：主要信息是"怎么赚到钱"就归 `Monetization`。
- prompt 修改规范（CLAUDE.md）：同一要求只声明一次；写成明确要求，不写打补丁式的禁止。
- 代码美观、精简、易读优先；不新增兼容性代码。
- 每个 commit message 末尾加一行 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。
- 基线：当前有 5 个测试已失败（`tests/test_flow.py::test_call_llm_logs_usage` 4 个参数化用例因 temperature 0.8≠0.3，`tests/test_rejected_links.py::test_successful_omissions_and_unknown_domains_are_rejected_only_in_memory`），与本计划无关，不修复；验证时以"无新增失败"为准。

## File Structure

- Modify: `src/config.py` — `immediate_push` 可选；资源校验跳过 `None` 字段
- Modify: `src/main.py` — 即时推送跳过未配置 prompt 的 domain
- Create: `prompts/score/monetization/domain_standard.md`
- Create: `prompts/score/monetization/score_standard.md`
- Create: `prompts/digest/monetization/digest.md`
- Modify: `config.yaml` — 注册 domain、补充信源
- Modify: `tests/test_flow.py` — domain 列表断言、可选 immediate_push 的测试
- Modify: `README.md`

---

### Task 1: immediate_push 可选，未配置的 domain 不走即时推送

**Files:**
- Modify: `src/config.py:131-137`（`DomainPromptConfig`）、`src/config.py:367-398`（`_validate_local_resources`）
- Modify: `src/main.py:298-300`（`run_fetch_job` 热点筛选）
- Test: `tests/test_flow.py`

**Interfaces:**
- Produces: `DomainPromptConfig.immediate_push: Optional[str]`，默认 `None`；`run_fetch_job` 只对 `immediate_push` 非空的 domain 生成即时推送。

- [ ] **Step 1: 写失败测试**

在 `tests/test_flow.py` 的 `test_load_config_rejects_incomplete_domain_prompt_mapping` 之后加入：

```python
def test_domain_without_immediate_push_passes_validation(tmp_path):
    from src.config import _validate_local_resources

    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    del raw["llm"]["prompts"]["domains"]["AI"]["immediate_push"]
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

    config = _validate_local_resources(load_config(str(path)), ROOT)

    assert config.llm.prompts.domains["AI"].immediate_push is None
```

在 `test_fetch_job_excludes_unconfigured_domain_results` 之后加入：

```python
@pytest.mark.asyncio
async def test_fetch_job_skips_immediate_push_for_domain_without_prompt(
    tmp_path, monkeypatch
):
    import src.main as main_module

    config = _config()
    domains = dict(config.llm.prompts.domains)
    domain = next(iter(domains))
    domains[domain] = domains[domain].model_copy(update={"immediate_push": None})
    prompts = config.llm.prompts.model_copy(update={"domains": domains})
    llm = config.llm.model_copy(update={"prompts": prompts})
    _install_config(config.model_copy(update={"llm": llm}))

    raw_entry = {
        "title": "Hot entry",
        "link": "https://example.com/hot",
        "published": datetime.now(timezone.utc),
        "source": "Example",
        "content": "Hot content",
    }
    fetch_file = tmp_path / "fetch.json"

    async def fake_fetch_all_feeds(_sources, _cutoff):
        return [raw_entry]

    async def fake_score_batch(entries):
        return [
            {**entries[0], "domain": domain, "score": 100, "summary": "Hot", "tags": []}
        ], []

    async def fail_generate_immediate_push(*_args, **_kwargs):
        raise AssertionError("未配置 immediate_push 的 domain 不应生成即时推送")

    monkeypatch.setattr(
        main_module,
        "merge_sources",
        lambda: [{"xmlUrl": "https://example.com/feed"}],
    )
    monkeypatch.setattr(main_module, "fetch_all_feeds", fake_fetch_all_feeds)
    monkeypatch.setattr(main_module, "score_batch", fake_score_batch)
    monkeypatch.setattr(main_module, "get_fetch_file", lambda: str(fetch_file))
    monkeypatch.setattr(main_module, "cleanup_old_files", lambda **_kwargs: None)
    monkeypatch.setattr(main_module, "is_immediate_push_forbidden", lambda: False)
    monkeypatch.setattr(
        main_module, "generate_immediate_push", fail_generate_immediate_push
    )

    await run_fetch_job()

    assert [entry["domain"] for entry in read_entries(str(fetch_file))] == [domain]
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_flow.py -k "without_immediate_push or without_prompt" -v`
Expected: 两个用例都 FAIL（第一个报 `llm.prompts.domains.AI.immediate_push: Field required` 后 SystemExit，第二个触发 AssertionError）

- [ ] **Step 3: 实现**

`src/config.py` 的 `DomainPromptConfig`：

```python
class DomainPromptConfig(ConfigModel):
    """单个 domain 的 prompt 路径；未配置 immediate_push 的 domain 不走即时推送"""

    domain_standard: NonEmptyStr
    score_standard: NonEmptyStr
    digest: NonEmptyStr
    immediate_push: Optional[NonEmptyStr] = None
```

`src/config.py` 的 `_validate_local_resources` 中，路径解析和路径检查都跳过未配置字段：

```python
    prompt_fields = tuple(DomainPromptConfig.model_fields)
    prompt_domains = {
        key: item.model_copy(
            update={
                field_name: str(_resolve_path(path, config_dir))
                for field_name in prompt_fields
                if (path := getattr(item, field_name))
            }
        )
        for key, item in config.llm.prompts.domains.items()
    }
```

```python
    paths.extend(
        (f"llm.prompts.domains.{key}.{field_name}", path)
        for key, item in resolved.llm.prompts.domains.items()
        for field_name in prompt_fields
        if (path := getattr(item, field_name))
    )
```

`src/main.py` 的 `run_fetch_job`，把热点筛选限定在配置了即时推送的 domain：

```python
    hot_threshold = config.filter.hot_threshold
    no_content_marker = config.filter.no_content_marker
    immediate_domains = {
        domain for domain, prompts in config.llm.prompts.domains.items()
        if prompts.immediate_push
    }
    hot_entries = [
        e for e in scored
        if (e.get("score") or 0) >= hot_threshold and e.get("domain") in immediate_domains
    ]
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_flow.py -k "without_immediate_push or without_prompt" -v`
Expected: 2 passed

Run: `.venv/bin/python -m pytest -q`
Expected: 只有 Global Constraints 里列出的 5 个基线失败

- [ ] **Step 5: 提交**

```bash
git add src/config.py src/main.py tests/test_flow.py
git commit -m "feat: immediate_push 改为可选，未配置的 domain 不走即时推送"
```

---

### Task 2: Monetization 评分 prompt 与 domain 注册

**Files:**
- Create: `prompts/score/monetization/domain_standard.md`
- Create: `prompts/score/monetization/score_standard.md`
- Create: `prompts/digest/monetization/digest.md`（本任务先建占位最小可用版本，Task 3 写完整内容）
- Modify: `config.yaml`（`llm.prompts.domains`）
- Test: `tests/test_flow.py:367-410`

**Interfaces:**
- Consumes: Task 1 的可选 `immediate_push`
- Produces: `config.llm.prompts.domains` 顺序为 `["AI", "Investment", "Monetization"]`

- [ ] **Step 1: 更新测试断言（先失败）**

`tests/test_flow.py` 的 `test_config_interface_and_prompt_files` 改为：

```python
def test_config_interface_and_prompt_files():
    """验证 config.yaml 能通过模型校验，并检查当前启用 domain 的 prompt 文件都可访问。"""
    config = _config()

    prompts = config.llm.prompts
    assert Path(prompts.score_batch).exists()

    assert list(prompts.domains) == ["AI", "Investment", "Monetization"]
    for domain_config in prompts.domains.values():
        assert Path(domain_config.domain_standard).exists()
        assert Path(domain_config.score_standard).exists()
        assert Path(domain_config.digest).exists()
    assert prompts.domains["Monetization"].immediate_push is None
```

`test_declared_domain_order_controls_processing_order` 改为：

```python
def test_declared_domain_order_controls_processing_order():
    assert get_domain_order() == ["AI", "Investment", "Monetization"]
    assert sort_domains(["Monetization", "Investment", "AI"]) == [
        "AI", "Investment", "Monetization"
    ]
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_flow.py -k "prompt_files or domain_order" -v`
Expected: 2 failed（domain 列表不含 `Monetization`）

- [ ] **Step 3: 新建 `prompts/score/monetization/domain_standard.md`**

```markdown
主要信息是个人或小团队通过互联网、AI 赚钱的做法与结果：
- 变现方式：独立开发与 SaaS、AI 工具与服务、内容创作与自媒体、电商与出海、SEO 与流量站、模板与数字产品、接单与咨询。
- 经营环节：选品与需求验证、获客渠道、定价与付费转化、收入与成本数据、失败复盘。
- 内容形态：个人言论、经验分享、社区讨论帖、自媒体文章与个人 Newsletter。
- 交叉领域：文章用到了 AI、出海或某个平台，但主要信息是靠它赚到钱的方法或结果时，归入本领域。
*例子：V2EX 帖子分享用 Claude 做 Chrome 插件三个月月入 2000 美元；Reddit 用户复盘小众 SaaS 从 0 到 1 万美元 MRR 的获客渠道；公众号作者拆解 AI 生成绘本在海外平台的销售数据；独立开发者博客总结 SEO 工具站的广告与订阅收入。*
```

- [ ] **Step 4: 新建 `prompts/score/monetization/score_standard.md`**

```markdown
按对个人或小团队的可行性和信息密度打分：
- 【90-100分】完整可复制的变现路径，附真实数据（启动成本、获客渠道、收入或转化数据、时间投入），一个人或三五人团队能直接上手。
*例子：开发者公开一款 AI 插件的选题、上线渠道、定价和半年收入曲线；博主复盘 SEO 工具站从建站到月入 3000 美元的流量来源与成本。*
- 【80-89分】路径清晰、有部分真实数据，或对某个变现渠道、平台规则有扎实的拆解与复盘。
*例子：独立开发者总结在 Product Hunt 发布前后的转化数据；经验帖拆解某海外平台对数字产品的分成与审核规则。*
- 【70-79分】给出可行的变现思路、渠道或工具，细节或数据不完整。
*例子：社区讨论帖整理几种用 AI 接外包单的渠道；作者分享一个需求点和初步验证方式，尚无收入数据。*
- 【60-69分】只有想法或简短讨论，没有验证。
*例子：「有没有人用 AI 做过小红书代运营？」类提问帖；一句话的副业点子。*
- 【<60分】个人或小团队做不了、或不值得做的内容：依赖大额资本、牌照、渠道关系或较大团队规模；灰产、违规或损害平台与他人权益；只晒收入不讲方法；卖课引流、带货软文、招募下线；纯情绪或闲聊。
*例子：「融资 5000 万做 AI 硬件」；「批量养号薅平台补贴」；「月入十万的秘密，进群领取」；「副业好难，不想干了」。*
```

- [ ] **Step 5: 新建 `prompts/digest/monetization/digest.md` 最小版本**

先写一行占位，保证 config 校验通过，Task 3 整体替换：

```markdown
根据今日素材生成 {date} 的变现日报。素材：{entries}
```

- [ ] **Step 6: 在 `config.yaml` 注册 domain**

在 `llm.prompts.domains.Investment` 之后加入：

```yaml
      # 不配置 immediate_push：变现内容时效性弱，只进定时汇总
      Monetization:
        domain_standard: prompts/score/monetization/domain_standard.md
        score_standard: prompts/score/monetization/score_standard.md
        digest: prompts/digest/monetization/digest.md
```

- [ ] **Step 7: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_flow.py -k "prompt_files or domain_order" -v`
Expected: 2 passed

Run: `.venv/bin/python -m pytest -q`
Expected: 只有 5 个基线失败

- [ ] **Step 8: 检查渲染后的评分 prompt**

Run:
```bash
.venv/bin/python -c "from src.config import initialize_config; from src.llm import _build_batch_prompt; c=initialize_config(); print(_build_batch_prompt(c.llm, [{'id':1}])[:3000])"
```
Expected: `domain_list` 为 `["AI","Investment","Monetization"]`，`### Monetization` 段落在两个标准里都出现。

- [ ] **Step 9: 提交**

```bash
git add prompts/score/monetization prompts/digest/monetization config.yaml tests/test_flow.py
git commit -m "feat: 新增 Monetization domain 评分标准"
```

---

### Task 3: Monetization 汇总 prompt

**Files:**
- Modify: `prompts/digest/monetization/digest.md`（整体替换 Task 2 的占位）

**Interfaces:**
- Consumes: `compose_digest` 传入的模板变量 `{date}`、`{count}`、`{entries}`、`{recent_push_context}`、`{context}`（见 `src/llm.py:598-605`），名称必须一致。

- [ ] **Step 1: 写入完整 prompt**

`prompts/digest/monetization/digest.md` 全文：

````markdown
你是一位面向独立开发者和副业从业者的变现日报编辑。你的读者有一定技术或内容能力，想找到一个人或三五人团队能做、值得投入时间的赚钱方式。你的任务是把今天社区帖子、个人博客和自媒体里零散的变现经验，整合成一篇**看完就能判断要不要试**的日报。

## 一、每条的结构

每条由「标题」「做法」「关键数据」「可行性」「来源」五部分组成，缺一不可。

### 1. 标题

陈述句，写清「谁用什么方式赚到了什么」，有收入数字时放进标题。

### 2. 做法

一个自然段，直接接在标题之后，不加小标题。3 到 5 句话讲清：卖什么、卖给谁、从哪里获客、怎么收钱。用到 AI 或某个平台时，写清它在哪个环节起作用。

### 3. 关键数据

- 只写可核验的量化事实：收入、MRR、用户数、转化率、启动成本、投入时长、定价。
- 每项格式为：`- **数字或指标**：一句话说明它是什么、统计的是多长时间。`
- 素材里只有 1 到 2 项数字时就只列 1 到 2 项；素材没有任何数字时写 `- 素材未披露量化数据`。数字必须出自素材，收入类数字都是作者自述，在「可行性」里说明可信度。

### 4. 可行性

格式为 `**可行性**：` 后接一个自然段，不超过 200 字，依次覆盖：

- 启动成本：钱和时间。
- 所需技能：写代码、设计、写作、运营、某种语言或行业知识。
- 获客难度：渠道是公开可用的，还是依赖作者已有的粉丝、关系或时机。
- 变现周期：多久能看到第一笔收入。
- 主要风险：平台规则变化、同质化竞争、合规、作者自述数据不可核验。

段末用一句话给出结论，以「**结论**：」开头，在「值得一试」「有条件可试」「不建议跟进」三者中选一个，并说明决定它的那一个因素。

### 5. 来源

- 格式为：`🔗 **来源**：[来源名 · 简短说明](链接) | [来源名](链接)`
- **链接必须逐字符复制素材中的 `link` 字段**。

## 二、选题与整合

1. **数量**：输出 3 到 8 条，按素材成色决定，够格的少就写少。
2. **入选标准**：个人或小团队能复制的变现方式，且素材给出了做法细节。`score` 仅供参考，不决定入选与排序。
3. **排序**：「值得一试」在前，「有条件可试」其次，「不建议跟进」只在它能帮读者避开一个流行误区时才收录，放最后。同一结论内按数据完整度排序。
4. **聚合**：同一种变现方式（例：多个开发者都在做 AI 简历工具）合并为一条，在「关键数据」里分别列出各案例，在「可行性」里写它们共同说明的竞争程度。不同变现方式不合并。
5. **新旧剥离**：与已推送清单对照，同一案例没有新增数据的不选；碎片化信息只用于判断某个方式此前是否出现过。

## 三、语言与风格

- 简练中文，短句为主，像有经验的同行在复盘，不像营销号。
- 收入数字照实陈述，用「作者自述」标明来源口径，不用「躺赚」「暴富」「轻松月入」这类词。
- 中英文之间加空格；产品名、平台名保留原文大小写。
- 引号统一使用「」。

## 四、输出约束

- 只输出正文，不要引导语、说明和结尾总结。
- 只允许两种标题：`#` 用于日报标题，`###` 用于每条标题（带键帽数字，如 `### 1️⃣`）。「关键数据」「可行性」用加粗标签。
- 日报标题为 `# 💰 AI Daily 变现精选 | {date}`。

## 五、样稿（仅示范结构，事件与链接均为虚构）

```markdown
# 💰 AI Daily 变现精选 | 2026-07-31

### 1️⃣ 独立开发者用 AI 做 Shopify 商品描述插件，上架 4 个月 MRR 2800 美元

作者把 GPT 接口封装成 Shopify 应用，帮中小卖家批量生成多语言商品描述。用户来自 Shopify 应用商店的自然搜索，作者没有投广告。按生成条数分三档月付，免费档限 20 条。AI 负责生成，作者的工作量集中在提示词调优和商店的 SEO 关键词上。

**关键数据**：

- **MRR 2800 美元**：上架第 4 个月，作者自述。
- **付费转化率约 6%**：安装用户到付费用户。
- **API 成本约占收入 12%**：按当月账单估算。

**可行性**：启动成本低，开发约 3 周、只有 API 费用；需要会写前后端和读懂 Shopify 应用审核规则。获客依赖应用商店搜索，同类插件已有十余款，新进入者要找更细的品类切入。第一笔收入在上架后第 3 周。主要风险是平台推出官方 AI 描述功能，以及收入数据为作者自述。**结论**：有条件可试，取决于能否找到一个现有插件没覆盖的品类。

🔗 **来源**：[V2EX 分享创造 · 作者复盘](https://example.com/v2ex/t/1)
```

## 六、今日素材（共 {count} 条）

entries 是一个 JSON 数组，包含社区帖子、个人博客和自媒体内容，每个对象包含 `title`、`source`、`link`、`score`、`tags`、`published`、`content` 字段。部分条目抓取不到正文，`content` 只有一句摘要，这类条目只能作为补充来源，不单独成条。

```json
{entries}
```

## 七、参考数据

### 近 N 天已推送事件清单（仅供查重）

<RECENT_PUSH_CONTEXT BEGIN>
{recent_push_context}
<RECENT_PUSH_CONTEXT END>

### 近几天已处理过的碎片化信息（供背景参考）

```txt
{context}
```

---

现在开始生成日报，遵守以上全部规则。
````

- [ ] **Step 2: 检查模板变量能被填充**

Run:
```bash
.venv/bin/python -c "
from src.llm import load_prompt
p = load_prompt('prompts/digest/monetization/digest.md', count=1, entries='[]', context='', recent_push_context='', date='2026-10-14')
import re; print(re.findall(r'\{[a-z_]+\}', p))"
```
Expected: `[]`（没有残留的未填充变量）

- [ ] **Step 3: 运行测试**

Run: `.venv/bin/python -m pytest -q`
Expected: 只有 5 个基线失败

- [ ] **Step 4: 提交**

```bash
git add prompts/digest/monetization/digest.md
git commit -m "feat: 新增 Monetization 汇总 prompt"
```

---

### Task 4: 补充变现信源

**Files:**
- Modify: `config.yaml`（`sources.add` 末尾）
- Test: `tests/test_scoring_config_prompt.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_scoring_config_prompt.py` 末尾加入：

```python
def test_monetization_sources_are_merged(initialized_config):
    urls = {feed["xmlUrl"] for feed in merge_sources() if feed["category"] == "Monetization"}

    assert {
        "https://www.v2ex.com/feed/create.xml",
        "https://levels.io/rss/",
        "https://www.reddit.com/r/SideProject/.rss",
    } <= urls
    assert len(urls) == 16
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv/bin/python -m pytest tests/test_scoring_config_prompt.py::test_monetization_sources_are_merged -v`
Expected: FAIL（集合为空）

- [ ] **Step 3: 在 `config.yaml` 的 `sources.add` 末尾（`商界新闻` 之后）加入**

```yaml
    # 变现：个人与小团队的经验分享、社区讨论
    - title: V2EX 分享创造
      xmlUrl: https://www.v2ex.com/feed/create.xml
      category: Monetization
    - title: V2EX 独立开发者
      xmlUrl: https://www.v2ex.com/feed/isv.xml
      category: Monetization
    - title: V2EX 创造者
      xmlUrl: https://www.v2ex.com/feed/starter.xml
      category: Monetization
    - title: V2EX 商业模式
      xmlUrl: https://www.v2ex.com/feed/business.xml
      category: Monetization
    - title: V2EX 奇思妙想
      xmlUrl: https://www.v2ex.com/feed/ideas.xml
      category: Monetization
    - title: V2EX 创业组队
      xmlUrl: https://www.v2ex.com/feed/meet.xml
      category: Monetization
    - title: V2EX AI SaaS 产品推荐
      xmlUrl: https://www.v2ex.com/feed/aisaas.xml
      category: Monetization
    - title: V2EX 搜索引擎优化
      xmlUrl: https://www.v2ex.com/feed/seo.xml
      category: Monetization
    - title: Pieter Levels
      xmlUrl: https://levels.io/rss/
      category: Monetization
    - title: Justin Jackson
      xmlUrl: https://justinjackson.ca/feed
      category: Monetization
    - title: Niche Pursuits
      xmlUrl: https://www.nichepursuits.com/feed/
      category: Monetization
    - title: Creator Science
      xmlUrl: https://www.creatorscience.com/feed
      category: Monetization
    - title: DecoHack 独立产品灵感周刊
      xmlUrl: https://decohack.com/feed
      category: Monetization
    - title: HN mentions MRR
      xmlUrl: https://hnrss.org/newest?q=MRR
      category: Monetization
    - title: Reddit - SideProject
      xmlUrl: https://www.reddit.com/r/SideProject/.rss
      category: Monetization
    - title: Reddit - Entrepreneur
      xmlUrl: https://www.reddit.com/r/Entrepreneur/.rss
      category: Monetization
```

- [ ] **Step 4: 运行确认通过**

Run: `.venv/bin/python -m pytest tests/test_scoring_config_prompt.py -v`
Expected: 新用例 PASS，其余用例状态不变

- [ ] **Step 5: 提交**

```bash
git add config.yaml tests/test_scoring_config_prompt.py
git commit -m "feat: 补充 Monetization 信源"
```

---

### Task 5: README 同步

**Files:**
- Modify: `README.md:10`、`README.md:85-105`、`README.md:358-363`、`README.md:426-440`

- [ ] **Step 1: 核心功能（第 10-11 行）**

```markdown
- **分领域评分**：LLM 按 `AI`、`Investment`、`Monetization` 等启用领域批量评分，并写入 `domain`、`score`、`tags`、`summary`。
- **即时推送**：配置了 `immediate_push` 的领域，达到 `hot_threshold` 的热点内容会立即生成快讯，避免错过高价值信息。
```

- [ ] **Step 2: 配置示例（`Investment` 映射之后）**

```yaml
      Monetization:
        domain_standard: prompts/score/monetization/domain_standard.md
        score_standard: prompts/score/monetization/score_standard.md
        digest: prompts/digest/monetization/digest.md
```

- [ ] **Step 3: 添加新的领域（第 360-363 行）**

```markdown
1. 在 `prompts/score/<domain>/domain_standard.md` 写领域归类标准，在 `prompts/score/<domain>/score_standard.md` 写评分标准。
2. 在 `prompts/digest/<domain>/digest.md` 写该领域的汇总 prompt。
3. 需要即时推送时，在 `prompts/immediate/<domain>/immediate_push.md` 写该领域的即时推送 prompt。
4. 在 `config.yaml` 的 `llm.prompts.domains` 增加以领域名为键的映射项，配置 `domain_standard`、`score_standard`、`digest`，需要即时推送时再配置 `immediate_push`。
```

- [ ] **Step 4: 目录结构的 prompts 部分**

```text
├── prompts/
│   ├── immediate/
│   │   ├── ai/immediate_push.md
│   │   └── investment/immediate_push.md
│   ├── score/
│   │   ├── score_batch.md
│   │   ├── ai/domain_standard.md
│   │   ├── ai/score_standard.md
│   │   ├── investment/domain_standard.md
│   │   ├── investment/score_standard.md
│   │   ├── monetization/domain_standard.md
│   │   └── monetization/score_standard.md
│   └── digest/
│       ├── ai/digest.md
│       ├── investment/digest.md
│       └── monetization/digest.md
```

- [ ] **Step 5: 检查 README 里没有遗漏**

Run: `grep -n "Investment\|immediate_push" README.md`
Expected: 每处列出领域或说明 `immediate_push` 的地方都已包含 `Monetization` 或"可选"的表述。

- [ ] **Step 6: 提交**

```bash
git add README.md
git commit -m "docs: README 同步 Monetization domain"
```

---

### Task 6: 最终验证

- [ ] **Step 1: 全量测试**

Run: `.venv/bin/python -m pytest -q`
Expected: 只有 Global Constraints 里的 5 个基线失败，新增用例全部通过。

- [ ] **Step 2: 启动级配置校验**

Run: `.venv/bin/python -c "from src.config import initialize_config; c=initialize_config(); print(list(c.llm.prompts.domains), c.llm.prompts.domains['Monetization'].immediate_push)"`
Expected: `['AI', 'Investment', 'Monetization'] None`
