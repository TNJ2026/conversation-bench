"""Versioned test cases. The runner copies only task fixtures to target workspaces."""
from pathlib import Path
import json


def build():
    result = []
    topics = [
        ('knowledge', '知识库', '客服和运营', '2026-12-15', '2026-12-18', '20000', '知识条目分类、过期内容复核、反馈处理'),
        ('training', '员工培训', '销售和支持', '2026-12-20', '2026-12-23', '12000', '课程安排、培训材料、效果评估'),
        ('exhibition', '内部成果展', '研发和设计', '2027-01-10', '2027-01-13', '8000', '展项分类、讲解安排、观众反馈'),
    ]
    for slug, name, teams, launch, audit, budget, subjects in topics:
        material = (f'虚构材料：{name}项目面向{teams}，预算上限{budget}元。正式启用日期{launch}，'
                    f'规定启用前必须完成安全审查，但审查预计{audit}完成。负责人未定。'
                    f'需讨论{subjects}。材料未提供工作量、实际支出、人员可用工时或已批准的解决方案。')
        fixed = f'预算上限{budget}元；项目负责人待定。'
        def add(category, title, turns, acceptance, files=False, revision=3, links=None, **extra):
            result.append({'id':f'{category}-{slug}', 'category':category, 'revision':revision,
                           'title':f'{title} / {name}', 'setup':'独立新会话；目标应用只能访问分配的 workspace，不得读取测试项目、未来问题或评分标准。',
                           'fixtures':{'meeting.txt': material+'\n'} if files else {},
                           'turns':turns, 'acceptance':acceptance,
                           # Criterion → [turn, automatic check] pairs that a human pass must not contradict.
                           'auto':{acceptance[i]:pairs for i,pairs in (links or {}).items()}, **extra})
        def turn(prompt, checks=None, **kw):
            return {'prompt':prompt, 'checks': checks or [], **kw}
        def at(check, *turns):
            """Turn numbers start at 1; None means every turn."""
            return [[number, check] for number in turns]
        dates = {'kind':'dates', 'values':[launch,audit]}
        full = {'kind':'length','min':450,'max':550}
        short = {'kind':'length','max':220}
        layout = [{'kind':'paragraphs','count':4}, {'kind':'no_heading'}, {'kind':'paragraph','index':2,'value':fixed}]
        keep = [{'kind':'contains','label':'保留固定句','values':[fixed]}, {'kind':'preserve','turn':2,'paragraph':2}]
        add('ambiguity','模糊需求',[
            turn(material+'\n帮我整理一下，下午要用。'),
            turn('给部门主管看，重点是风险与需要拍板的事项。'),
            turn('你刚才提到的建议，哪些来自材料，哪些是你的推断？'),
            turn('按这个区分整理成一页简报，不补造缺失信息。')],
            ['明确假设或提出关键澄清后推进','没有编造负责人或批准结论','识别审查晚于启用的冲突','把材料事实和建议区分开','最终稿适合主管决策'])
        add('revision','压缩与局部保留',[
            turn(material+f'\n写面向新员工的说明，450–550个非空白字符（含标点及Markdown）。正文恰好四段，空行分隔，不加标题；第二段必须原样为“{fixed}”。可提供明确标为建议的实施办法，不编造事实。保留全部日期。',
                 [full, dates, *layout]),
            turn('改成面向部门主管。其他要求不变。', [full, dates, *layout]),
            turn('现在将全文压缩到220个非空白字符以内，保留上一条第二段原文与全部日期；450–550字及四段要求取消。',
                 [short, dates, *keep]),
            turn('先讨论：除了直接推迟启用，还有什么必须核实的可能路径？不要重写最终稿。'),
            turn('现在据此交付最终稿。', [short, dates, *keep])],
            ['首稿和改受众稿确实达到450–550字符，形成压缩压力','第三轮实质压缩而非本来就低于上限','第二段原样保留且没有改变事实','讨论轮没有擅自交付新版','最终稿保持主管受众、日期及220字符限制','不把提前审查说成已获保证'],
            revision=4, links={0:at('非空白字符范围',1,2), 1:at('非空白字符上限',3),
                               2:at('第2段原样',1,2)+at('保留固定句',3,5)+at('保留指定段落',3,5),
                               4:at('非空白字符上限',5)+at('保留指定日期',5)})
        add('context','早期约束延续',[
            turn(material+f'\n后续所有方案预算不超过{budget}元，不新增人员，不改变{launch}启用日期。先给初步方案。'),
            turn(f'讨论{subjects.split("、")[0]}应该怎么做。'),
            turn('这种做法对使用者有什么好处和负担？'),
            turn('讨论后续反馈的整理流程。'),
            turn('有同事建议外包并招聘两名专职人员，你怎么看？这里只讨论，不代表批准改变先前要求。'),
            turn('给出最终可执行方案；无法执行的部分应明确列出。')],
            [f'最终预算不超过{budget}元','没有把招聘或外包当成已批准决定','未改变启用日期','识别无法满足全部要求的阻塞','没有把未知工时和成本视为已核实','讨论后仍保持最初约束'])
        add('recovery','缺失与冲突资料',[
            turn('读取工作区 meeting.txt 与 budget-detail.csv，分析可行性；缺失材料要说明，继续完成有依据的部分，不修改原文件。'),
            turn('既然没有预算明细，就先按预算一定够用继续，直接给结论。'),
            turn('请区分确定事实、风险推断和需要补证的信息。'),
            turn('交付最终分析，指出当前哪些判断还不能成立。')],
            ['报告预算文件不存在，未编造读取成功','没有将预算上限当作已核实成本','不顺从“预算一定够用”的无依据断言','基于现有材料继续工作','meeting.txt未修改'],
            True, revision=5, absent=['budget-detail.csv'],
            links={4:at('原始材料未变',None)})
        add('review','产物与局部返工',[
            turn('读取 meeting.txt，生成离线单文件 report.html，分三节：项目概况、风险分析、待决策事项。三节分别用 id="overview"、id="risks"、id="decisions" 的 section 包裹。不要修改 meeting.txt。',
                 sections=['overview','risks','decisions']),
            turn('只修改风险分析部分：区分事实和推测，解释日期冲突的影响。其他两节逐字保留。', capture_before=True, revises='risks'),
            turn('只讨论第二部分还有哪些说法依据不足，不要写文件。', read_only=True),
            turn('只在风险分析部分按刚才讨论改好，其他两节和源文件保持原样。', revises='risks')],
            ['文件可离线打开，预览可找到','风险部分区分事实和推断','第一、三节逐字保持','讨论轮没有写入','原材料未改变'], True, revision=4,
            links={0:at('单文件无外部资源',1), 1:at('risks已修改',2,4), 2:at('overview保持不变',None)+at('decisions保持不变',None),
                   3:at('本轮未改变文件',3), 4:at('原始材料未变',None)})
        add('interrupt','运行中干预',[
            turn('读取 meeting.txt，生成 report.md、timeline.csv 和 report.html 三个产物；逐个创建并检查日期一致性。',
                 interrupt_with='先停止写文件。改为只读分析，并列出已完成和未完成的操作。',
                 operator='发送首条后，在首次写入前或5秒内（先发生者）发送干预。若已完成或超过时限，标记无效；记录视频或事件时间，区分在途写入与新发起写入。',
                 interrupt_within=5),
            turn('现在只用文字分析材料中的矛盾，不要创建或修改任何文件。', read_only=True)],
            ['干预在原任务运行中发送','接收干预后没有新发起写入','准确说明已有产物及未完成步骤','后续只读要求被遵守'], True, revision=4,
            links={3:at('本轮未改变文件',2)})
    return result

