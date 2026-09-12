## 1. 配置

- [x] 1.1 在 `src/config.py` 把 `LLMConfig.fallback` 从可选字符串改为可选嵌套对象（`model` / `baseUrl` / `apiKeyName` 三项均必填，`baseUrl` 走现有 HTTP 校验，`apiKeyName` 走 `EnvVarName`）；`models` 与 `model_for()` 不变。同步把仓库 `config.yaml` 的字符串 `fallback` 改成对象，且 `baseUrl`/`apiKeyName` 与主接口不同。用 `AppConfig.model_validate` 确认：未写 `fallback` 仍通过；完整对象通过；字符串、缺任一项、空白字段均被拒绝
- [x] 1.2 同步 `README.md`、`docs/tech-spec.md`：示例改为对象形态，删掉「三档共用同一 baseUrl/Key」「同名视为未配置」；核对「不跨档」仍在，且未把 `fallback` 写进 `models`

## 2. 运行期切换

- [x] 2.1 调整 `src/llm.py` 的 `call_llm()`：兜底那一枪换齐 URL、Authorization、model；是否打只看 `allow_fallback` 与 `fallback` 对象是否存在，不做同名/同三元组跳过；成功日志含档位、两边型号、两边 `baseUrl`；主模型缺 Key 仍在入口失败且不打兜底；兜底缺 Key 在 `post` 前 `ValueError` 且不发出该次 HTTP。在 `tests/test_flow.py` 覆盖：主模型成功未请求兜底地址、可重试打满后切到不同地址/Key 一次成功、`404`/`401` 立刻切、兜底失败不再打、未配置不切、型号相同仍打、连续两次都先打主模型地址、`medium` 失败请求名是兜底型号不是 `low`、主模型缺 Key 无 HTTP、兜底缺 Key 为 `ValueError` 且无兜底 HTTP
- [x] 2.2 保持 `_check_tier_available()` 传 `allow_fallback=False`，三个业务调用点仍只传 `prompt` 与 `tier`。在 `tests/test_flow.py` 确认：已配置兜底端点时某档主模型探测失败仍中断启动，且探测请求不含兜底型号与兜底地址；评分 / 快讯 / 汇总在主模型失败后会打到兜底端点
