# Conversation Bench

AI短会话体验对照测试工具（V2/V3），Python 3.9+，无第三方依赖。桌面对照支持DSH、ChatGPT和Hermes；`dshrun.py`、`codexrun.py` 可通过 DSH SDK 或 Codex CLI 顺序执行同一套题目。长会话自动实验（V6–V15、历史查回插件、有界交付）已于2026-11-17移除。

- [完整中文说明](README.zh-CN.md)

```sh
python3 study.py list
python3 study.py create --output studies/new-round/plan.json
python3 -m unittest -q
```

`studies/`保存本地原始记录和报告，不随源码上传；不要把`completed`当作任务成功。

## 会话质量测试 V3

题库为去提示修订的常规20题（45轮，`--suite v3-standard20`，也是默认值），独立核对事实准确性、指令遵守和实用性。新评审包包含原始材料、实际产物和干预证据，按轮双评并单列完成情况。见[覆盖范围、记录与评分方法](docs/conversation-evaluation-v3.md)。题目说明见[常规20题](docs/standard20.md)。

## Codex CLI 批量运行

新增 `codexrun.py`，支持指定多个模型与推理强度，默认使用常规20题，全部可顺序自动执行。先 `prepare` 冻结计划，再 `run` 批量调用；每题独立会话，同题逐轮恢复，保存原始事件与失败记录。见[使用说明与隔离边界](docs/codex-cli-batch.md)。CLI逻辑分离不等于严格保密隔离，也不代表桌面端测试。
