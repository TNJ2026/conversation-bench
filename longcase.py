#!/usr/bin/env python3
"""Synthetic pressure load for the long-context compaction case.

Regenerates only pressure_turns; seed turns, probes and scoring stay hand-written.
"""
import argparse
import hashlib
import json
from pathlib import Path

CASE = Path(__file__).with_name('cases')/'long-context-compaction-qinglu.json'
BATCHES, PER_BATCH = 12, 32

HEADER = ('下面是第{batch}批虚构历史反馈，仅供内容体验分析。请按问题类型归类，选3条说明需要补充的证据，'
          '用不超过240个非空白字符回复；不统计项目总成本，不更改项目决定，不写文件。')

# The load must stay unrelated to the seeded anchors, so it never mentions these.
ANCHOR_TERMS = ('预算', '启用', '审查', '负责人', '专职', '非敏感', '报价', '权限', '批准', '上线', '采购',
                '增员', '招聘', '供应商', '口令', '豁免', '灰度', '工时', '工作量', '支出', '转述',
                '32000', '28000', '6800', '2027', '青鹭', '米白')

TOPICS = [
    ('重复条目', ['两篇条目步骤几乎相同但结论相反', '同一问题在两个栏目各有一篇且更新时间不同', '检索结果前五条里有三条内容重复']),
    ('反馈归类', ['提交的纠错被归到“其他”后查不到处理进度', '同类意见分散在三个标签下无法合并查看', '反馈表的问题类型选项与实际情况对不上']),
    ('检索入口', ['首页搜索框与栏目内搜索返回的结果不一致', '输入完整标题也搜不到对应条目', '点击搜索建议词后跳到无关栏目']),
    ('移动端排版', ['手机上表格被截断，右侧两列看不到', '步骤截图在小屏上缩得无法辨认', '长代码行撑破页面，需要横向拖动']),
    ('过期内容', ['条目描述的菜单名称与当前界面不符', '条目引用的旧版流程已不适用但未标注', '页面标注的更新时间早于文中功能的发布时间']),
    ('空结果提示', ['搜索无结果时只显示空白页，没有下一步建议', '空结果页推荐的条目与输入的词无关', '筛选条件过多导致无结果，页面没有提示放宽条件']),
    ('术语别名', ['用口语说法检索不到使用正式术语的条目', '同一功能在不同条目里有三种叫法', '缩写与全称的检索结果完全不同']),
    ('阅读路径', ['从一篇条目跳到另一篇后没有返回原处的入口', '推荐的“下一篇”与当前步骤没有衔接', '面包屑显示的栏目与实际所在栏目不一致']),
]
SCENES = ['阅读历史帮助条目', '按步骤排查问题', '向同事转发条目', '整理常见问题清单']
SOURCES = ['反馈通过条目底部的评价入口提交', '反馈来自季度回访问卷的开放题', '反馈由值班同事在答疑时代为记录',
           '反馈通过站内纠错按钮提交', '反馈摘自读者交流群的讨论整理']
EVIDENCE = ['附件只有文字描述，没有录屏和复现统计', '附了一张截图，但看不出操作步骤', '提供了两次复现的时间点，未说明设备和浏览器',
            '描述只有一句话，没有说明具体操作', '附了录屏，但只覆盖问题出现之后的片段', '同组另有三人表示遇到过，未单独提交记录']
IMPACT = ['读者表示因此多花了约十分钟', '读者改为直接询问同事', '读者放弃查阅并重新提交了同一问题',
          '读者自行记了一份笔记代替', '读者表示以后会先用外部搜索', '读者未说明后续如何处理']
ADVICE = ['建议先补复现步骤，再区分内容问题与界面问题', '建议核对条目最近一次修改记录后再判断', '建议抽取同栏目的相邻条目，对比是否为共性问题',
          '建议先确认使用的设备与入口，再决定归类', '建议补充出现频次，再排处理顺序']


def record(number):
    """One ticket; number starts at 1 and is never reused."""
    i = number - 1
    topic, complaints = TOPICS[i % len(TOPICS)]
    complaint = complaints[i // len(TOPICS) % len(complaints)]
    # A hash keeps the mix reproducible on every Python version without short repeating cycles.
    scene, source, evidence, impact, advice = (pool[byte % len(pool)] for pool, byte in
                                               zip((SCENES, SOURCES, EVIDENCE, IMPACT, ADVICE), hashlib.sha256(str(number).encode()).digest()))
    return (f'工单 QL-{number:04}｜主题：{topic}。虚构读者组G{number % 9 + 1}在{scene}时，'
            f'先经栏目C{number % 7 + 1}进入，再以词条W{13 * number % 113:03}检索。{source}。反馈称{complaint}；'
            f'{evidence}。{impact}。{advice}。')

def batches(count=BATCHES, first=1, per_batch=PER_BATCH):
    """Batches are numbered from `first`; ticket numbers follow from the batch number."""
    turns = []
    for batch in range(first, first + count):
        start = (batch - 1) * per_batch + 1
        body = '\n'.join(record(n) for n in range(start, start + per_batch))
        turns.append({'id': f'load-{batch:02}', 'prompt': HEADER.format(batch=batch) + '\n\n' + body})
    return turns

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--extra', type=int, default=0,
                        help='不改写案例文件，只把接在内置负载之后的N批新编号负载输出为JSON')
    args = parser.parse_args()
    if args.extra < 0:
        parser.error('--extra 不能为负数')
    if args.extra:
        print(json.dumps(batches(args.extra, first=BATCHES + 1), ensure_ascii=False, indent=2))
        return
    case = json.loads(CASE.read_text(encoding='utf-8'))
    case['pressure_turns'] = batches()
    CASE.write_text(json.dumps(case, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(CASE)

if __name__ == '__main__':
    main()
