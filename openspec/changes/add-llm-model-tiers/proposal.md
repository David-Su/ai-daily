## Why

当前所有 LLM 调用共用一个 `llm.model`，评分、快讯、汇总三类任务不论难易都跑在同一个模型上。实测这三类任务的加权成本分布极不均衡（汇总约占 63%、评分约 22%、快讯约 15%），而其中评分的输出只是 100 条 × 约 37 字符的紧凑 JSON、快讯是短文，两者都不需要最强模型。按任务难度分配模型可以在不改动上下文策略的前提下降低约 12% 的账单。

## What Changes

- **BREAKING** 移除 `llm.model`，改为 `llm.models` 三档配置（`low` / `medium` / `high`），每档只声明模型名。不提供兼容分支，旧配置将因 `extra="forbid"` 直接启动失败并报错。
- `call_llm()` 新增必填 `tier` 参数（枚举），调用点显式声明所需档位；不提供默认值，避免新增调用点隐式落到某一档。
- 档位分配：评分与即时快讯用 `low`，定时汇总用 `medium`。`high` 保留槽位但当前无调用点，作为汇总质量不满意时的升档备选。
- `check_llm_available()` 改为并行检查全部三档：成功静默返回，任一档失败即抛出带档位名的错误并中断启动。返回类型由 `str` 变为 `None`。
- 不引入失败自动降档：高档调用失败不会静默回落到低档，以免推送质量不可预测。
- 上下文额度（`max_prompt_chars`、`digest_max_input_tokens`）保持全局，不随档位变化。分批与裁剪逻辑因此无需感知档位。

## Capabilities

### New Capabilities
- `llm-model-tiers`: LLM 模型档位配置与选择——三档模型声明、调用点按档位取模型、启动时全档位可用性检查、以及明确排除的自动降档行为。

### Modified Capabilities

（无。`openspec/specs/` 下暂无既有能力。）

## Impact

**配置**
- `config.yaml`：`llm.model` → `llm.models.{low,medium,high}`
- `src/config.py`：`LLMConfig.model` 字段替换，需要档位枚举与三档齐全的校验

**代码**
- `src/llm.py`：`call_llm()` 签名新增 `tier`；`score_batch`（经 `_score_single_batch`）、`generate_immediate_push`、`compose_digest` 三个调用点各自声明档位；`check_llm_available()` 改为并行检查三档
- `src/main.py`：`check_llm_available()` 返回值本已被丢弃，调用处无需改动

**测试**
- `tests/test_flow.py`：`call_llm("test prompt")` 会因 `tier` 必填而失败；构造 `LLMConfig` 的 helper 需要 `models` 字段
- `tests/test_digest_token_limit.py`：同上，config helper 需要 `models` 字段
- 需新增：档位到模型的映射断言、`check_llm_available` 单档失败即中断且错误含档位名

**文档**（项目规则要求代码与文档同步）
- `README.md`：`llm.model` 的配置说明
- `docs/tech-spec.md`：`config.llm.model` 属性访问示例、`call_llm()` 职责描述、配置详解中的 `llm` 段落

**风险**
即时快讯是唯一直达用户且不可撤回的输出路径，其 prompt 要求五步内部推理与严格 Markdown 格式，且 `[NO_NEW_CONTENT]` 标记被用作控制流分支。降到 `low` 档需要用真实数据验证格式完整性与标记触发的正确性，而非上线后依赖用户发现。
