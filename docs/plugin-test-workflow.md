# 历史查回插件：完整测试流程

本流程适用于本机macOS上的DSH Web-host运行器，从准备环境到评分、复核和版本比较。执行会调用真实模型并产生用量；项目自检不调用模型。本轮目标是验证0.1.1，与已完成的0.1.0记录比较，不修改旧版结果。

## 1. 确认环境和版本

在终端执行：

```sh
cd /Users/cxd/develop/conversation-bench
python3 -m unittest -q
'/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh' --version
git rev-parse HEAD
git status --short
```

自检通过后再运行。记录代码提交、实际DSH版本、模型、推理档位及未提交改动。本轮固定插件0.1.1，模型deepseek-flash、effort low；示例中的DSH版本0.2.2-rc.3应与本机实际情况一致。若配置与旧基线不同，应明确报告，不能称为仅插件版本变化。

不要给被测DSH完整案例、未来问题、评分或其他分支答案。当前助手/操作员负责运行与评审，被测对象是运行器建立的独立DSH会话。

## 2. 准备模型认证

运行器不会自动复制日常DSH凭据。可在**执行测试的同一个终端**提供DEEPSEEK_API_KEY。macOS默认zsh可隐藏输入，避免将实际密钥写入命令历史或聊天：

```sh
read -s 'DEEPSEEK_API_KEY?请输入 DeepSeek API key：'
echo
export DEEPSEEK_API_KEY
```

也可沿用已验证的独立环境认证方式；不需要把整个日常DSH目录复制进测试环境。不要打印密钥或把它写入仓库。若出现model-unavailable、认证失败或超时，按第7节保留记录处理；不要把认证失败计为答案错误。

## 3. 安排六组新运行

先V7三组，再V8.1三组。每组都有独立新目录：

| 用例 | 案例文件 | 建议运行目录 |
|---|---|---|
| V7，第1组 | cases/long-context-compaction-qinglu-v7.json | studies/v7-plugin-0_1_1-1 |
| V7，第2组 | 同上 | studies/v7-plugin-0_1_1-2 |
| V7，第3组 | 同上 | studies/v7-plugin-0_1_1-3 |
| V8.1，第1组 | cases/long-context-task-qinglu-v8.1.json | studies/task-v8_1-plugin-0_1_1-1 |
| V8.1，第2组 | 同上 | studies/task-v8_1-plugin-0_1_1-2 |
| V8.1，第3组 | 同上 | studies/task-v8_1-plugin-0_1_1-3 |

如果建议目录已经存在，选择新的唯一名称，不覆盖、不删除旧记录。每组重复下面第4–6节，完成后再换下一组。合法运行中答错、未使用插件或工具失败，均应保留计入结果；只有协议无效或未完成的运行才另列，并在新目录补足三组有效运行。

## 4. 创建并执行一组

以下为V7第1组；后续按表格修改两个变量。

```sh
BENCH_CASE=cases/long-context-compaction-qinglu-v7.json
BENCH_RUN=studies/v7-plugin-0_1_1-1

python3 study.py long create \
  --case "$BENCH_CASE" --output "$BENCH_RUN/plan.json" \
  --transport web --history-plugin --history-plugin-version 0.1.1 \
  --dsh-bin '/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh' \
  --provider deepseek-official --model deepseek-flash --effort low \
  --app-version 0.2.2-rc.3 --load-batches 12 --seed 42

python3 study.py long run --record "$BENCH_RUN/plan.json"
python3 study.py long next --record "$BENCH_RUN/plan.json"
```

第二组将BENCH_RUN改成新的第2组目录，再从create开始；第三组同理。切到V8.1时：

```sh
BENCH_CASE=cases/long-context-task-qinglu-v8.1.json
BENCH_RUN=studies/task-v8_1-plugin-0_1_1-1
```

然后重复相同的create/run/next命令，之后改目录完成第2、3组。`--seed`只控制运行器分支顺序，不代表固定了模型生成随机性。

每组正常完成22个动作：3轮seed、12批负载、1次压缩、3分支各2次探针。A与A_repeat不压缩，B压缩；插件只在各分支recovery阶段加载。create冻结用例、插件版本和文件哈希，旧计划不会跟随默认插件版本升级。

先检查status为completed、pending为空、problems为空；这只表示执行完成，**不等于评分和协议复核已经通过**。

## 5. 生成并填写评分

```sh
python3 study.py long grade --record "$BENCH_RUN/plan.json"
```

此命令生成BENCH_RUN下的scores.json，不自动替代语义评审。每组需核对3分支×2阶段×10项，逐项依据冻结标准填写等级和证据，不能直接复制上一组或让被测模型评自己。

通用字段：

