# 插件维护指南

供本仓库后续开发使用。依据2026-11-15当前代码和工作树整理，检查时HEAD为`a761d39`。这是一份实际维护资料，不是模型评测答案或真实项目交接验收。Git状态是当时快照，接手时重新检查；未联网核对远端或确认发布状态。

## 先确定要维护哪条路线

|路线|用途|主要入口|不能据此宣称|
|---|---|---|---|
|历史查回|从调用者会话中查回原始用户消息|`history_plugin.py`、`plugins/current-history-v0.1.1/index.cjs`|长期记忆、自动完整理解、跨会话检索|
|有界交付|给定有限来源后一次生成，可显式追加修复或压缩|`boundedrun.py`、`bounded_delivery.py`、`plugins/bounded-delivery-controller/index.cjs`|自动浏览仓库、工具检索、语义保证|

修改搜索、分页、来源范围时走历史查回路线；修改输出约束、压缩、请求预算和用量时走有界交付路线。不要把两条路线的实验成功率混用。

## 代码地图

以下路径均相对仓库根目录。

|文件或目录|职责与现状|
|---|---|
|[history_plugin.py](../history_plugin.py)|`SOURCES`只映射0.1.0、0.1.1，`DEFAULT_VERSION=0.1.1`；冻结、部署、校验插件和采集工具调用证据|
|[plugins/current-history/](../plugins/current-history/)|包版本0.1.0；旧行为对照实现，当前源码也有未提交的分页扩展，不能等同历史冻结快照|
|[plugins/current-history-v0.1.1/](../plugins/current-history-v0.1.1/)|默认历史插件；命中行范围控制；分页变更未提交|
|[plugins/current-history-v0.1.2/](../plugins/current-history-v0.1.2/)|本地未跟踪；增加交付自查提示，属于建议性提示，不是机械语义验证；由`deliveryrun.py`自己的版本映射使用|
|[plugins/current-history-scoped/](../plugins/current-history-scoped/)|本地未跟踪；版本`0.1.1-scoped.1`，限定操作者允许的原始来源seq；由`scopepairrun.py`冻结|
|[webhost_driver.py](../webhost_driver.py)|DSH Web-host会话调用、事件收集、正文提取与加载证据|
|[boundedrun.py](../boundedrun.py)|直接交付、可选末段修复/全文压缩、隔离home、请求核验、用量与失败状态|
|[bounded_delivery.py](../bounded_delivery.py)|证据选择、提示构造、末段补丁检查、全文压缩提示|
|[bounded_runtime.py](../bounded_runtime.py)|运行时指纹、工作区等辅助功能|
|[plugins/bounded-delivery-controller/index.cjs](../plugins/bounded-delivery-controller/index.cjs)|bootstrap零模型请求，draft/repair/compress阶段单次请求限制，实际请求与usage捕获；真实请求工具列表为空|

本地实验控制器映射：`v10-controller`供`recoveryrun.py`/`deliveryrun.py`使用；`v12-controller`供`auditrun.py`使用；`v13-controller`供`issuerun.py`使用；`v14-controller`供`coveragerun.py`使用；`scope-pair-controller`供`scopepairrun.py`使用。这些目录及上述实验runner当前均未跟踪，属于本地研究工作，不能视为已随源码发布的稳定入口。

## 历史查回的关键契约

- 只读取调用者会话、当前步骤边界之前的原始用户事件；不接受任意会话ID、路径或代码。不得把助手答案、工具结果或压缩替代摘要当原文。
- `current_history_search(query, limit=5, after_seq?)`是大小写敏感的字面搜索，最多10个事件；每事件只返回首个命中。
- 结果按seq升序，`after_seq`为排他游标；`has_more=true`时保持同一query，用`next_after_seq`继续，末页游标为null。
- 同一事件中的其他内容使用`current_history_read(seq, offset=0)`，每页最多12000个JavaScript UTF-16代码单元。不要与Python的Unicode字符计数混为一谈。
- 0.1.1的`line_truncated=false`仅表示命中行完整，不表示整条消息完整；查到值也不证明它属于正确对象或是最新决定。
- scoped实现要求`scope.sessionId`和允许的seq集合匹配当前调用者；缺失、重复、越界来源应拒绝，不退化为全会话读取。
- 插件范围约束只作用于自身工具，不改变宿主其他工具权限。模型是否主动调用，需要实际tool/call事件证明；注册成功但调用0次不算已使用。

普通历史实验只在recovery阶段加载插件。`history_plugin.freeze()`保存package.json、index.cjs、cordis.patch.yml及逐文件SHA-256；`stage()`校验冻结和部署副本，禁止改坏后静默覆盖。已有计划使用自己的快照，不随默认版本变化。不要向`history_plugin.SOURCES`随意加入0.1.2或scoped以便旧命令“直接可跑”，那会改变实验入口与条件。

## 有界交付的关键契约

