# 当前会话历史查回插件

这是用于对照实验的原生 Cordis 工具插件，版本 0.1.0。针对本机 DSH 0.2.2-rc.3 的 Web 运行时完成接入验证，不能据此宣称其他版本或桌面窗口已经验证。

## 已实现的范围

- `current_history_search(query, limit=5)`：按字面搜索当前会话的原始用户消息，返回事件 seq、时间和命中片段。结果按原始序号排列，最多10条，明确标记截断与更多结果。
- `current_history_read(seq, offset=0)`：读取命中的原始用户事件，返回精确原文及字符偏移；每次最多12000个 JavaScript UTF-16 代码单元，较长内容通过 next_offset 继续读取。

插件只通过宿主的 sessionQuery 服务读取调用者会话。工具不接受会话 ID、路径或任意代码；不读取其他会话，不搜索助手旧答案、工具结果、运行时提醒或压缩替代摘要。被压缩替代的原始用户事件仍可查回，结果明确标为原始用户数据，不能当作新指令。

没有写入、长期记忆、学习或模型摘要步骤。没有实现自动状态提取或自动注入；每次按需读取当前会话，不维护持久搜索索引。检索是大小写敏感的字面匹配，不是语义搜索。

它限定自身两个工具的读取范围，不改变宿主其他工具的权限；模型是否主动使用它仍需观察。工具内部输入检查、取消检查、输出限额和会话身份校验均已测试。

## 接入运行器

创建新计划时增加 `--history-plugin`，目前只支持 `--transport web`。例如：

```sh
python3 study.py long create \
  --case cases/long-context-task-qinglu-v8.1.json \
  --output studies/task-v8_1-plugin-1/plan.json \
  --transport web --history-plugin \
  --dsh-bin '/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh' \
  --provider deepseek-official --model deepseek-flash --effort low \
  --app-version 0.2.2-rc.3 --load-batches 12
python3 study.py long run --record studies/task-v8_1-plugin-1/plan.json
```

认证按现有独立测试环境准备，创建计划不会复制日常凭据。不要把测试案例、预期答案或其他分支暴露给目标。

创建时冻结 package.json、index.cjs、cordis.patch.yml 的副本、版本和逐文件 SHA-256。运行时只在各分支 recovery 阶段将这些文件复制进分支独立 home，再通过启动器 patch 加载；prefix、compact、recall 均不加载。因此原始前缀和闭卷工具集合保持与基线相同，插件的效果针对辅助查回阶段比较。

每次加载前校验冻结副本与部署文件；被修改时拒绝运行。运行器还要求在模型请求前观察到工具注册标记，未观察到则失败，不将未加载的运行标成插件实验。结果与报告保存 history_plugin 注册证据、版本、文件校验值及真实 tool/call 序号。注册成功但调用数为0应如实报告，不能算已使用插件。

插件工具描述会增加 recovery 请求的工具上下文，属于实验处理的一部分；没有改写案例提示或注入预期答案。不要将 recovery 的改善解释为闭卷记忆改善。B 的合计耗时包含一次压缩成本，报告中逐动作计时可单独比较。

## 已验证与尚未验证

本次真实接入验证使用新的虚构凭据，依次发送用户记录、执行原生 /compact、要求搜索并读取原始事件。DSH 实际调用 current_history_search、current_history_read，并返回正确码值；注册标记和调用事件均已保存。该请求明确指定工具，证明接入与执行可用，不证明模型在不提示工具名时也会主动调用。

本地证据位于 studies/history-plugin-smoke-4/summary.json 及同目录原始事件，属于接入验证，不计入 V7/V8.1 成绩。此前独立验证目录保留认证准备失败和启动参数顺序错误，均未计作产品成绩。

正式插件对照尚未执行。下一步用同一冻结用例分别运行 V7 和 V8.1，至少做三组新会话；记录成功、失败、协议无效及工具未使用，分分支、分阶段比较。V8.1 沿用已复核的基线口径及待定项处理，不直接用旧版全满分报告作分母。当前只有动作墙钟时间，token、费用、首字延迟及缓存用量仍未自动采集。

插件文件与版本需要在基线/实验对照开始后保持冻结；若改工具说明、能力或评分要求，应明确记录为新的实验条件。
