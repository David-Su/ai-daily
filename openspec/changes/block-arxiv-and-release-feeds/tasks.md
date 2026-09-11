## 1. 源屏蔽配置

- [ ] 1.1 从 `resources/rss.opml` 列出全部 `releases.atom` xmlUrl，与 design 中的清单对齐后写入 `config.yaml` 的 `sources.block`；保留已有的 dev.to 与 OpenClaw commits 项。
- [ ] 1.2 在 `config.yaml` 的 `sources.block_domains` 增加 `*.arxiv.org`，保留现有 `*.proceedings.mlr.press` 与 `*.youtube.com`。
- [ ] 1.3 确认 `github.blog/changelog/feed/` 与 `github.blog/changelog/label/copilot/feed/` 未出现在 `block` 中。

## 2. AI 提示词

- [ ] 2.1 改写 `prompts/score/ai/score_standard.md`：高分绑定时事；预印本与软件版本说明归入低于 `min_score` 的档位，除非该条本身是产品/监管/商业报道。同一要求只写一次，不追加禁令补丁。
- [ ] 2.2 改写 `prompts/digest/ai/digest.md` 选题规则：用时事标准替换「论文簇不超过 2 条」整段；论文或版本说明只可作为已成立时事条目的佐证。
- [ ] 2.3 将 digest 样稿中以预印本为主体的示范改成时事结构，使样稿与新选题规则一致。

## 3. 测试与文档

- [ ] 3.1 在 `tests/test_flow.py` 增加或扩展源合并断言：真实配置下 `merge_sources()` 不含 arXiv 主机与任何 `releases.atom`，且两条 GitHub Changelog 博客仍在。
- [ ] 3.2 运行 `pytest -q tests/test_flow.py` 并通过。
- [ ] 3.3 同步 `docs/tech-spec.md` 的配置示例与 `README.md` 中 `block` / `block_domains` 说明，使其与 `config.yaml` 一致；若 README 仍描述论文簇选题，改为时事口径。
