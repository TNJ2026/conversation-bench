# 长会话压缩对照：自动运行说明

入口为 `python3 study.py long`，支持 `create`、`run`、`next`、`extend`、`grade`、`report`。原来的 18 个短会话及其命令保持独立。

## 实际执行方式

运行器使用本机 DSH CLI 的 `sdk` profile，通过标准输入输出上的 JSON-RPC 发送真实提示并等待结束，不调用当前评测助手来模拟目标回答，也不自动点击桌面应用。其结果应标记为 `dsh-sdk`，不能冒充 DSH 桌面 UI 实测或与此前桌面配置已经对齐的实验。

需要支持 `initialize`、`session/query`、`session/resume`、`shutdown` 与原生 `/compact` 的 DSH CLI。提供启动环境中的模型凭据；运行器不读取或复制日常 `~/.dsh` 的凭据。测试环境由独立的 `DSH_HOME` 管理，SDK profile 按 DSH 的原生机制初始化，模型和推理档位在创建时固定。可用 `--app-version` 记录实际 DSH 版本；握手中的 `serverInfo.version` 只是 SDK 服务版本，不能替代应用版本。若原接口不兼容、凭据不可用或目标请求人类输入，应保留日志并处理失败，不将它们转成虚构成功。

只用 Python 标准库，不需要安装 Python SDK。默认 CLI 名称为 `dsh`，可用 `--dsh-bin /absolute/path/to/dsh` 指定。真实执行会调用模型并产生用量；本项目的进程级协议测试完全不调用模型。

## 创建与连续执行

选择尚不存在的输出目录；计划会冻结完整案例、配置、分支顺序和实际负载。以下模型与档位仅为命令示例，须匹配你安装的 DSH 路由。

```sh
python3 study.py long create --model deepseek-v4-flash --effort low \
  --provider deepseek-official --load-batches 12 \
  --output studies/long-1/run.json
python3 study.py long run --record studies/long-1/run.json
```

按顺序发送三轮早期任务及选用的负载，每次等待目标结束，保存原始协议日志、事件和回答。每个动作结束后关闭 DSH 进程并等待其正常退出，再保存完成状态。不会向目标发送完整案例、未来探针或答案锚点。

计划中的负载全部完成后，将停止状态的测试环境复制为 A、A_repeat、B 三支，逐文件校验副本与同一检查点一致。运行器记录的是完整前缀事件证据哈希，并非声称已重建模型请求；等价起点的主要证据是停止后的持久环境逐文件一致。各支使用相同会话 ID、相同既有历史、相同任务工作区及独立 DSH_HOME。这里是独立测试环境的磁盘快照，不是调用未提供的会话 fork 接口。

在 B 中调用原生 `/compact`。必须同时观察到非空 `compaction/summary`、覆盖三条原始 seed 用户消息序号的 `shadowedSeqs`，以及引用该摘要、覆盖这些消息的 `user/message` 历史替代事件，才继续探针。仅出现“已总结”文字不合格。随后按已保存的随机顺序运行三支的闭卷回忆与只读查回。

## 分段执行与追加负载

```sh
# 每次最多完成三次目标调用，然后在安全边界暂停
python3 study.py long run --record studies/long-1/run.json --max-actions 3
python3 study.py long next --record studies/long-1/run.json
# 仅在检查点创建之前追加，编号延续已有负载
python3 study.py long extend --record studies/long-1/run.json --batches 2
python3 study.py long run --record studies/long-1/run.json
```

`next` 仅显示状态和下一个操作，不调用目标。检查点之后禁止追加前缀负载。`--load-batches` 是显式的负载数量，不是 token 阈值或压缩触发保证；可在暂停时检查原始请求上下文，再决定继续或追加。

当前版本不在第一次自动压缩后“倒退”制造未压缩分支。前缀或探针期间出现自动压缩，会将本次实验判为协议失效；需要减少负载、调整独立测试配置并新建计划。闭卷调用工具或目标改变共享任务工作区，同样会停止并保留证据，防止污染后续分支。

## 超时、崩溃与恢复

每个目标调用默认总时限 900 秒，创建时可用 `--timeout` 调整。调用前先持久化 `pending`。超时、断连、需要人类输入或无法证明进程已停止时，记录为 `attention`，禁止自动重发同一提示：远端可能已经提交了答案或其他动作。

在正常动作边界暂停的运行可直接继续；`pending` 或 `attention` 需要核对私有协议日志和目标持久历史，不能仅删除标记后盲目重试。当前没有自动消解不确定调用的功能，确认原进程停止后应以新计划重新开始。进程崩溃遗留 `.lock` 时，先确认没有同一运行器或目标进程活动，再移除锁；移除锁不代表可以清除 `pending`。

`invalid`、`attention` 和 `completed` 运行不会被自动继续或覆盖。不同计划必须使用不同输出目录。日志和状态保存在 `studies/`，默认被 Git 忽略。

## 人工评分与程序校验

```sh
python3 study.py long grade --record studies/long-1/run.json
# 填写 studies/long-1/scores.json 后：
python3 study.py long grade --record studies/long-1/run.json \
  --scores studies/long-1/scores.json
python3 study.py long report --record studies/long-1/run.json
```

模板包括三支、两阶段、十个锚点，每项填写 `grade`、具体 `evidence`、是否 `omitted`、是否 `retrieved` 以及查回的 `sources`。语义档位由独立评审者依据原材料和实际回答判断；不能让目标自己生成评测成绩。

另在 `conclusions` 中选择每支实际回答里的结论原文，附具体依据。程序验证它确实是原回复的连续片段，再检查220字符、日期、现行预算与固定句；无法确定结论范围时留空并说明原因，报告显示待人工确认。

程序检查分支、阶段、锚点完整性；遗漏只能记为未知；固定句和口令不能给部分分，判正确时必须出现在实际回答中；声称查回时只允许在 recovery 阶段，并要求有实际工具调用和非空来源定位。程序无法证明任意来源文本真实支持某个结论，这部分仍需人工审阅。

模板的协议复核还要求明确判断信息未泄露、没有外部写入或自动学习、配置等价，并给出证据。工作区快照仅能发现其中的文件变化，不能证明全盘没有写入、没有更新外部记忆或没有读取测试目录。目标是否有足够的访问隔离由操作者保证；不可将独立目录当作系统级隔离。

评分绑定 run ID、案例哈希及全部回答/事件快照，拒绝把另一轮评分套到当前记录。评分保存为 `scores-reviewed.json`，报告同时输出 `report.json`、`report.html`，并保留保留分、错误项数、漏答数与真实查回项数。未填评分就生成报告时，成绩留空，不补造结果。

报告给出 B−A 与 A_repeat−A。单组三支结果不作因果归因；人工协议复核不通过时，不输出“超出重复波动”的判断。调用耗时来自实际墙钟时间，token 暂不自动汇总，未知值保留为空。

## 验证范围

`python3 -m unittest -v` 中的自动运行测试启动一个独立的 JSON-RPC 协议夹具进程，覆盖连续发送、持久恢复、复制分支、原生压缩回执顺序、替代证据核验、闭卷工具违规、暂停追加、超时不重发、评分绑定和漏答规则。它不调用真实模型，不代表已测过某个已安装 DSH 或其压缩质量。真实 DSH 兼容性和完整产品实验仍需实际运行上述命令确认。
