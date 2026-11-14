# 桌面会话体验对照测试 v2

[中文](README.zh-CN.md) | [English](README.md)

Python 3.9+，无第三方依赖。新版入口为 `study.py`。支持 DeepSeek Harness（`dsh`）、ChatGPT（`chatgpt`）和 Hermes（`hermes`）。包含六类场景，每类三个不同案例；默认两款应用共36次会话，也可单独测试一款（18次）或三款同题对照（54次）。提供逐轮提示、独立材料目录、产物快照、协议分组、对照报告和匿名文本评审导出。它是人工操作桌面应用的测试工具，不是模拟用户的自答脚本，也不自动点击应用或调用模型API。

## 加入 Hermes

新建计划时用 `--products` 选择应用，逗号分隔；不填写时仍使用原来的 `dsh,chatgpt`，旧计划和历史记录无需修改。

```sh
# 只测试 Hermes：18次会话
python3 study.py create --products hermes --output studies/hermes-desktop-1/plan.json
python3 study.py next --plan studies/hermes-desktop-1/plan.json
# DSH 与 Hermes 对照：36次会话
python3 study.py create --products dsh,hermes --output studies/dsh-hermes/plan.json
# 三款同题对照：54次会话
python3 study.py create --products dsh,chatgpt,hermes --output studies/three-apps/plan.json
```

计划已存在时直接运行 `next`，不要重复 `create`；工具不会覆盖已有计划。Hermes 同样使用下面的 `begin`、`submit`、`finish`、`report` 流程。每个案例在 Hermes 中新建独立会话，只绑定分配的材料目录，逐轮发送当前提示；记录实际模型、推理档位、权限与记忆设置。不要把完整用例或对方答案交给被测会话。运行中干预必须实际验证消息已发送给运行中的任务，不能把排队等候当作即时干预。

产品标签记录的是被测应用，不是模型名称。如果实际使用 Codex 或其他客户端，应在配置中明确记录，不把应用标签当作模型或客户端已经对齐的证明。

## 从这里开始

历史测试记录、过程材料和对比报告保存在项目之外的本地归档目录，不随源码上传。归档中的路径映射与校验清单用于追溯原始证据。

以下以新计划 `studies/new-round/plan.json` 为例。在终端执行：

```sh
git clone https://github.com/TNJ2026/conversation-bench.git
cd conversation-bench
python3 study.py create --output studies/new-round/plan.json
python3 study.py next --plan studies/new-round/plan.json
```

这会显示接下来该测试哪个应用、哪个案例和任务编号。按照输出，用真实编号和模型信息开始测试（下例 `J001` 仅为第一项）：

```sh
python3 study.py begin --plan studies/new-round/plan.json --job J001 \
  --model '填写实际模型及推理档位' --app-version '填写应用版本' \
  --permissions '填写权限' --plugins '填写插件' --memory '填写记忆设置' \
  --method desktop --isolated --unexposed
```

`--isolated` 声明使用独立新会话；`--unexposed` 声明目标未接触未来问题、验收标准及对方答案。只有实际做到才能填写。默认 `--method selftest`，避免把集中自答误认为正式测评。自测可保存但不会进入正式配对或匿名评审。

**测试执行者与被测AI必须分离。** 终端由你或独立测试执行者操作；不要把本README、脚本或完整案例交给被测AI，也不要让它自行生成测试记录。每个目标会话只收到当前轮提示词及分配的工作区。脚本只逐轮显示提示，并不能阻止有全盘权限的AI读取案例，访问隔离需由操作员保证。

## 完成一轮

1. `begin` 输出记录文件路径、目标工作区和第一轮提示。将目标应用绑定到该工作区，或告知该目录绝对路径。工作区位于相邻的 `conversation-bench-workspaces/`，仅含材料，不含用例和评分标准。
2. 复制当前提示到目标应用，真实等待并观察。用秒表或屏幕录制记录反馈、完成和操作时间。
3. 将回答正文单独保存为UTF-8文件，如 `/tmp/bench-answer.txt`。工具过程、额外追问、截图路径和异常另存 `/tmp/bench-notes.txt`。不要将工具日志混入字数核查正文。
4. 录入本轮，脚本随即显示下一轮提示：

```sh
python3 study.py submit \
  --record studies/new-round/records/J001.json \
  --answer /tmp/bench-answer.txt --notes /tmp/bench-notes.txt \
  --elapsed 48 --first-feedback 3 --active-seconds 12 \
  --corrections 0 --actions 2
```

数值仅为示例，必须替换为真实观测；未测量的参数直接省略，不能填0。时间单位为秒。`elapsed` 为发送至本轮结束，`first-feedback` 为首次有信息量的反馈，`active-seconds` 为人的操作耗时。`corrections` 不包括案例预定追问。相同记录第二次 submit 会写入下一轮，务必确认输出轮号，不重复提交同一答案。

暂时退出后，运行 `next --plan ...` 显示尚未提交的当前轮。每次提交原子保存；已提交内容不重跑、不覆盖。

