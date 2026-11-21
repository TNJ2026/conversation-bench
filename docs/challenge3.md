# Challenge3 高难度挑战

`v3-challenge3` 共 3 题、7 轮，纳入 `v3-combined20`、`v3-combined10`、`v3-combined11` 和 `v3-combined8`。也可单独运行。

| 用例 | 主要验收 |
|---|---|
| 补货工具修复（revision 3） | 复现重复入账，最小修复，保留原接口与正常样本，隐藏回归检查冲突和兼容性 |
| 局部恢复（revision 3） | 首轮绑定文件范围和清单内容校验，次轮绑定路由变更范围和清单保留校验；人工核对遗留阻塞的说明 |
| 发布决策（revision 2） | 随有效证据更新给出 NO-GO、GO、NO-GO。首轮审批已签发，20:00 才可启动。20:15 为窗口的排他上限 |

重建题库：

```sh
python3 suite_challenge3.py
```

比较两款模型，各重复两次：

```sh
python3 codexrun.py prepare --suite v3-challenge3 \
  --model gpt-6.1-sol@medium --model gpt-6.2-sol@medium --repeat 2 \
  --output studies/codex-sol-medium-challenge3-1
python3 codexrun.py run --study studies/codex-sol-medium-challenge3-1
python3 challenge_verify.py --study studies/codex-sol-medium-challenge3-1 --regress
python3 codexrun.py export --study studies/codex-sol-medium-challenge3-1
```

`challenge_verify.py` 默认只读取记录，核对文件集合、受保护文件哈希和结构化产物。`export` 会把逐轮结果并入评审包，标注“challenge_verify”。发布文本、修复复现过程和操作授权还需结合原始日志评审。

`--regress` 在 macOS 上通过 `sandbox-exec` 运行第 1 轮快照中的 `allocation.py`。沙箱允许读取评审临时目录和 Python 所需运行库，禁止写文件、访问网络或创建子进程。沙箱完成初始化后才导入交付代码。沙箱缺失或未完成初始化时，结果记为待定。初始化后的交付代码异常退出或超时计为失败。

场景覆盖相同行重放、同量不同收货单、冲突报错、不相邻的重放和冲突，以及跨调用的状态隔离。程序在成功返回和抛出异常后都核对传入余额和收货记录，收货记录包括从 CSV 读取的列表。场景结果由沙箱外的参考实现逐一比对。同一批次用同一个随机种子生成场景，必须不同的编号按无放回方式抽取。记录保存种子、输入散列和测试文件散列。可用 `--regress --seed <记录中的 seed>` 复跑，再比对 `inputs_sha256` 确认输入一致。

`export` 将回归结果关联到补货修复 R2。应在导出前运行回归，导出后修改记录会使旧评分绑定失效。

挑战题单独报告得分。`report` 的评审总分按原始题组分行，保留各次重复和独立评审。文件和测试校验提供证据，不能从摘要或一轮的工具状态推断全部行为。
