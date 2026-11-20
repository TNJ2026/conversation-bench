# DSH SDK 批量测试

`dshrun.py` 使用已安装桌面应用自带的 `dsh --profile sdk`，经 `dsh_driver.py` 的 JSON-RPC 接口运行默认合并题库（`v3-combined10`，10 题、23 轮），全部可按顺序会话执行。结果不是桌面UI测试。

```sh
python3 dshrun.py prepare --model deepseek-flash --effort high \
  --output studies/dsh-flash-high-new
python3 dshrun.py run --study studies/dsh-flash-high-new
python3 dshrun.py export --study studies/dsh-flash-high-new
```

`--dsh` 可指定启动器，`--provider` 默认 deepseek-official，`--timeout` 默认每轮600秒。`prepare --cases adv-approved-picklist` 可单独准备两轮预检。模型及推理档位必须由所选运行时支持；不自动替换模型或降低强度。

`--cases` 可选择部分题目。`--profile-patch /绝对路径/provider.yml` 可提供 SDK 配置覆盖层；内容冻结到计划，运行时从冻结内容生成 `runtime-overlay.yml` 并传入启动器的 `--patch`。覆盖层必须只包含非敏感配置，凭据使用 `apiKeyEnv` 引用，不能内嵌 API key。输入文件后续修改不会影响已冻结的计划。


2026-11-17 的连通性实测中，显示名 `close_ai` 对应路由 ID `closeai`。`gpt-6.1-sol / medium` 在原 Chat Completions 协议下因工具与推理参数组合返回400；独立覆盖层将 `api` 改为 `openai-responses` 后成功对话。该结果只确认这组配置的连通性；日常 desktop profile 没有修改。其他自定义 provider 的凭据需在启动批处理的进程环境中提供，官方凭据桥接不会自动读取它们。

每题建立新的临时工作区、DSH_HOME和会话ID，同题后续轮次恢复原会话。每轮结束后关闭运行时，因此不保证恢复外部浏览器或终端进程。运行时使用默认SDK工具、系统提示和生成上限，不加载日常desktop profile的插件；这些差异必须与Codex的模型、推理设置一起披露。独立目录不能阻止模型读取其他路径，也不能宣称不存在全局技能影响。

认证优先使用已有环境；缺少环境凭据时复用 `dsh_driver.runtime_environment`，仅在内存中读取本地DSH保存的官方API key并传给子进程。不会要求用户重新输入、把凭据写入计划或复制整个认证文件。不支持的认证会如实导致预检失败。

计划与案例通过哈希冻结；执行前验证运行时版本。`records/` 保留逐轮回答、文件快照和工具证据；`raw/` 保留发送提示、请求配置、JSON-RPC事件、stderr及完整结果。快照沿用Codex运行器的文件数量/大小限制。原始日志可能包含任务材料，应视为私有数据。

发生传输异常立即停止整批，保存 transport-unknown，不自动重发当前题。再次运行跳过所有已有记录，继续未开始的题；重测须使用新目录。模型报告异常完成时保留 failed。completed 仅代表全部轮次取得正常响应，不等于答案正确。

`export` 复用同一V3评审包和评分标准；语义评分仍需独立评审。预检与正式样本分别保存。协议serverInfo版本与应用版本是两个不同字段。

验证：`python3 -m unittest -q test_dshrun test_codexrun`；模拟SDK验证同题恢复、记录导出、计划篡改拒绝及失败防重发，不调用真实模型。真实预检另行执行。

