## Why

当前 `llm.fallback` 只换模型名，仍走主接口的 `baseUrl` 和 API Key。主供应商整站超时或鉴权失败时，换型号救不了评分、快讯和汇总。需要让兜底带上自己的地址和凭据，成为第二套 OpenAI 兼容端点。

## What Changes

- **BREAKING**：`llm.fallback` 从可选字符串改为可选对象，必须同时声明 `model`、`baseUrl`、`apiKeyName`。三项都必填，不继承主接口。旧的 `fallback: grok-4.5` 不再合法。
- 运行期：主模型按既有重试结束后，若已声明兜底块，用该块的地址、钥匙和型号再 `post` 恰好一次。不因型号或三元组与主模型相同而跳过。
- 主模型缺 Key 仍在发请求前 `ValueError`，兜底轮不到。主模型 `401` 仍会打兜底那一枪。轮到兜底却缺自己的 Key 时，就地 `ValueError`。
- 启动探测、不粘滞、不跨档、成功只打日志、业务调用点签名：保持现有约定。
- 仓库 `config.yaml` 与 README / 技术规格中的 `llm.fallback` 说明一并改成对象形态。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `llm-fallback-model`: 兜底从「同接口备用名」改为「独立端点」（自有型号、地址、凭据）；取消「同名视为未配置」；补上兜底缺 Key 的失败表现。主目录 `openspec/specs/` 仍空，现有契约在未归档变更 `add-llm-fallback-model`。

## Impact

**配置**

- `src/config.py`：`LLMConfig.fallback` 改为可选嵌套对象
- `config.yaml`：现有字符串写法改为对象；部署时必须同步改配置，否则启动校验失败

**代码**

- `src/llm.py`：`call_llm()` 的兜底那一枪改打另一套 URL / Authorization / model；缺兜底 Key 时抛 `ValueError`
- 业务调用点与 `_check_tier_available()` 不改签名

**测试**

- `tests/test_flow.py`：配置校验、跨端点请求、缺 Key、同名仍打、探测仍不走兜底

**文档**

- `README.md`、`docs/tech-spec.md`：去掉「三档共用同一 baseUrl/Key」「同名视为未配置」
