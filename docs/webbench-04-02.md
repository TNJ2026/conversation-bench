# WebBench

当前题组有四道题，包括三维天体沙盒、五阶魔方、第一人称迷宫和鹈鹕骑行 SVG 动画。各题独立按百分制验收。

## 生成被测产物

安装 Codex CLI、Node.js 和 Playwright CLI，并安装 Playwright 浏览器。在固定工作环境中为各次会话提供相同依赖条件。

```sh
python3 webbench.py prepare \
  --model gpt-6.1-sol@medium --model gpt-6.2-sol@medium \
  --output studies/webbench-sol-1
python3 codexrun.py run --study studies/webbench-sol-1
```

`--case case02-gravity` 可单独准备天体沙盒题。使用 `--repeat 2` 可重复试验。计划冻结题面和材料。每份交付位于对应记录的 `workspace` 内的 `candidate/`。工作区快照保留源码和交付内的 `vendor/`，排除 `.next`、`node_modules`、`.git` 以及交付目录之外的 `vendor/`。复测启动从各作业的工作区取得产物。

## 自动验收

在隔离环境中启动被测产物。对照实验使用相同浏览器、硬件和种子。浏览器仅访问评分时指定的本地地址。

Case02 在本地端口静态提供被测的 `candidate/`，例如运行 `python3 -m http.server 9135 --bind 127.0.0.1 --directory /path/to/candidate`。然后：

```sh
python3 webbench.py score --case case02-gravity --url http://127.0.0.1:9135 \
  --output studies/webbench-sol-1/J0001-gravity-review
```

建议加上 `--record /path/to/records/Jxxxx.json`，以题目 ID 和源码快照核对被测交付，并将记录散列写入评分结果。运行者仍需确认 URL 实际指向该工作区。每项检查及失败原因见评分目录的 `score.json`。指定场景生成桌面或移动截图。Case02 核对 WebGL、相机实际画面变化、物理与状态、实际 UI 操作、1500 步近距离运行及 20 体工作负载。20 体用例的阈值为同一浏览器与硬件下 360 次确定性步进用时少于 4 秒，此值不等同于实际交互帧率。

## 人工计分

各评审独立查看匿名产物、截图和实际操作记录。每项给整数分，接近不可用给 0 分，基本可用给约一半，完整满足给满分。记录具体依据。

| 题目 | 自动分 | 人工分 |
|---|---:|---|
| Case02 | 80（功能与物理 55、稳定与固定性能负载 25） | 20：视觉清晰与信息层级（`visual-clarity`）8，实际鼠标相机旋转、平移、缩放和交互（`interactive-camera`）6，质量变化时曲率反馈、真实轨迹、物理近似说明（`overlays-and-explanation`）6 |

自动结果不含人工总分。每位评审用单独文件写入最后分数，命令会绑定自动评分文件的散列：

```sh
python3 webbench.py manual --score studies/webbench-sol-1/J0001-gravity-review/score.json \
  --reviewer reviewer-1 --mark visual-clarity=7 --mark interactive-camera=6 --mark overlays-and-explanation=5 \
  --note '桌面视口下能旋转、缩放和追踪天体，轨迹说明略简' \
  --output studies/webbench-sol-1/J0001-gravity-review/reviewer-1.json
```

分数按评审分别保留。固定性能阈值、浏览器版本及模拟 seed 应在正式对照前约定；严格盲测需要阻止被测进程读取本仓库中的评分脚本。

## Case09 五阶魔方和 Case10 第一人称迷宫

默认准备全部 WebBench 题。只运行魔方和迷宫可指定两个题号：

```sh
python3 webbench.py prepare --case case09-cube-5x5 --case case10-raymaze \
  --model gpt-6.1-sol@medium --model gpt-6.2-sol@medium \
  --output studies/webbench-cube-maze-1
python3 codexrun.py run --study studies/webbench-cube-maze-1
```

两题都从各自作业的 `candidate/` 静态启动，评分方法和 Case02 相同，将 `score --case` 设为对应题号。每题独立百分制：

