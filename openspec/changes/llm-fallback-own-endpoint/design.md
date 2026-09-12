## Context

动机见 [proposal.md](proposal.md) - Why。需求契约见 [specs/llm-fallback-model/spec.md](specs/llm-fallback-model/spec.md)。

约束现状：

- `LLMConfig.fallback` 现在是 `Optional[NonEmptyStr]`。`call_llm()` 只把 payload 里的 `model` 换成这个字符串，`url` 与 `Authorization` 闭包在主接口上。
- 比较「有没有可用兜底」时只看 `fallback != model`。同名就跳过。
- API Key 只在 `call_llm()` 入口读一次 `llm.apiKeyName`；缺了直接 `ValueError`，兜底轮不到。`401` 不可重试，主模型一轮结束后仍会打兜底。
- `config.yaml` 已是字符串 `fallback: grok-4.5`，与主接口同属 OpenRouter。不改配置则新 schema 无法启动。
- 未归档变更 `add-llm-fallback-model` 把契约钉成「同接口备用名」。本次改的是那份契约，不是另起能力。
- `ConfigModel` 为 `extra="forbid"`、冻结。嵌套对象可以复用现有 `baseUrl` 校验与 `EnvVarName`。

## Goals / Non-Goals

**Goals:**

- 把兜底收成一块可选配置，写了就三项齐全，运行期那一枪换齐 URL、Key、型号。
- 入口仍只查主模型 Key；兜底 Key 只在真正要打那一枪时查。
- 测试能断言兜底请求的地址和 Authorization 与主模型不同（在两者配置不同时）。

**Non-Goals:**

- 不做字符串/对象双格式兼容。
- 不按档位各配兜底，不引入非 OpenAI 协议。
- 不加运行期超时、不改可重试状态码、不做粘滞。
- 启动探测仍不碰兜底，包括不预检查兜底环境变量是否存在。

## Decisions

### `fallback` 是嵌套对象，不是三个平行字段

备选是 `fallbackModel` / `fallbackBaseUrl` / `fallbackApiKeyName`。

选嵌套的理由：三项同生共死。平行字段很难表达「整块可省略，写了就全要」，也更容易只改型号、漏改地址，退回同接口换名。

实现：新增与主接口同形的小模型（`model`、`baseUrl`、`apiKeyName`），`LLMConfig.fallback: Optional[...] = None`。`baseUrl` 走现有 HTTP URL 校验并去尾斜杠；`apiKeyName` 走 `EnvVarName`。不写 `fallback` 键则为 `None`。

### 拒绝字符串，不做 union

备选是 `str | FallbackConfig`，字符串视为只换型号、继承主接口。

不做 union 的理由：那正是本次要废掉的语义。双格式会让文档和测试永远解释「这两种不一样」。破坏是一次性的：代码与 `config.yaml` 同一次提交。

### 那一枪换齐 URL / Header / model，不做相同判断

备选是继续只换 `model`，或三元组完全相同时跳过。

`request_once` 需要能带目标地址和鉴权，不能闭包主接口的 `url`/`headers`。是否打兜底只看：开关为真，且 `fallback` 对象存在。用户已选定「就算相同也打」，省掉同名/同三元组分支。

Key 的检查点保持「谁马上要 POST，谁就查自己的钥匙」：主模型在入口；兜底在决定打那一枪之后、`post` 之前。缺兜底 Key 抛与主模型缺 Key 相同的 `ValueError`，不把主模型的 HTTP 错误原样抛回。

### 成功日志带两边地址

型号可以相同，只打模型名分不清切到了哪。日志带档位、两边型号、两边 `baseUrl`。仍不走 `notify_llm_errors`。

## Risks / Trade-offs

**配成与主接口完全相同** → 主模型打满后多一枪空转。用户接受，不在运行期拦截。

**兜底 Key 要到第一次运行期失败才发现** → 与「探测不验兜底」一致。缓解：缺 Key 的报错带环境变量名。

**主模型悬挂时兜底仍轮不到** → `session.post` 仍无超时。本次不加。缓解：启动探测仍有超时。

**评分的 `response_format` 会带到兜底供应商** → 对方若不支持 JSON mode，那一枪会失败。不为此分流 payload。

## Migration Plan

- 代码与 `config.yaml` 必须同一次落地。只更代码时，现有字符串 `fallback` 会让启动校验失败。
- 文档示例改为对象；「同接口」「同名视为未配置」删掉。
- 回滚：恢复字符串字段与旧 `call_llm()`，配置改回一行型号。
