# Conversation Bench

AI会话体验、长上下文恢复与交付质量的实验工具。Python测试工具与DSH产品源码分开；桌面对照支持DSH、ChatGPT和Hermes，自动运行器使用隔离DSH运行时。

- [完整中文说明](README.zh-CN.md)
- [插件维护指南：代码地图、测试与工作树状态](docs/plugin-maintenance.md)
- [默认一次交付：输入、运行与复核](docs/bounded-delivery.md)
- [配对结果及适用边界](docs/bounded-delivery-results.md)
- [虚构输入格式示例](examples/bounded-delivery.input.json)
- [实验协议与执行流程](docs/plugin-test-workflow.md)

```sh
# 在项目根目录执行；input.json应是你已准备的真实材料
python3 boundedrun.py run --input /绝对路径/input.json --output studies/my-delivery-1
# 需要一次末段修复时显式增加 --repair，并使用新输出目录
python3 -m unittest -q
```

当前默认有界原文证据＋一次生成。相同证据下的12次配对测试中，两组均6/6完整交付，默认追加修复没有观察到收益。结果是小样本AI非盲复核，不代表通用可靠性保证。

`studies/`保存本地原始记录和报告，不随源码上传；不要覆盖冻结记录或把`completed`当作任务成功。当前本地项目位于`/Users/cxd/develop/conversation-bench`，历史迁移说明仅用于追溯。
