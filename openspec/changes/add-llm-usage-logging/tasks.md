## 1. 日志行为测试

- [x] 1.1 在 `tests/test_flow.py` 复用 `_install_llm_http()` 与标准输出捕获，补充主模型响应的测试用例，覆盖完整嵌套及扩展 `usage`、缺失字段、显式 `null` 和零 token；断言单行格式与原样正文，并先运行用例确认当前实现缺少日志而失败。
- [x] 1.2 补充兜底和启动探测用例，验证实际请求模型与档位；评分解析失败用例走真实 `call_llm()` 和 HTTP 桩，验证 usage 日志先于评分失败日志；使用原有请求断言确认错误响应不生成 usage 日志、重试和兜底次数保持原样。

## 2. 单点日志接入

- [x] 2.1 在 `src/llm.py` 的 `request_once()` 解析响应 JSON 后、读取正文前，用现有 `print()` 和 `compact_json()` 输出 `tier.value`、`model_name` 和 `data.get("usage")`；运行新增用例及现有 LLM 请求相关测试确认通过，并检查差异仅增加日志、无文件写入或调用契约变更。

## 3. 技术说明

- [x] 3.1 在 `docs/tech-spec.md` 的 LLM 模块说明中补充日志格式、原始 usage、缺失值与错误响应的计量边界，并说明启动探测同样计入且 low 档不能精确区分评分和快讯；对照规格审阅，并运行 `openspec-cn validate add-llm-usage-logging --strict` 确认一致。
