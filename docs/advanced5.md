# Advanced5 进阶题

Advanced5 共 5 题、12 轮，纳入默认的 `v3-combined8`；`v3-combined11` 只取其中 4 题，不含场地复核（与签收更新同为“条件更新后重算、再撤销一项”）。可用 `--suite v3-advanced5` 单独运行。

| 题目 | 主要验收 |
|---|---|
| 场地复核与单项撤销 | 座位数、投影条件和预算修改后的重新推荐 |
| 更新签收证据与局部授权变化（revision 2） | 门禁时间与截止计算，交付证据的边界 |
| 报销附件缺失时仍交付已核部分（revision 2） | 已核清单、待核费用和授权范围；如实报告缺失附件 |
| 明确批准后直接生成领取单（revision 2） | 库存扣减、生成获批文件和只读复核；文件范围和CSV内容由程序校验 |
| 按字段选择权威来源（revision 2） | 预算、报价、收货时间和下单状态各取正确来源；下单状态以采购系统正式采购单为准 |

运行 `python3 suite_advanced5.py` 可重建题库。题目可用 `creates_only`（本轮只允许新建的文件）和 `expect_csv`（预期表格）声明确定性检查，结果写入每轮 `checks` 并进入评审包。新建计划时冻结题面、预置文件和评分要求。

```sh
python3 codexrun.py prepare --suite v3-advanced5 \
  --model gpt-6.1-sol@medium --model gpt-6.2-sol@medium \
  --output studies/codex-sol-medium-advanced5-1
python3 codexrun.py run --study studies/codex-sol-medium-advanced5-1
```

另见 [Challenge3 挑战题](challenge3.md)。
