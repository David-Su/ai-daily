## Why

预定模型在运行中下线或持续报错时，评分、快讯、汇总会一起停。当前三档常配成同一个模型名，又没有同接口的备用名，一次故障就是整条链路中断。需要一个可选的兜底模型，让运行中的调用在主模型耗尽重试后还能再试一次。

## What Changes

- 新增可选配置 `llm.fallback`：一个模型名，三档共用，仍走现有的 `baseUrl` 与 API Key。不写该项时行为与现在完全一致。
- `call_llm()` 每次先打该档主模型，按现有重试策略打完；仍失败且允许兜底时，用 `llm.fallback` 再请求恰好一次。这一次失败则本次调用失败。
- 进程不粘滞：下一次调用仍先打主模型。
- 不跨档：`low` 失败不会改打 `medium` / `high`。兜底换的是同接口下的另一个模型名，不是另一档，也不是第二套供应商。
- 启动探测关掉兜底，继续只验三档主模型。评分、快讯、汇总三个业务调用点不改。
- 切到兜底并成功时只打日志，不当作调用失败去发异常通知。
- 本次不加请求超时，也不改 401 / 缺 Key 的特殊处理。

## Capabilities

### New Capabilities

- `llm-fallback-model`: 可选的同接口兜底模型——配置声明、运行中主模型耗尽后再打一枪、启动探测不走兜底、以及与「不跨档回落」的边界。

### Modified Capabilities

（无。`openspec/specs/` 下暂无既有能力。档位与「不跨档」的既有约定写在已完成变更 `add-llm-model-tiers` 中，本次不改那些需求。）

## Impact

**配置**

- `config.yaml`：`llm` 下新增可选 `fallback`
- `src/config.py`：`LLMConfig` 增加可选字段；`models` 三档字典保持不变

**代码**

- `src/llm.py`：`call_llm()` 内部读取 `llm.fallback`，新增默认开启的 `allow_fallback`；`_check_tier_available()` 关闭兜底
- `src/main.py` 与三个业务调用点不改签名、不传新参数

**测试**

- `tests/test_flow.py`：构造配置的 helper 在未写 `fallback` 时应仍合法；需覆盖主模型成功不切、重试耗尽后切一次、兜底失败即失败、启动探测不切、缺省与同名不切

**文档**

- `README.md`、`docs/tech-spec.md` 的 `llm` 配置说明需同步可选 `fallback` 与运行期切换约定