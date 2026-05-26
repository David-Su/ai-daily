## TODO

当前待办

- [ ] 日志系统，保存到文件，push和fetch分开，
- [ ] 分领域日报格式持续优化：AI 参考 appso / xiaohu / ai gap，Investment 强化投资含义和风险提示
  - [ ] 优先级顺序
  - [ ] 美化排版
- [ ] 添加更多信息源，如 TechCrunch、GitHub Trending
- [ ] 允许fetch链接中的内容对信息进行扩展
- [ ] 增强配置校验：启动时检查启用 domain 的评分标准、digest prompt 和推送环境变量

长期待办

- [ ] 增加图片/信息图
- [ ] 推送到知乎 / 小红书 / 网站

## 技术决策

| 决策 | 方案 | 原因 |
|------|------|------|
| 定时调度 | croniter | 专业、准确、自动跨天处理 |
| 数据格式 | JSON | 结构清晰、易处理、支持嵌套 |
| 推送文件 | Markdown+YAML | 人工可读、Frontmatter 元数据 |
| 循环模式 | asyncio.gather | 简单、无锁、Pythonic |
| LLM 评分 | 批量 JSON | 减少 API 调用次数 |
| 状态追踪 | 文件时间戳 | 无需外部数据库 |
| RSS延迟防护 | fetch_lookback_minutes | 防止RSS延迟导致漏读 |
| LLM异常通知 | 调用方统一上报 | 避免批次级刷屏，同时保留关键异常通知 |
| Gmail推送 | SMTP + App Password | 不引入额外依赖，适合个人邮箱接收推送 |
| 分领域内容生产 | `activity_domains` + domain prompt | 同一抓取池可同时产出 AI、Investment 等不同口径摘要 |
| LLM接口 | OpenAI 兼容 `/chat/completions` | 方便切换 DashScope、OpenRouter、OpenAI 等兼容服务 |
| LLM重试 | `max_retries` + 指数退避 | 降低临时 429/5xx 对抓取流程的影响 |

## 开发进度

**2026-05-26**
- 同步说明文档到最新代码：README、技术规格、协作说明和环境变量示例已对齐分领域评分/摘要、Gmail 默认配置、`tests/test_flow.py` 测试入口和当前数据目录结构
- 明确当前 LLM 配置使用 OpenAI 兼容接口，默认示例为 DashScope 兼容模式、`OPENAI_API_KEY`、`max_retries` 和分批评分参数
- 补充 domain 配置说明：`activity_domains` 控制启用领域，`domains[].score_standard` 和 `domains[].digest` 分别控制评分标准与汇总 prompt

**2026-05-14**
- 新增 Gmail SMTP 推送平台：支持 App Password、收件人环境变量、cc/bcc 与默认 Gmail SMTP 配置
- 优化 Gmail 邮件正文：同时发送纯文本 Markdown 与渲染后的 HTML，避免 Gmail 中只显示原文
- 更新 `config.json`、`.env.example`、README 与技术规格文档中的 Gmail 推送配置说明
- 补充 Gmail 推送平台配置校验、邮件构建、发送调用与工厂注册测试

**2026-03-08**
- 新增 LLM 异常通知：`compose_digest`、`generate_immediate_push` 与 `score_batch` 的错误会通过现有推送渠道发送简单告警
- 优化批量评分容错：`score_batch` 在批次返回数量不匹配时会按 `link` 回收可用结果，并聚合错误返回给调用方
- 移除 `generate_immediate_push` 的 fallback 内容，生成失败时由调用方告警并跳过本次即时推送
- 新增启动前 LLM 可用性检查：主程序在启动 fetch/push 双循环前先探测 LLM 接口，失败则直接退出
- 修复 pytest 中遗留的旧推送平台命名问题，将相关测试更新为当前 `feishu` 实现

**2026-03-03**
- 采用 MIT 许可开源项目，添加 LICENSE 文件
- 更新 RSS 源说明，致谢 BestBlogs 项目

**2026-03-02**
- 修复RSS延迟漏读问题：新增 fetch_lookback_minutes 参数，fetch时读取过去更长一段时间的RSS条目进行去重
- 新增飞书 Webhook 推送支持：使用卡片消息格式，支持 Markdown 渲染
- 新增测试脚本 test_fetch_lookback.py
- 更新 cleanup_old_files 函数支持 notify 文件清理

**2026-03-01**
- 优化评分系统：通过更新 score 提示词提升评分质量
- 即时推送去重：新增 notify-*.md 文件存储即时推送，LLM 调用时传入近期推送上下文避免重复
- 汇总推送优化：新增 push_context_days 配置，汇总推送时传入近期推送上下文进行去重
- 修复 score 类型问题：确保 LLM 返回的 score 为整数类型
- 完善测试脚本：添加上下文参数和保存功能

**2026-02-28**
- 初始化项目，MVP 已完成，支持 RSS 抓取、LLM 评分、定时推送、即时推送。
