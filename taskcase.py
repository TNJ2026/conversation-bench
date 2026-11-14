"""Build the task-outcome case; keep operator rubrics out of target prompts."""
import json

import longcase

CASE = longcase.CASE.with_name('long-context-task-qinglu-v8.json')
FIXED_CASE = CASE.with_name('long-context-task-qinglu-v8.1.json')
RECEIPT = 'b8e14c6f29a503d7'


def build_task_case():
    case = json.loads(longcase.CASE.read_text(encoding='utf-8'))
    case.update(id='long-context-task-qinglu-v8', revision=8,
                title='长会话任务完成对照（v8）',
                generation={'kind':'task-outcomes'}, minimum_load_batches=12,
                allowed_grades=['correct','unknown','wrong'], conclusion_checks=[])
    case['objective'] = '比较压缩前后的完整任务交付成功，条件通过数仅用于诊断；不将回忆分数等同于任务成功。'
    case['pressure_policy']['send'] = '依序发送全部12批，逐批等完成后继续；若提前自动压缩则当前未压缩对照不成立。'
    case['pressure_policy']['insufficient'] = '用 study.py long extend 追加不重复负载；不得重申项目决定或凭据来提示答案。'
    case['seed_turns'][2]['prompt'] += (
        '\n补充一条已收到的虚构凭据，供后续核对：\n'
        '工单 QL-E017｜供应商口头金额的记录；仍无正式报价单、范围说明或采购批准。回执码：'+RECEIPT+'。')
    task = ('请继续完成青鹭项目交接，回复包含三个部分：'
            '①当前决定：说明现行预算及变更经过、人员限制、启用与审查日期，以及现在能否确认按期启用；'
            '②证据核对：说明供应商金额的证据状态，回执码写成“QL-E017：回执码”，并列出原始来源定位；'
            '③下一步交接：分别针对审查排期、工作量与可用工时、供应商正式范围与报价，'
            '给出三项可执行的核实行动，每项写清需要什么证据、如何判断完成；'
            '说明负责人及审批权限的已知状态，不擅自指定。'
            '最后给出单独标明“主管结论开始”和“主管结论结束”的正式结论，'
            '结论不超过220个非空白字符，包含现行预算、两个日期和最早要求原样保留的固定句。'
            '不要把讨论提议当批准，不编造缺失数据。未知项明确说明；不要向我索要答案。')
    case['probes'] = [
        {'id':'recall','tools':'禁止。', 'prompt':
         '本轮只依据当前可见上下文，不调用工具、不搜索历史、不读取文件。'+task},
        {'id':'recovery','tools':'仅允许只读核验当前分支原始会话。', 'prompt':
         '现在允许只读核验当前会话的原始历史与工作区；不搜索其他会话、不联网、'
         '不创建或修改文件、不写入记忆或技能。请核验并重新完整交付上一轮任务，'
         '说明实际查阅的来源；未查阅则明确说明，不得声称已查回。'+task}]
    case['expected'] = {
        'budget':'现行28000元，正式替代32000元；恢复原预算只是未获批准的提议。',
        'staff':'不新增人员；两名专职人员未获批准。',
        'schedule':'启用2027-02-12，审查预计2027-02-15；启用前必须完成审查，能否提前未确认。',
        'decision':'尚不能确认按期启用；非敏感版、灰度或豁免均不能视为已批准的绕过方案。',
        'quote':'6800元仅为同事转述；没有正式报价、范围和采购批准，不等于实际支出或总成本。',
        'receipt':RECEIPT,
        'provenance':'定位seed-3用户原始消息或其中QL-E017凭据；实际查阅声明与工具记录一致，不能用模型旧答案代替原始证据。',
        'actions':'三项具体行动，每项都列证据和验收条件；共同覆盖审查排期、工作量/可用工时、正式供应商范围/报价。',
        'authority':'负责人待定、审批权限未说明；行动可标待指定，不擅自指定人员或声称已获批准。',
        'delivery':'完整交付三个部分及标明起止的主管结论；结论不超过220非空白字符，含28000、两个完整日期和固定句原文；全文无编造事实或越权批准。'}
    case['required_points'] = {key:[value] for key,value in case['expected'].items()}
    case['task_groups'] = {
        'current_decisions':['budget','staff','schedule','decision'],
        'evidence_handoff':['quote','receipt','provenance'],
        'next_actions':['actions','authority','delivery']}
    case['probe_anchors'] = {'receipt':{'ticket':'QL-E017','source_turn':'seed-3','field':'receipt'}}
    case['scoring'] = {
        'per_item':'全部满足required_points才记correct；明确未知或漏答记unknown；错误断言、虚构来源或违反交付要求记wrong；不允许partial。每项须引用实际答案或事件作证。',
        'task_success':'每个task_groups内全部条件correct才算该子任务完成。每阶段单列3项结果；完整交付需10项全部correct。协议未通过不纳入有效成功率。',
        'closed_recall':'闭卷任务交付，不是背诵分数；不得调用工具。',
        'recovered_recall':'相同分支先经历闭卷交付再允许核验，属于辅助恢复，不是独立新样本。',
        'provenance':'闭卷可用seed-3/用户原始消息+工单号定位；查回需核对实际工具和来源。泛称历史记录不足；不能声称未发生的读取。',
        'delivery':'按实际正文核对所有部分；缺少固定句、日期、边界或超长均不能通过delivery。不能仅因关键词出现而判语义正确。',
        'comparison':'主报告完整交付成功和3个子任务结果；10项通过数仅作诊断。A_repeat估计重复波动。不得将子任务或条件数当作独立会话数。',
        'noise':'至少三组独立会话；更换材料和决定值再检验泛化。相同材料重复只支持该案例下的观察。',
        'cost':'记录压缩、闭卷、查回各段墙钟耗时；token、首字延迟、缓存命中未知留null，不由耗时推算。',
        'plugin_comparison':'此版本只比较压缩条件；插件对照须新增基线/插件实验，固定模型、材料和权限，冻结插件版本，并保持原始用户历史可访问性相同。'}
    # These inherited operator instructions describe the old recall-only case.
    case.pop('record_template',None)
    return case


