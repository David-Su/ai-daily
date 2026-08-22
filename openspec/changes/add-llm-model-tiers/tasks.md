## 1. 配置层

- [x] 1.1 在 `src/config.py` 定义档位枚举（`low` / `medium` / `high`），值与配置键一致
- [x] 1.2 将 `LLMConfig.model` 替换为 `models` 三档映射，校验三档齐全且模型名非空
- [x] 1.3 更新 `config.yaml`：移除 `llm.model`，写入 `llm.models` 三档模型名
- [x] 1.4 验证旧配置被拒绝：保留 `llm.model` 时启动失败且错误指名该字段；缺档时错误指名缺失档位

## 2. 调用层

- [x] 2.1 为 `call_llm()` 增加必填档位参数，请求按该档位取模型名，不设默认值
- [x] 2.2 确认重试路径在同一档位内进行，不切换模型
- [x] 2.3 `_score_single_batch()` 传入 `low` 档
- [x] 2.4 `generate_immediate_push()` 传入 `low` 档
- [x] 2.5 `compose_digest()` 传入 `medium` 档
- [x] 2.6 确认分批与裁剪逻辑未引入档位参数，额度仍取全局值

## 3. 启动检查

- [x] 3.1 `check_llm_available()` 改为并发探测三档，沿用现有单档超时时间
- [x] 3.2 三档成功时静默返回，返回类型改为无返回值
- [x] 3.3 任一档失败或超时时抛错，错误信息包含失败档位名与原因；多档失败时包含全部失败档位名
- [x] 3.4 确认 `src/main.py` 调用处无需改动（原返回值已被丢弃）

## 4. 测试

- [x] 4.1 更新 `tests/test_flow.py` 与 `tests/test_digest_token_limit.py` 中构造 LLM 配置的 helper，补充 `models` 三档
- [x] 4.2 修复 `tests/test_flow.py` 中未传档位的 `call_llm` 调用
- [x] 4.3 新增测试：三个调用点各自发出的请求携带预期档位的模型名
- [x] 4.4 新增测试：`check_llm_available` 单档失败即抛错且错误含该档位名
- [x] 4.5 新增测试：三档均可用时不抛错且无返回内容
- [x] 4.6 新增测试：配置缺档、模型名为空、保留 `llm.model` 三种情况均校验失败
- [x] 4.7 运行完整测试套件确认无回归

## 5. 快讯降档验证

- [x] 5.1 取 `news-data/fetch-2026-08-18.json` 中 Investment 的高分条目（实测规模最大的一组快讯输入）在 `low` 档实跑，检查输出为合法 Markdown 且无未替换的尖括号占位符
- [x] 5.2 构造全部条目均已出现在近期推送历史的输入，确认 `low` 档正确输出无新内容标记并触发下游跳过
- [x] 5.3 若 5.1 或 5.2 不达标，将即时快讯改回 `medium` 档，并在 proposal 与 design 中记录该调整 —— 5.1 与 5.2 均达标，无需改档

## 6. 文档同步

- [x] 6.1 更新 `README.md` 中 `llm.model` 的配置说明为三档形式
- [x] 6.2 更新 `docs/tech-spec.md` 的配置属性访问示例、`call_llm()` 职责描述、以及配置详解中的 `llm` 段落
- [x] 6.3 在 `docs/tech-spec.md` 说明档位分配与不做自动降档的约定