| 题目 | 自动 80 分 | 人工 20 分 |
|---|---|---|
| Case09 五阶魔方 | 立体视图及内外层打乱 10、外部混合局面 20、合法翼棱奇偶 20、非法导入保留状态及历史 15、重复求解与重置取消 15。独立模型重放两组解法，记录耗时和步数。 | 立体清晰度（`3d-clarity`）8、旋转可见性（`visible-turns`）7、实际交互及直接打开 `index.html` 的离线验证（`interaction`）5 |
| Case10 第一人称迷宫 | 视图响应 10、真实键盘 10、头碰墙 15、转角 15、步长和斜移 15、通关与安全重置 15。 | 空间深度（`visual-depth`）8、实际操控（`controls`）7、原创关卡和反馈（`level-and-feedback`）5 |

Case09 自动评分通过本地 HTTP 提供静态文件，并拦截外部网络请求。人工验收还需在隔离环境中断网后直接打开 `index.html`，验证 `file://` 下的离线求解。五阶版使用 150 字符面片格式。正式比较时可为两组指定相同的 `--seed` 来生成外部混合局面，翼棱奇偶样例固定。Case10 的测试地图由评分器装载。

五阶题第 2 版要求用浏览器原生 API 自行编写全部代码，可参考公开的五阶归约法。第三方实现、预编译求解器和现成查找表均不允许，依赖来源需人工审查。新版的求解与逐步动画不限时。携带旧作业记录复评第 1 版时，仍采用该版的 90 秒限制。

## 扩展题 Case08 骑行 SVG 动画

以[静态鹈鹕题](https://github.com/ruanyf/ai-test-case/blob/8126f1ac2875282c92842e62fea7cbfecda440ec/README.md#case08)为起点，交付原创单文件 `candidate/index.svg`。自行车固定，车轮与曲柄同向，鞋底跟随踏板，髋部贴近坐垫。测试使用 SVG 的实际屏幕坐标，不仅核对接口里的相位数值。

- 自动 **60 分**。单文件 SVG 与实时播放 8，两脚踏板几何 16，车轮与曲柄同步 12，坐垫接触与循环接缝 12，暂停与切速 12。
- 人工 **40 分**。角色识别与构图（`character-and-composition`）15，动画自然度（`natural-motion`）15，画面和控件清晰度（`clarity-and-controls`）10。自动评分看的是 SVG 锚点的运动，人工需确认锚点与实际鞋底、坐垫及车轮图形对应。

```sh
python3 webbench.py prepare --case case08-pelican \
  --model gpt-6.1-sol@medium --model gpt-6.2-sol@medium \
  --output studies/webbench-pelican-1
python3 codexrun.py run --study studies/webbench-pelican-1
```

静态启动各作业的 `candidate/`，向 `score --case case08-pelican --url` 传服务目录的根地址，评分器会读取 `index.svg`。建议传 `--record`，这样也会核查交付目录只包含 `index.svg`。首轮可以只对比 **自动分 / 60**，人工分随后独立登记。

## 四题批量自动验收

准备完整计划后，可用同一条批量命令生成、启动和自动评分：

```sh
python3 webbench.py prepare \
  --model gpt-6.1-sol@medium --model gpt-6.2-sol@medium \
  --output studies/webbench-four-sol-1
python3 webbench_batch.py --generate --study studies/webbench-four-sol-1 \
  --output studies/webbench-four-sol-1/automatic \
  --seed 34021
```

已有会话记录时省略 `--generate`，只评分，不再调用模型。输出目录需为新目录。批量入口使用两个模型相同的魔方 seed，逐份核对交付记录并复制到临时目录。

- Case02、08、09、10 由临时本地 HTTP 服务提供静态文件，播放、物理、求解与交互用 Playwright 检验。
- 自动分母分别为 **80、60、80、80**。汇总同时给出原始分及全部已计分时的题目等权百分比。未完成、缺记录或环境阻塞不折算为零，也不进入等权总分；若产物缺少要求的入口或其自身无法构建，该题计零。无需人工评审即可生成自动结果。

批量输出包含 `report.md`、`results.json` 和逐作业浏览器报告。人工视觉分可在需要时继续单独登记。

每个模型的单题生成结束时，运行日志和报告都会显示耗时，以及输入、缓存输入、未缓存输入、输出和总 token。耗时为该题各轮 Codex CLI 的实际运行时间之和，包含模型调用的工具时间，排除题间等待和浏览器评分。总 token 为输入加输出，缓存输入已包含在输入中。CLI 没有返回的数据用 `—` 表示。批量评分的 `results.json` 还会为每道题保留数值形式的 `execution` 字段。
