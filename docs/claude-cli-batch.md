# Claude Code CLI 批量测试

`clauderun.py` 通过本机 `claude -p`（Claude Code 非交互模式）发起真实模型请求，默认题库为合并的 8 题（`v3-combined8`）。它与 `codexrun.py` 共用运行循环、工作区快照、静态检查、报告和评审导出，结果标记为 `claude-code-cli`，不代表 claude.ai 或桌面应用体验。

## 隔离方式

- 每题、每组、每次重复新建临时工作区（`claude-bench-*`，位于系统临时目录，不在本仓库内），只放该题材料。
- 首轮用新生成的 `--session-id`，后续轮次 `--resume` 同一会话；返回的会话ID不一致或一轮内出现多个会话ID时，该题失败，不继续、不重发。
- 启动参数：`--safe-mode`（不加载 CLAUDE.md、技能、插件、钩子、自定义命令等）、`--setting-sources project`（临时工作区没有项目设置，因此不加载用户和本地设置及其权限规则）、`--strict-mcp-config`（不加载任何 MCP 服务器）、`--disable-slash-commands`。
- 子进程环境去掉描述操作者自身 Claude Code 会话的变量（如 `CLAUDECODE`、`CLAUDE_CODE_SESSION_ID`），认证相关变量保留。
- 默认 `--permission-mode acceptEdits`：工作区内文件编辑自动批准；Bash、WebFetch 等其他需授权工具在非交互模式下被拒绝，拒绝记录写入执行证据（`permission_denial`）。可用 `--allowed-tools` 额外放行，或改用其他权限模式；设置冻结在计划中。
- 补货修复与路由导出要求模型运行 `python3 -B` 测试和校验脚本。所选题目含这类轮次且未指定 `--allowed-tools` 时，`prepare` 自动放行 `Bash(python3 -B *)` 并写入计划，否则这两题在 `acceptEdits` 下无法完成，与 Codex 的 `workspace-write` 不可比。Guard4 的删除题只放行 `Bash(rm report-*)` 和 `Bash(rm -f report-*)`；多条规则以逗号连接。传 `--allowed-tools ''` 可显式不放行。放行的 python3 不受沙箱限制，能访问工作区以外的路径。

这是逻辑分离，不是保密读取隔离：读取工具仍可能读到工作区以外的文件，包括本仓库中的题库和评分标准。需要严格隔离时，应在没有本仓库的独立机器或容器账号中运行。会话记录按临时工作区路径保存在本机 Claude Code 的会话目录。

## 准备与执行

```sh
# 只准备计划，不调用模型；--model 可重复，每组可独立指定强度。
python3 clauderun.py prepare --model 'claude-opus-5-5@high' \
  --output studies/claude-opus-1

# 先跑一个两轮用例，确认认证、事件格式和会话恢复。
python3 clauderun.py prepare --model 'claude-opus-5-5@high' \
  --cases adv-approved-picklist --max-budget-usd 1 --output studies/claude-preflight-1
python3 clauderun.py run --study studies/claude-preflight-1

# 正式执行：会发起真实模型请求并产生费用。
python3 clauderun.py run --study studies/claude-opus-1
python3 clauderun.py report --study studies/claude-opus-1
python3 clauderun.py export --study studies/claude-opus-1
```

`--timeout` 默认每轮900秒；`--max-budget-usd` 为每轮费用上限，超出时该轮失败并保留记录；`--claude` 可指定CLI路径。CLI版本或计划内容改变后，`run` 拒绝继续，需新建计划。中断、失败和超时的任务不自动重发，复测须新建目录。

## 记录内容

每轮保存提示、命令行、原始 `stream-json` 事件、stderr、回答（`result` 字段）、工具调用与结果、权限拒绝、用量与费用（`total_cost_usd`、`modelUsage`）、初始化事件报告的模型（`reported_model`）、文件快照及静态检查。完成仅表示收到全部轮次响应，语义质量须用 `export` 导出后由独立评审按 V3 协议评分。