## 中途干预案例

这类案例第一步会同时给操作员“开始任务”和“干预”两条指令。它们必须在桌面应用里实时发送：任务仍运行时，在首次写入前或5秒内（先发生者）发送停止指令。若先前任务已完成，本次干预实验无效，不要假装发生过打断。

把两条消息对应的响应按顺序一起写入首轮回答文件。备注记录发送干预、应用确认干预、后续调用和写入时点；区分已经在执行的写入完成与收到干预后新发起写入。

```sh
python3 study.py submit --record studies/new-round/records/J001.json \
  --answer /tmp/bench-answer.txt --notes /tmp/bench-notes.txt \
  --interruption-observed --interrupt-delay 1.5
```

`--interruption-observed` 只在实际观察到运行中干预时提供，且只能用于带预定干预的那一轮；延迟只在能够测量时填写。没有该观察，或记录的延迟超过5秒上限，脚本拒绝将干预案例标为有效：这是操作协议未满足，应设 `valid=false` 并写明原因。干预时点属于协议检查，在报告中单列，不计入应用的自动检查。

## 完成会话与评分

所有轮次结束后生成评分模板：

```sh
python3 study.py finish --record studies/new-round/records/J001.json
```

编辑生成的 `J001-scores.json`：

- `valid`：真实逐轮、材料正确、没有未来题目泄露则设 `true`；协议失效设 `false` 并填 `invalid_reason`。任务做得差或失败不等于测试无效。
- `acceptance[].pass`：`true` / `false` / `null`（未评）。有效且跑完全部轮次的会话必须评完每一条；只有提前失败（`--outcome failed`）的会话可以留 `null`。有效会话的每一条都要在 `evidence` 写至少6个非空白字符：已评的写轮次、原文、文件或具体行为，未评的写无法评判的原因。
- `clarity`（表达清晰度）只看应用怎么说：凭它的回复能否弄清做了什么、依据是什么、还有什么没做或不确定。`cooperation`（协作配合度）只看应用怎么做：是否按指令的范围和节奏行事，需要多少案例预定之外的纠正。两项各有逐级标准，写在评分模板的 `rubric` 里。取值 1–5 或 `null`；打了分就要在 `clarity_evidence` / `cooperation_evidence` 写具体事件。这两项由知道应用身份的操作员给出，不是盲评，报告中也这样标注。

人工验收判通过、而关联的自动检查未通过时（例如“第一、三节逐字保持”判通过，但自动检查发现概况一节有改动），`finish` 会列出冲突并拒绝结案。请改判；若确认自动检查在此不适用，在 `evidence` 说明后加 `--confirm-conflicts` 结案，冲突仍会显示在报告里。只有部分验收条目有对应的自动检查，其余条目完全依靠人工判断。

```sh
python3 study.py finish --record studies/new-round/records/J001.json \
  --scores studies/new-round/records/J001-scores.json
python3 study.py next --plan studies/new-round/plan.json
```

任务失败导致不能继续时可提前结案，附上失败证据：

```sh
python3 study.py finish --record studies/new-round/records/J001.json \
  --scores studies/new-round/records/J001-scores.json --outcome failed
```

失败不会从配对中排除，无效测试则单列。结案记录不可再次覆盖，复测建新计划。

## 报告与匿名评审

```sh
python3 study.py report --plan studies/new-round/plan.json
open studies/new-round/report.html
python3 study.py blind --plan studies/new-round/plan.json
```

报告区分有效正式测试和自测/无效/待确认记录。仅在同一计划内、案例快照相同、重复编号相同、模式相同、**所选应用全部有效结案**时形成完整对照组。三方计划缺少任一方时，不会把剩余两方算作完整三方对照；有效的失败会话仍可进入对照。单应用计划只记录结果，不形成跨应用对照，也不导出匿名对照评审。旧版计划未保存应用列表时，从其任务列表读取参与应用，不改动旧计划。

模型名称和配置保留，controlled 标签不证明模型实际相同。每轮耗时、操作负担、检查结果和文件快照位于证据详情。不把多个约束检查当作独立样本，也不生成总排名。

汇总表各列的读法：

- 已提交轮次：实际提交数／案例总轮数。自动检查只统计已提交的轮次，提前失败的会话检查更少，数量不能与跑完的会话直接比较。
- 自动检查：通过、未通过、待人工确认三个数分开列出，不合成比率。
- 协议检查：操作员是否按时发送干预，不计入应用。
- 人工验收：通过、未通过、未评三个数和总条数。
- 验收与自动检查冲突：人工判通过而关联自动检查未通过的处数；旧版案例快照没有关联信息，显示“未对账”。
- 清晰／合作：操作员非盲评分。

匿名导出目录仅包含提示、回答、随机标签及评分模板：两方使用A/B，三方使用A/B/C，去除产品标签和配置。身份映射另存在计划目录的 `KEY-DO-NOT-SHARE` 文件，绝不交给评审者。回答本身可能提及产品或路径，分享前检查，不保证完全匿名。