默认一次直接生成；`--repair`显式追加末段修复，`--compress --max-answer-chars N`显式允许完整超限草稿追加一次全文压缩，两者互斥。压缩没有稳定达标证据，不默认启用。完整性优先时通常不设硬字数门槛。

默认模型配置仍为deepseek-official/deepseek-flash、low、4096；模拟诊断使用过off，但不能把该结果泛化为所有任务的最佳配置。证据预算默认3200、允许800–12000；每次核对`evidence_packet.selection.omitted_ranges`。既往模拟使用10000，不等于默认3200已获同样验证。

`completed`只表示流程结束；`patch_accepted`仅表示末段补丁检查通过。`delivery_validation=passed`只验证完整草稿和长度；`semantic_verified=false`、`task_success=null`应保留。失败或超限不裁剪原文冒充合规，未知请求结果不自动重发。

请求已捕获后断连仍计入request_count，用量标不完整，totals为null；先前核验部分保留为verified_*，不是全任务用量。压缩失败保留原草稿，并另存compression.md。压缩与修复最多两次请求，共享任务超时；不同阶段的用量都要计入。

对于deepseek-official，`boundedrun.py`优先使用启动环境中的密钥；不存在时可桥接启动端DSH凭据库的单项密钥，要求仅所有者可读写。不把密钥写入记录或复制整个凭据库。这是该运行器的行为，不能推定所有历史runner都有同样认证逻辑。

## 本地开发与验证

在仓库根目录执行；当前本地路径为`/Users/cxd/develop/conversation-bench`。旧测试流程中的`/Users/cxd/develop/dsh-testing/conversation-bench`是历史路径，不应照抄。

```sh
git status --short
python3 -m unittest -q
node --test plugins/current-history/test.cjs plugins/current-history-v0.1.1/test.cjs plugins/current-history-v0.1.2/test.cjs plugins/current-history-scoped/test.cjs
git diff --check
```

如果只修改历史插件，可先运行对应test.cjs；若改冻结、加载、隔离或计量，同时运行Python测试。四套Node测试包含未跟踪实现；干净克隆未必具有全部文件，不要把本机通过等同于仅提交代码可复现。

需要原生机制自检时，用新的目录：

```sh
python3 boundedrun.py smoke --output studies/maintenance-smoke-unique
```

这是DSH运行时加模拟流，不调用真实模型；该CLI smoke覆盖直接与末段修复路线，并非全部全文压缩路线。全文压缩原生模拟的既有证据为`studies/compression-native-smoke-v2-20261115/`；机制自检不能证明真实模型语义质量。真实模型命令会产生用量，应有具体任务和预先冻结的验收要求，不为“再试一次”无限采样。

## 本次实际执行的检查

2026-11-15整理时重新运行：Python全量290项通过；四套历史插件Node测试44项通过。本次只整理维护资料及运行机制测试，没有调用新的真实模型，没有验证当前DSH桌面窗口加载、安装或发布状态。

这些结果适用于本地工作树（含未提交/未跟踪代码），不是远端CI或发布版结论。模型交付研究见[结果摘要](bounded-delivery-results.md)；当前推荐一次生成后按[来源复核清单](bounded-delivery.md#一次生成后的复核与交付)检查，必要时另存编辑稿。

## 提交与继续开发前的注意事项

检查时最近提交为`a761d39`；`8c93177`已提交全文长度检查、显式全文压缩及相关断连计量修复。后续`53df5e4`、`cbbfd9e`、`a761d39`记录实验收尾和完整性优先原则。未核验推送状态。

当前仍未提交的内容包括README.zh-CN.md、历史插件文档、0.1.0/0.1.1的index.cjs和test.cjs分页改动。0.1.2、scoped、若干控制器和实验runner为未跟踪文件。不要直接`git add .`把全部研究产物作为一次发布；先逐项确认归属、依赖和要保留的范围。

`studies/`、`runs/`、工作区和原始日志被.gitignore排除，摘要链接指向本地记录不等于其他克隆可访问。保留冻结材料、请求、用量和评分；源码有变更就建立新运行目录，不改旧评分来适配新要求。源文件版本号未变也可能散列已变，应记录准确散列。

后续按实际需求选择一项：

- 修改分页时，检查升序、排他游标、最后一页、同事件多命中、取消及会话/步骤边界，避免分页扩大权限。
- 维护scoped时，先核对来源集合构造与session绑定，不借“查不全”放宽到未批准事件。
- 修改交付逻辑时，核对触发条件、请求上限、真实配置、失败保留和用量完整性；不要把结构通过直接改成task_success=true。
- 准备发布时，先整理上述未提交与未跟踪依赖，再用实际要提交的文件集验证。当前未提出或授权发布任务。

进一步阅读：[历史插件行为](current-history-plugin.md)、[实验流程](plugin-test-workflow.md)、[有界交付运行与复核](bounded-delivery.md)。
