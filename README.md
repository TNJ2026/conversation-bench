# Conversation Bench

AI短会话体验对照测试工具（V3），Python 3.9+，无第三方依赖。桌面对照支持DSH、ChatGPT和Hermes；`dshrun.py`、`codexrun.py`、`clauderun.py` 可通过 DSH SDK、Codex CLI 或 Claude Code CLI 顺序执行同一套题目。长会话自动实验（V6–V15、历史查回插件、有界交付）已于2026-11-17移除。

- [完整中文说明](README.zh-CN.md)

```sh
python3 study.py list
python3 study.py create --output studies/new-round/plan.json
python3 -m unittest -q
```

`studies/`保存本地原始记录和报告，不随源码上传；不要把`completed`当作任务成功。

## 会话质量测试 V3

默认题库 `v3-combined20` 共 20 题、43 轮，五个测试目标各 4 题。可用 `--suite` 指定旧版或子题组。[题目分组](docs/combined20.md)

原始材料、产物和干预证据按轮交给独立评审，分别评价事实准确性、指令遵守和实用性。[会话测试 V3](docs/conversation-evaluation-v3.md)

## Claude Code CLI 批量运行

`clauderun.py` 在独立临时工作区中用 `claude -p` 逐题运行，关闭 CLAUDE.md、记忆、技能、插件、MCP 和用户权限规则，同题逐轮恢复同一会话，保存原始事件、工具调用、权限拒绝与费用。用法与隔离边界见[Claude Code CLI 批量测试](docs/claude-cli-batch.md)。

## Codex CLI 批量运行

`codexrun.py` 支持指定多个模型与推理强度，默认使用 Combined20，全部可顺序自动执行。先 `prepare` 冻结计划，再 `run` 批量调用；每题独立会话，同题逐轮恢复，保存原始事件与失败记录。见[使用说明与隔离边界](docs/codex-cli-batch.md)。CLI逻辑分离不等于严格保密隔离，也不代表桌面端测试。
