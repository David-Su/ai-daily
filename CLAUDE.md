# AI 每日资讯推送系统

AI 驱动的 RSS 新闻聚合与分领域推送系统，支持 400+ 信息源，使用 LLM 批量评分筛选，按 domain 生成 AI / Investment 等汇总，并推送到 Discord/飞书/Gmail。

当前阶段：MVP 已完成，支持 RSS 抓取、HTML 转 Markdown、分领域 LLM 评分、即时推送、定时汇总、Gmail SMTP 和本地归档。

## 技术栈

- 语言：Python 3.10+
- 框架：asyncio
- 依赖：feedparser, aiohttp, croniter, markdownify, markdown, python-dotenv
- 构建：pip
- 测试：pytest

## 开发规则

1. 任何代码改动如果与 docs/ 下的文档不一致，必须同步更新对应文档
2. 产品决策变更（功能取舍、交互调整、设计修改）和任务进度写入 docs/plan.md 的 `## 技术决策` 和 `## 开发进度`
3. 不确定的产品问题先问用户，不要自行决定
4. 敏感信息（API Keys、Webhook URLs）通过环境变量管理，不硬编码
5. config 有更新需要即时更新对应文档 `docs/tech-spec.md` 中的`## 配置详解`
6. 新增或修改 domain prompt 时，同步更新 README 和技术规格中的 prompt 路径说明
7. 代码生成规范:
    - 代码美观、精简与易读性是优先级最高
    - 不需要考虑特别极端的情况
    - 遵守Python代码规范

## 文档索引

- 使用说明 → [README.md](README.md)
- 技术架构 → [docs/tech-spec.md](docs/tech-spec.md)