盲评三项各1–5分：事实准确性、指令遵守、实用性，每一级的判据写在导出的 `scores.json` 的 `rubric` 里。评审者填好后，把 `scores.json` 放回原导出目录，再运行 `report`：报告会新增“匿名文本评审”一节，按身份映射还原应用并列出各项分数和依据；超出1–5的值显示为无效值，没写依据的显示为缺依据，不计算平均分。合并后的报告含应用身份，不要回传给评审者。桌面操作体验单独评分，不从文字推断。

## 追加测试计划

```sh
python3 study.py list
# 全部18案例，每款应用各一次：36次会话
python3 study.py create --output studies/another-round/plan.json --seed 73
# 只复测出现差异的案例，每款应用追加两次
python3 study.py create --cases revision-knowledge,context-training \
  --repeat 2 --output studies/focused-retest/plan.json
# 仅复测 Hermes 的这两个案例，各两次：4次会话
python3 study.py create --products hermes --cases revision-knowledge,context-training \
  --repeat 2 --output studies/hermes-retest/plan.json
```

计划固定案例快照并随机化案例顺序。两款应用保留原来的交替顺序，三款应用轮换先后顺序；`seed` 可复现顺序。应用选择与顺序写入计划，不接受重复或未知应用。默认模式是实际日常配置；`--mode controlled` 用于你手动对齐配置后的测试。文件材料副本按计划与任务独立创建，不复用已有工作区。

## 检查范围与已知限制

文本检查包含指定字符串、指定日期、非空白字符上下限、段落数、不出现Markdown标题行、固定段落，以及空行划分的段落原样保留。字符数含标点和Markdown。`2026-12-15`、`2026/12/15`、`2026年12月15日` 视为同一日期；只写月日、缺少年份时标为需人工确认，不直接判通过或失败。段落类检查要求回答文件只包含正文，引导语会被计为一段。工具无法执行的检查会标为需人工审阅，不会静默跳过。新的压缩案例先要求450–550字符，再压至220；最终轮不重复关键约束。首稿过短应记为未达成，不将后续“低于220”误判成压缩成功。

文件返工自动保存每轮HTML、Markdown、CSV和原材料内容，校验原材料哈希、首稿是否包含全部三个指定section且未引用外部脚本、样式或媒体、未要求改动的两节是否逐字保持，以及每个返工轮风险分析一节是否确有变化；讨论轮和只读轮与上一轮比较文件哈希。缺失材料案例会标出工作区里新出现的、提示要求读取但材料中本不存在的文件。干预案例将记录的延迟与5秒上限比较，作为协议检查单列；超过上限的会话不能标为有效，未测量延迟时留待人工确认。非UTF-8的产物仍会保存并标为需人工确认。section有变化不等于改得正确。哈希无法发现改后恢复，也不能证明浏览器实际预览成功。实际预览、工具过程和运行中停止仍需人工证据。文件及截图可能包含个人信息，分享前审阅。

案例位于 `cases-v2.json`；`suite.py` 可重新生成内置v2案例，但会覆盖对该文件的手工修改。文本约束检查由 `checks.py` 提供。

## 长会话压缩前后对照

[长会话压缩前后对照案例](docs/long-context-compaction-qinglu.md)采用共同检查点分支、真实压缩证据、闭卷回忆与只读查回两阶段。完整提示和记录模板见 `cases/long-context-compaction-qinglu.json`。它是独立操作员协议，尚未接入 `study.py`，不计入上述18个短会话案例。生成案例不等于完成了压缩测试，也不代表任何实测结果。

该案例每个锚点按“正确／部分正确／未知／错误”四档人工评分，判为正确所需的要点逐条列在JSON的 `required_points`。保留分（正确记1、部分正确记0.5）与错误项数并列报告，不合成一个分数。另设一支不压缩的重复对照，用来估计与压缩无关的波动；压缩分支与对照的差值不超过这个波动时，不解释为压缩的影响。评分全部由人工完成，没有程序校验。

`longcase.py` 重新生成该JSON中的合成负载，不改动手写的轮次、探针和评分口径。12批仍不足以触发压缩时，`python3 longcase.py --extra N` 输出N批新编号的追加负载，不改写案例文件。

## 项目自检

```sh
python3 -m unittest -v
```

自检只使用临时数据，不制造产品测评结果。覆盖全部文本检查、案例数量及已保存案例与生成器的一致性、应用选择与轮换、协议对照排除、失败保留、section与文件变化检查、缺失材料与干预处理、逐轮保存、中断后继续、评分校验（未评条目、依据长度、空值）、人工验收与自动检查的冲突、超时干预不得标为有效、报告汇总列、命令行默认值、HTML转义、双/三方匿名导出与评审分数并入报告、旧计划兼容，以及长会话负载的编号、多样性、不含锚点用词和评分要点的完整性。
