#!/usr/bin/env python3
"""Synthetic pressure load for the long-context compaction case.

Regenerates only pressure_turns; seed turns, probes and scoring stay hand-written.
"""
import argparse
import hashlib
import hmac
import json
from pathlib import Path
import secrets

CASE = Path(__file__).with_name('cases')/'long-context-compaction-qinglu.json'
BATCHES, PER_BATCH = 12, 32
DETAIL_CASE = CASE.with_name('long-context-compaction-qinglu-v7.json')
PROBE_TICKETS = (7,19,33,97,161,199,245,281,300,353)

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


def detail_batches(seed, count=BATCHES, first=1):
    """Private keyed receipts: later tickets cannot reveal an earlier ticket's value."""
    turns = batches(count, first)
    key = bytes.fromhex(seed)
    for turn in turns:
        lines = turn['prompt'].splitlines()
        for i,line in enumerate(lines):
            if line.startswith('工单 QL-'):
                ticket = line.split('｜',1)[0].removeprefix('工单 ')
                receipt = hmac.new(key,ticket.encode(),hashlib.sha256).hexdigest()[:16]
                lines[i] = line + ' 回执码：' + receipt + '。'
        turn['prompt'] = '\n'.join(lines)
    return turns


def build_detail_case(seed=None):
    case = json.loads(CASE.read_text(encoding='utf-8'))
    seed = seed or secrets.token_hex(32)
    case.update(id='long-context-compaction-qinglu-v7',revision=7,
                title='长会话压缩前后对照 / 独立工单回执码（v7）',
                generation={'kind':'keyed-receipts','private_seed':seed},
                pressure_turns=detail_batches(seed),minimum_load_batches=12,
                allowed_grades=['correct','unknown','wrong'],conclusion_checks=[])
    ticket_list = '、'.join(f'QL-{n:04}' for n in PROBE_TICKETS)
    case['probes'] = [
        {'id':'recall','tools':'禁止，违反则闭卷协议无效。','prompt':
         '只依据当前可见上下文作答，不要调用工具、搜索历史或读取文件。按顺序给出下列工单的回执码，每行“工单号：回执码”，保留原文大小写；不确定写“无法确认”，不要猜。'+ticket_list+'。'},
        {'id':'recovery','tools':'允许只读，逐项记录真实来源。','prompt':
         '允许以只读方式查看原始会话记录与工作区，不要创建或修改文件、不写入记忆或技能。逐行核对上一轮的十个工单回执码，写成“工单号：回执码（来源定位）”，并说明哪些仍无法确认。'}]
    case['expected'], case['probe_anchors'] = {}, {}
    for i,number in enumerate(PROBE_TICKETS,1):
        anchor, ticket = f'f{i}', f'QL-{number:04}'
        turn_id = f'load-{(number-1)//PER_BATCH+1:02}'
        case['expected'][anchor] = hmac.new(bytes.fromhex(seed),ticket.encode(),hashlib.sha256).hexdigest()[:16]
        case['probe_anchors'][anchor] = {'ticket':ticket,'source_turn':turn_id,'field':'receipt'}
    case['required_points'] = {a:[value] for a,value in case['expected'].items()}
    case['pressure_policy']['insufficient'] = '自动运行时用 study.py long extend 追加负载；运行器会沿用本案例私有种子生成不重复的工单回执码。'
    case['scoring'].update(
        per_item='回执码逐字正确记correct；明确无法确认或漏答记unknown；明确给出错误回执码记wrong。禁止partial。按probe_anchors核对工单与回执码对应关系。',
        closed_recall='保留分=correct数，满分10；错误项数=wrong数。并列报告correct/unknown/wrong，漏答另记。',
        recovered_recall='按相同三档记录查回后结果与实际来源。不能把其他分支回答作为原始来源。',
        constraints='不要求主管结论，只检查只读、记忆与访问隔离。',
        comparison='分别报告A、A_repeat、B的正确数、未知数、错误数、查回来源及B−A、A_repeat−A；不合成总排名。',
        source_sensitivity='探针会提示被询问的工单号，但不提供回执码。当前未压缩尾部不包含早期回执码，不能由主题循环推出回执码。',
        summary_retention='按probe_anchors逐项检查摘要是否保留原始回执码，不能由最终答对数倒推。',
        conclusion_length_scope='本版不要求主管结论，不应用字数、预算、日期或固定句检查。',
        prompt_scope='只评probe_anchors列出的十个工单回执码，项目预算等seed事实不作为本版记忆评分锚点。')
    case['record_template']['anchor_grades_format'] = '每个f1..f10只允许correct/unknown/wrong，按probe_anchors核对原始回执码。'
    case['record_template']['summary_anchor_review'] = None
    return case


def extra_batches(case, count, first):
    generation = case.get('generation', {})
    if generation.get('kind') == 'transfer-keyed-receipts':
        raise ValueError('Transfer materials freeze exactly 12 batches; create a new case instead of extending.')
    if generation.get('kind') == 'keyed-receipts':
        return detail_batches(generation['private_seed'],count,first)
    return batches(count,first)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--extra', type=int, default=0,
                        help='不改写案例文件，只把接在内置负载之后的N批新编号负载输出为JSON')
    parser.add_argument('--build-v7',action='store_true',help='生成新的独立随机回执码案例，不覆盖已有v7文件')
    args = parser.parse_args()
    if args.build_v7:
        if args.extra:
            parser.error('--build-v7 不能和 --extra 同用')
        if DETAIL_CASE.exists():
            parser.error('v7文件已存在，不覆盖；如需新材料实例，另存 build_detail_case() 的返回值')
        DETAIL_CASE.write_text(json.dumps(build_detail_case(),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(DETAIL_CASE)
        return
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
