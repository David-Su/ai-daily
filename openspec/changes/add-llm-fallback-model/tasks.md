## 1. 配置

- [x] 1.1 在 `src/config.py` 的 `LLMConfig` 增加可选字段 `fallback: Optional[NonEmptyStr] = None`，`models` 字典与 `model_for()` 保持不变；用 `AppConfig.model_validate` 确认未写 `fallback` 的现有配置仍通过，空白或仅空白被拒绝且错误指到 `llm.fallback`
- [x] 1.2 在 `config.yaml` 的 `llm` 段（紧挨 `models`）增加可选 `fallback` 的注释示例，并同步 `README.md`、`docs/tech-spec.md` 的配置说明：三档共用、同一 `baseUrl`/Key、与当前档主模型同名视为未配置、不跨档；核对示例未把 `fallback` 写进 `models` 字典，且「不跨档」与「同接口备用名」分成两件事

## 2. 运行期切换

- [x] 2.1 在 `src/llm.py` 的 `call_llm()` 增加 `allow_fallback: bool = True`；主模型按现有 `max_retries` / `RETRYABLE_STATUS_CODES` 结束后，仅当开关为真、`llm.fallback` 有值且与当前档主模型名不同时，用同一 `baseUrl`/Key 再 `post` 恰好一次（不再重试）；成功则打印含档位、主模型名、兜底模型名的日志并返回内容，失败则抛与现有相同的 `RuntimeError`。在 `tests/test_flow.py` 覆盖：主模型成功不出现兜底名、可重试状态打满后切一次成功、`404` 立刻切一次、兜底失败不再打、缺省或同名不切、连续两次调用都先打主模型、`medium` 失败后请求名是 `fallback` 不是 `low`
- [x] 2.2 在 `src/llm.py` 的 `_check_tier_available()` 调用 `call_llm(..., allow_fallback=False)`；`_score_single_batch` / `generate_immediate_push` / `compose_digest` 的 `call_llm` 调用保持只传 `prompt` 与 `tier`。在 `tests/test_flow.py` 确认：已配置 `fallback` 时某档主模型探测失败仍中断启动且探测请求不含兜底名；三个业务调用点在主模型失败且备用名不同时会打到兜底