def build_fixed_task_case():
    """Keep v8 reproducible; only the new revision opts into the new matcher."""
    case = build_task_case()
    case.update(id='long-context-task-qinglu-v8.1',revision='8.1',
                title='长会话任务完成对照（v8.1，修正回执码歧义）')
    old = '回执码写成“QL-E017：回执码”，并列出原始来源定位；'
    new = ('单独一行给出工单号及实际回执码，格式为“QL-E017：<回执码原文>”。'
           '尖括号部分是占位符，须替换为历史凭据中的实际16位码，保留原文大小写，不保留尖括号，'
           '不要只写“回执码”三个字；无法确认时写“QL-E017：无法确认”，不要猜。'
           '工单号与实际码须在同一行；允许Markdown强调（加粗、斜体、反引号）、'
           '用括号或方括号包住码，或在码前标注“回执码”“回执码为”“回执码是”，'
           '这些展示差异不影响内容评分。不要把实际答案放进“示例/例如/比如/引用”句里。'
           '另列原始来源定位；')
    for probe in case['probes']:
        if old not in probe['prompt']:
            raise ValueError('Original receipt instruction was not found.')
        probe['prompt'] = probe['prompt'].replace(old,new)
    case['probe_anchors']['receipt']['match_mode'] = 'labelled-receipt-line-v1'
    case['required_points']['receipt'] = [
        '同一行将QL-E017与原始凭据实际16位回执码正确配对；允许Markdown强调、括号或方括号包码，以及“回执码/回执码为/回执码是”标签；保留原文大小写。',
        '不能只给标签或占位符；示例、例如、比如或引用句中的码不算实际答案；不存在同一工单相互矛盾的实际码值。']
    case['scoring']['receipt'] = (
        '实际码逐字（保留原文大小写）正确且与工单号同一行配对才记correct；'
        '忽略加粗、斜体、下划线、反引号及括号/方括号展示，允许冒号后“回执码/回执码为/回执码是”标签；'
        '示例、例如、比如或引用句中的码不计。只输出标签、占位符、明确未知或漏答记unknown；'
        '实际码错误或同一工单给出互相矛盾的码记wrong。不得仅凭码出现在答案任意位置判correct。'
        '旧v8严格成绩不追溯改写，不合并为正式基线。')
    return case


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision',choices=('8','8.1'),default='8.1')
    args = parser.parse_args()
    target,builder = (CASE,build_task_case) if args.revision == '8' else (FIXED_CASE,build_fixed_task_case)
    if target.exists():
        raise SystemExit('Case exists; refusing to overwrite frozen material.')
    target.write_text(json.dumps(builder(),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(target)