- grades中的grade使用案例允许的correct、unknown、wrong，不使用partial；evidence引用实际回答或事件，不能只写“满足要求”。
- omitted表示是否漏答；漏答记unknown，明确错误断言记wrong。
- retrieved仅在recovery且有实际工具、原始来源支持时填写true，sources附原始事件seq及工具调用/返回定位。它不意味着答对；查到后抄错仍判wrong。
- protocol三项必须明确pass和证据：无答案/跨分支泄露、无外部写入或学习、配置等价。核对真实工具记录、工作区变化、插件版本和加载阶段。
- AI评分须另存说明“AI非盲复核”，不能标成独立人工盲评。

V7：逐工单核对码值与来源，沿用冻结的行格式规则。表格内容正确但未通过旧配对格式时，正式评分与内容诊断分开，不修改旧规则。conclusions三支都保留text为null，evidence说明“V7不要求主管结论，不适用”。

V8.1：逐项检查最新决定、历史证据和交接行动，10项全correct才算完整交付。conclusions选择实际recovery回答中主管结论的连续原文并附证据；另核对两阶段结论长度、日期和固定句。分清“审批权限未说明”与“尚未指定”，以及“核实/上报风险”与“正式启用获批”。

是否完整读取按返回内容判断：search也可能返回完整消息；核对truncated、偏移、total_chars及原文一致性，不能仅凭未调用read判错。0.1.1中line_truncated=false只表示命中行完整，不表示整个消息完整。

若原标准确有歧义，另存复核记录及待定项；不要为通过程序而强行填correct或wrong。当前grade不支持ambiguous，未能裁定时不能宣称已获得无待定的正式成功率；先保留原始记录，完成裁定或单独报告待定范围。

## 6. 校验、生成报告并复核

完成评分文件后：

```sh
python3 study.py long grade \
  --record "$BENCH_RUN/plan.json" --scores "$BENCH_RUN/scores.json"
python3 study.py long report --record "$BENCH_RUN/plan.json"
open "$BENCH_RUN/report.html"
```

每组应有plan.json、scores.json、scores-reviewed.json、report.json、report.html及raw/事件。复核时确认：

1. 三项协议审阅均有真实证据，protocol_valid明确，不把completed当作协议结论。
2. 运行ID、案例哈希、回答快照和评分哈希绑定一致，报告与逐项评分一致。
3. 闭卷0工具、无插件；9次recovery均有注册证据，并区别“注册成功”与“实际使用”。
4. 插件版号、文件哈希一致且为所选版本；原始出处属于本分支。被压缩原消息的可追溯seq不代表该原消息仍直接可见。
5. 压缩覆盖三条seed。V7声明10个回执锚点，核对覆盖表；V8.1声明receipt锚点1个，不把10项验收条件写成10个压缩锚点。
6. 内容错误、格式问题、工具失败与协议无效分别记录，汇总从逐项数据重算。

有判分修订时保留旧版本与变更理由，JSON和Markdown同步；不改答案、不追溯改变验收标准。

## 7. 中断与异常

需要分段执行时，用 `run --max-actions 3` 在动作边界停止，再执行同一run命令继续；next可查看下一动作。

attention、pending、超时或断连均不能盲目重发：请求可能已经执行。invalid和completed不自动重开。不删除状态或锁来强行继续；先确认旧进程已停止并检查原始事件，必要时在新目录重建。完整处理规则见[运行器异常与恢复说明](long-context-runner.md)。

如果新版本真实查回仍出现错码，应保留为正式失败。不能通过只重跑失败样本替换结果来获得三组满分。

## 8. 版本比较与收尾

三组V7、三组V8.1均评分并复核后，按分支和阶段比较：

| 指标 | 对比方式 |
|---|---|
| V7精确配对 | correct/unknown/wrong、格式问题、内容诊断分开；检查相邻码错配 |
| V8.1完整交付 | 通过/失败/待定及具体原因；recall和recovery分开 |
| 效率 | 相同阶段累计墙钟、每次耗时、总工具及search/read次数 |
| 来源质量 | 片段与原文、归属、截断、定位、完整读取声明是否一致 |

0.1.0参考记录为studies/v7-plugin-1/2/3、studies/task-v8_1-plugin-1/2/3，其[最终结果与限制](current-history-plugin-results-0.1.0.md)单独保留。0.1.1采用新的运行目录与汇总文件，不覆盖0.1.0。

即使结果改善，也先表述为本次观察。三组单案例重复不能证明普遍或稳定因果收益；18次交付及90项条件也不是独立样本。没有token、费用、首字延迟和缓存用量时留空，不能由墙钟推算。

保存代码版本、配置、用例及插件哈希、逐项评分、复核变更和报告。原始运行位于被Git忽略的studies/，不把凭据或原始日志加入源码提交。全部测试结束后，在终端清理临时认证环境变量：

```sh
unset DEEPSEEK_API_KEY
```

本文不自动安装插件到日常DSH，也不自动运行六组测试。
