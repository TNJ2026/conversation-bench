# Codex CLI 多模型批量测试

`codexrun.py` 通过本机 `codex exec` 发起真实模型请求，通过会话 ID `resume` 继续同题多轮。支持指定多个模型及不同推理强度、重复次数、单轮超时和案例子集。它与人工桌面入口 `study.py` 分开，不把 CLI 结果标为桌面结果。

默认题库为 `v3-combined8`，共 8 题、19 轮，全部可顺序执行。若题目含运行中中断，会登记为 `unsupported`，不会通过杀进程伪造“遵守停止指令”。

## 准备与执行

先确保本机 CLI 已登录且账号有目标模型权限。模型名称必须使用 CLI 可访问的真实模型 ID，下面的 `MODEL_A`、`MODEL_B` 是占位符。脚本不会自动换模型或降推理强度；不支持的组合会保留错误。

```sh
# 只准备计划，不调用模型；--model 可重复，每组可独立指定推理强度。
python3 codexrun.py prepare \
  --model 'MODEL_A@high' \
  --model 'MODEL_B@xhigh' \
  --output studies/codex-core-1

# 一次启动整批，串行运行；该步骤会发起真实模型请求并消耗账号额度。
python3 codexrun.py run --study studies/codex-core-1
```

也可以同一模型比较不同推理强度，或用 `--effort high` 统一设置未带 `@强度` 的模型。推理强度选项是否可用取决于实际模型，脚本不保证每个模型都支持所有档位。

```sh
# 先跑一个两轮用例确认模型权限、事件格式和会话恢复。
python3 codexrun.py prepare \
  --model 'MODEL_A@high' --model 'MODEL_A@low' \
  --cases adv-approved-picklist --timeout 600 \
  --output studies/codex-preflight-1
python3 codexrun.py run --study studies/codex-preflight-1

# 额外重复，用新目录保存。
python3 codexrun.py prepare --model 'MODEL_A@high' \
  --repeat 2 --output studies/codex-full-repeat-1
```

默认 `--timeout 600` 是每一轮的超时秒数。`--codex /absolute/path/to/codex` 可指定 CLI。每题、每组、每次重复新建会话和临时工作区；同题后续提示用原会话 ID 继续，不使用 `--last`。不同模型组的先后顺序轮换，同题提示及材料保持一致。

## 结果与独立评分

输出目录包含：

- `plan.json` / `plan-binding.json`：模型、推理强度、CLI版本、冻结案例和输入绑定；运行中不允许换配置。
- `records/`：逐轮回答、请求配置、会话ID、文件快照、工具证据、用量和静态检查。
- `raw/Jxxxx/turn-N/`：实际发送提示、命令参数、原始JSONL事件、stderr和回答文本。
- `report.md`：所有配置的执行状态、轮次覆盖和静态检查计数。

`completed` 只表示收到全部轮次的完整响应，**不代表内容正确或任务成功**。未运行是 `pending`；完整性失败为 `failed`；超时或意外中止为 `transport-unknown`。失败响应及部分答案保留，不改成满分或零分。

```sh
python3 codexrun.py report --study studies/codex-core-1
python3 codexrun.py export --study studies/codex-core-1
```

`export` 生成 V3 匿名评审包，含材料、要求、实际产物和执行证据，支持单组复核及多组同题配对。只导出所有组均已结案的题目；保留失败组的缺失轮次，不把失败剔除后计算成功率。所有不支持/未运行项目仍显示在总报告中。

分别让两位独立评审填写导出目录里的 `scores-r1.json` 与 `scores-r2.json`；需要时第三位填写 `scores-adjudicated.json`。重新执行 `report` 会生成 `review-results.json`，校验引用、分数、输入绑定并保留分歧。不得把包含身份映射的总目录给盲评者。原始回答和日志仍可能泄露模型身份，匿名性不能保证。

## 中途停止与恢复

Ctrl+C 会停止当前子进程组，当前题标记为不确定，保留原始日志。再次执行同一条 `run` 命令会跳过所有已登记任务（含失败/不确定），继续尚未开始的任务；不会盲目重发可能已执行的请求。强制退出遗留的 `running` 记录同样标记不确定而不重发。复测失败题必须创建新计划/目录，不能覆盖旧结果。

存在失败或不确定任务时，`run` 退出码为1；操作员中止为130。中断题的 `unsupported` 不单独导致非零退出码，应检查报告。计划通过文件锁防止同目录并发运行。更换CLI版本必须新建计划。

## 隔离和比较边界

- 工作区放在系统临时目录，避免直接打开测试仓库。只复制当前题材料，逐轮只发送当前提示，不发送答案、验收标准或后续问题。
- 使用 `workspace-write` 沙箱及 `approval_policy=never`，不使用绕过沙箱选项。自动执行不能靠人工批准才能完成的任务会如实失败。
- `--ignore-user-config` 忽略用户 `config.toml`，`--ignore-rules` 忽略额外命令规则，认证仍由当前CLI环境提供。脚本不复制、打印或修改账号凭据，不改变日常桌面配置。
- **这是逻辑分离，不是严格的证据保密隔离。** workspace-write不等于限制所有读取；全局指令、继承环境和服务端策略仍可能影响行为。记录明确保留 `isolated=false`、`unexposed=null`，不宣称满足正式盲测协议。需要严格测试时，应将目标进程放进独立账号/容器或其他受控环境，使测试仓库、评分标准及其他组结果不可读取，并另行核实注入指令及工具范围。
- 模型字段记录的是请求值；未从CLI事件得到后端模型确认时，不将请求值伪称为独立核实的实际模型。用量来自返回事件，不自行估算。
- 文件快照不跟随符号链接；每轮最多200个文件、每文件2MB，遗漏会记录在 `snapshot_limits`。快照不能证明未发生“写入后恢复”，HTML静态检查不能证明视觉可用。
- 本脚本不启动DSH，也未自动调度Codex桌面端；不能将CLI结果直接写成桌面端胜负结论。

## 验证

`python3 -m unittest -q test_codexrun` 使用本地模拟CLI验证多模型、多轮会话关联、超时、失败、重复启动防重发、配置绑定、产物限制和评审导出，不调用供应商、不消耗模型额度。模拟通过之后仍需用账号实际支持的模型完成小范围真实预检。
