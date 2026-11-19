"""Evidence-complete, version-bound reviewer packets. No model calls or automatic semantic grading."""
import hashlib
import json
import random
import re
import uuid

FIELDS = ('factuality', 'instruction_following', 'usefulness')
# Each requirement is counted in exactly one dimension; untagged legacy requirements count as instruction.
DIMENSION = {'factuality': 'factuality', 'instruction_following': 'instruction', 'usefulness': 'usefulness'}
STATUSES = ('met', 'partial', 'missed', 'na')
MIN_QUOTE = 4
RUBRIC = {
    'factuality': '只评可核实的事实陈述。先判是否适用/证据充分；否则score=null并说明。编造来源、读取或验证证据，或>=2个关键事实错误=1；恰1个关键事实错误且无编造证据=2；无关键错但>=2个次要事实错误/无依据事实=3；恰1个次要问题=4；无已发现问题=5。dimension=factuality的本轮要求未满足或部分满足时，必须按其重要性计入counts；清单外另发现的事实错误可再加。虚构创作、明确假设与允许的推断不计事实错误。不得把“资料没提供”自动判成错误。无依据断言只在确定语气时计入：用确定语气陈述材料之外的内容计1个次要问题，带“可能、估计、假设、需确认”等限定或属于允许的推断不计，同一说法同一轮只计一次；影响结论、授权边界或执行条件的按关键问题计。',
    'instruction_following': '分数由本轮dimension=instruction的要求状态自动推导，不另填计数：关键missed>=2=1；关键missed=1为2；关键partial或次要missed/partial>=2为3；恰1项次要未满足为4；全部满足为5。只填requirements中各要求状态，na表示本轮无法判定且需说明；某维度有na要求时，该维度score须为null。事实类要求只计事实维度，同一问题不跨维度重复扣分。本轮没有dimension=instruction的要求时score须为null。字数上限按整条回复的全部非空白字符计（含标点、Markdown及交付物之外的说明），正文单独达标而整条回复超限判未满足。',
    'usefulness': '结合该用例的5/3/1锚点评估当轮产物。5=可直接用于指定目的；4=仅局部措辞/排版小改，不需新增事实或重排核心结构；3=需补充关键步骤或重组后才能用；2=只可保留零散内容，核心产物需重做；1=不可用或会误导行动。dimension=usefulness的要求（如未经要求的主动识别）只在此维度参考，不计入事实或指令。无法看到所需产物时score=null，不根据“已完成”措辞猜测可用性。',
}
PROTOCOL = {
    'version': 3,
    'unit': '每个已提交轮次分别评分；第1轮为初始表现；仅完成全部计划轮次时才有最终阶段。不得用最终修正覆盖前轮。',
    'completion': 'coverage单列计划/已提交/未提交轮次及终止状态。失败仍保留；未提交轮次不计满分、不计未知事实错误。任务完成度不得从三维文字分数推导。',
    'importance': 'critical=错误/遗漏会改变事实结论、授权边界、执行条件，或违反明确交付硬约束；minor=不改变这些内容的局部说明/风格要求。以逐例requirements为准，协议是否执行不计模型分。',
    'correction': '逐轮保留分数，另填corrections说明在哪一轮主动修正/经提示修正/仍未修正；后续修正不覆盖前轮分数。',
    'total': '报告按固定口径为每位评审、每个题组分别计算题目等权总分：每题先按轮平均各维度，再平均该题有分数的维度，同一题组内各题等权后乘以20；Advanced5与Challenge3分行，不合并；留空不计，未完成全部轮次的样本不计入并单列。不同评审的总分不合并、不平均。',
    'independence': 'r1与r2必须先独立填写各自副本，不看对方分数；填不同reviewer和真实review_type。AI评审填写model。独立性属于声明，软件不能证明。',
    'disagreement': '逐轮逐维比较两评；任一分歧保留双方证据，第三位评审填写scores-adjudicated.json及裁决原因。未裁决不合成分数；不求平均。',
    'evidence': f'每个数值评分都需该轮答案/产物/要求/来源的精确引用和解释，引文至少{MIN_QUOTE}个非空白字符（引用整段短文本除外）；缺失问题可用kind=requirement引用本轮生效的要求原文。要求状态和计数只做结构一致性验证，不是语义真伪证明。',
    'limits': '静态文件快照不能证明从未写入；未提供工具记录/观察证据时，执行行为不可判定。运行方式完整记录每轮工具调用（批量脚本）时，执行证据为空即视为未调用工具，“不联网”“不写文件”等要求判满足。材料/文本可能透露应用身份，分享前检查，不能保证完全匿名。',
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def recorded_verifications(record):
    """{turn number: [check rows]} from challenge_verify for Challenge3 records; empty for other cases."""
    try:
        import challenge_verify
        results = challenge_verify.verify(record)
    except (ImportError, ValueError, KeyError, TypeError):
        return {}
    labels = {'file_scope': '文件范围（challenge_verify）', 'dispatch_rows': 'dispatch.csv内容（challenge_verify）',
              'routing': 'routing.json仅改kiosk（challenge_verify）', 'dispatch_kept': 'dispatch.csv未被改动（challenge_verify）',
              'snapshot_complete': '快照完整（challenge_verify）'}
    return {item['turn']: [dict(check=labels.get(key, key), detail='评审侧结构化校验，只读记录、不执行被测代码；语义仍需人工判断',
                                **{'pass': value}) for key, value in item['checks'].items()]
            for item in results}


def sample_of(record, label):
    case = record['case']
    turns = []
    verified = recorded_verifications(record)
    for number, done in enumerate(record['turns'], 1):
        spec = case['turns'][number-1]
        observed = done.get('interruption_observed') is True
        intervention = done.get('intervention_text')
        # Old records have only the operator's declaration, never present it as a transcript.
        if observed and intervention is None:
            intervention = spec.get('interrupt_with')
        turns.append(dict(number=number, prompt=done['prompt'], answer=done['answer'],
            artifacts=done.get('artifacts', {}), checks=done.get('checks', []) + verified.get(number, []),
            files=done.get('files', {}), operator_notes=done.get('notes', ''),
            execution_evidence=done.get('execution_evidence', []),
            intervention={'text': intervention if observed else None,
                'observed': observed,
                'provenance': 'recorded-text' if done.get('intervention_text') else 'operator-declaration' if observed else 'not-observed',
                'delay_seconds': done.get('metrics', {}).get('interrupt_delay'),
                'first_write_delay_seconds': done.get('metrics', {}).get('first_write_delay'),
                'timing_evidence': done.get('interruption_evidence', '')},
            evidence_limits=['回答记录是整轮文本，不代表逐token时序；工具是否执行以独立记录为准。'] +
                ([] if done.get('execution_evidence') else ['没有结构化执行证据；仅靠回答不能验证操作声明。'])))
    planned = len(case['turns']); submitted = len(turns)
    sample = dict(id=label,
        case={k: case.get(k) for k in ('id', 'title', 'suite_version', 'family', 'polarity', 'acceptance', 'evaluation', 'protocol_criteria')},
        materials=case.get('fixtures', {}), intentionally_absent_materials=case.get('absent', []),
        initial_files=record.get('initial_files', {}),
        legacy_limits=[] if case.get('evaluation') else ['旧用例未提供逐轮要求重要性清单；应先独立确定评分口径，不能将新导出视为V3用例运行。'],
        planned_turns=[dict(number=i+1, prompt=t['prompt'], planned_intervention=t.get('interrupt_with'),
                            submitted=i < submitted) for i, t in enumerate(case['turns'])],
        coverage=dict(planned_turns=planned, submitted_turns=submitted,
                      missing_turns=list(range(submitted+1, planned+1)), termination=record['status'],
                      final_available=record['status'] == 'completed' and submitted == planned),
        turns=turns)
    sample['sample_sha256'] = digest(sample)
    return sample


def blank_dimension(field, derived=False):
    value = {'score': None, 'reason': '', 'evidence': []}
    if field == 'factuality': value['counts'] = {'critical': 0, 'minor': 0, 'fabricated_evidence': False}
    if field == 'instruction_following' and not derived:
        value['counts'] = {'critical_missed': 0, 'critical_partial': 0, 'minor_missed': 0}
    return value


def active_requirements(sample, number):
    requirements = (sample['case'].get('evaluation') or {}).get('requirements') or []
    return [r for r in requirements if number in r.get('active_turns', [])]


def dimension_of(requirement):
    return requirement.get('dimension', 'instruction')


def blank_turn(sample, number):
    active = active_requirements(sample, number)
    turn = dict(number=number, **{f: blank_dimension(f, bool(active)) for f in FIELDS})
    if active:
        turn['requirements'] = [dict(id=r['id'], dimension=dimension_of(r), importance=r['importance'],
                                     status=None, note='') for r in active]
    return turn


def requirement_counts(active, statuses, dimension):
    """Counts implied by the reviewer's statuses for one dimension."""
    critical = minor = partial = 0
    for req in active:
        if dimension_of(req) != dimension: continue
        status = statuses[req['id']]
        if status == 'missed' and req['importance'] == 'critical': critical += 1
        elif status == 'partial' and req['importance'] == 'critical': partial += 1
        elif status in ('missed', 'partial'): minor += 1
    return critical, partial, minor


def fenced(text, info='text'):
    """Verbatim block; the fence is longer than any backtick run inside, so content is never cut."""
    text = '' if text is None else str(text)
    longest = max((len(m) for m in re.findall(r'`+', text)), default=0)
    fence = '`' * max(3, longest + 1)
    return f'{fence}{info}\n{text}\n{fence}'


def file_changes(before, after):
    added = sorted(set(after) - set(before)); removed = sorted(set(before) - set(after))
    changed = sorted(k for k in set(before) & set(after) if before[k] != after[k])
    parts = [f'{label}：' + '、'.join(f'`{n}`' for n in names)
             for label, names in (('新增', added), ('删除', removed), ('改动', changed)) if names]
    return '；'.join(parts) or '无变化'


def render_markdown(packet):
    """Human-readable view of review.json. Scores are still entered in the scores-*.json files."""
    out = ['# 评审材料（只读视图）', '',
           '本文件由 review.json 生成，供阅读；评分仍填写在 scores-r1.json / scores-r2.json。'
           '引文须与原文逐字一致，请从下方代码块内复制。未来轮次的提示只用于判断覆盖，不视为已提交。', '',
           '## 评分规则', '']
    out += [f'- **{field}**：{text}' for field, text in packet['rubric'].items()]
    out += ['', '## 协议', '']
    out += [f'- **{key}**：{text}' for key, text in packet['protocol'].items()]
    out += ['', '## 样本目录', '']
    out += [f'- [{s["id"]}](#{s["id"].lower()}) {s["case"]["title"]}（{s["coverage"]["submitted_turns"]}/{s["coverage"]["planned_turns"]}轮，{s["coverage"]["termination"]}）'
            for s in packet['samples']]
    for sample in packet['samples']:
        case = sample['case']; ev = case.get('evaluation') or {}; cov = sample['coverage']
        out += ['', '---', '', f'## {sample["id"]}', '', f'**{case["title"]}**（`{case["id"]}`）', '',
                f'完成情况：已提交 {cov["submitted_turns"]}/{cov["planned_turns"]} 轮，终止状态 `{cov["termination"]}`'
                + ('' if cov['final_available'] else '，最终阶段未完成') + '。', '']
        if sample['legacy_limits']:
            out += ['> ' + x for x in sample['legacy_limits']] + ['']
        out += ['### 事实依据', ''] + [fenced(x) for x in ev.get('facts', [])] + ['']
        if ev.get('allowed_inferences'):
            out += ['### 允许的推断', ''] + ['- ' + x for x in ev['allowed_inferences']] + ['']
        if ev.get('usability_anchors'):
            out += ['### 实用性锚点', ''] + [f'- {k}分：{v}' for k, v in sorted(ev['usability_anchors'].items(), reverse=True)] + ['']
        out += ['### 要求清单', '', '|ID|维度|重要性|生效轮次|要求|', '|---|---|---|---|---|']
        out += [f'|{r["id"]}|{r.get("dimension", "instruction")}|{r["importance"]}|{",".join(map(str, r["active_turns"]))}|{r["text"]}|'
                for r in ev.get('requirements', [])]
        out += ['']
        if sample['materials']:
            out += ['### 预置材料', '']
            for name, content in sample['materials'].items():
                out += [f'`{name}`', '', fenced(content), '']
        if sample['intentionally_absent_materials']:
            out += ['刻意缺失的材料：' + '、'.join(f'`{n}`' for n in sample['intentionally_absent_materials']), '']
        previous_files = sample.get('initial_files', {}); seen = {}
        submitted = {t['number']: t for t in sample['turns']}
        for planned in sample['planned_turns']:
            number = planned['number']; out += ['', f'### 第{number}轮', '']
            turn = submitted.get(number)
            if turn is None:
                out += ['**未提交**，不评分。计划提示：', '', fenced(planned['prompt'])]; continue
            active = active_requirements(sample, number)
            out += ['**本轮生效要求**：' + ('、'.join(f'{r["id"]}({r.get("dimension", "instruction")[0].upper()}/{r["importance"]})' for r in active) or '无'), '',
                    '**提示**', '', fenced(turn['prompt']), '', '**回答**', '', fenced(turn['answer']), '']
            if turn['intervention'].get('observed'):
                out += ['**实际干预**', '', fenced(turn['intervention']['text']), '']
            if turn['operator_notes']:
                out += ['**操作员备注**（声明，非独立证据）', '', fenced(turn['operator_notes']), '']
            out += ['**文件变化**（相对上一轮末）：' + file_changes(previous_files, turn['files']), '']
            previous_files = turn['files']
            for name, content in turn['artifacts'].items():
                if seen.get(name, (None,))[0] == content:
                    out += [f'产物 `{name}`：与第{seen[name][1]}轮相同。', '']; continue
                seen[name] = (content, number)
                out += [f'<details><summary>产物 <code>{name}</code>（{len(content)} 字符）</summary>', '', fenced(content), '', '</details>', '']
            if turn['checks']:
                mark = {True: '通过', False: '**未通过**', None: '待人工'}
                out += ['**自动检查**', ''] + [f'- {mark[c["pass"]]} · {c["check"]}：{c["detail"]}' for c in turn['checks']] + ['']
            evidence = turn['execution_evidence']
            if evidence:
                out += [f'<details><summary>执行证据（{len(evidence)} 条，引用时用 kind=execution 与 index）</summary>', '']
                for index, item in enumerate(evidence):
                    out += [f'index {index} · {item["kind"]}', '', fenced(item['text'], 'json'), '']
                out += ['</details>', '']
            out += ['> ' + x for x in turn['evidence_limits']]
    return '\n'.join(out) + '\n'


def export(folder, groups):
    name = 'blind-' + uuid.uuid4().hex[:8]
    destination = folder/name; destination.mkdir()
    mapping = {}; samples = []; record_hashes = {}
    for i, group in enumerate(groups, 1):
        ordered = list(group.values()); random.SystemRandom().shuffle(ordered)
        for j, record in enumerate(ordered):
            label = f'P{i:03}-{chr(65+j)}'
            mapping[label] = record['job']; record_hashes[record['job']] = digest(record)
            samples.append(sample_of(record, label))
    packet = {'version': 3, 'protocol': PROTOCOL, 'rubric': RUBRIC, 'samples': samples}
    packet_hash = digest(packet)
    save(destination/'review.json', packet)
    (destination/'REVIEW-PACKET.md').write_text(render_markdown(packet), encoding='utf-8')
    for reviewer in ('r1', 'r2', 'adjudicated'):
        save(destination/f'scores-{reviewer}.json', dict(version=3, packet_sha256=packet_hash,
            reviewer='', review_type='', model='', independent=False, adjudication_reason='',
            samples=[dict(id=s['id'], sample_sha256=s['sample_sha256'], corrections='',
                turns=[blank_turn(s, t['number']) for t in s['turns']]) for s in samples]))
    save(folder/(name+'-KEY-DO-NOT-SHARE.json'), mapping)
    save(folder/(name+'-BINDING.json'), {'packet_sha256': packet_hash, 'mapping_sha256': digest(mapping), 'records': record_hashes})
    (destination/'REVIEW.md').write_text(
        '# 独立评审\n\n先读 review.json（或其只读视图 REVIEW-PACKET.md）的 protocol、材料、逐例验收标准和全部轮次。未来提示只供评审者判断覆盖，不视为已提交。\n\n'
        '分别将相同 review.json 与 scores-r1.json / scores-r2.json 交给两位独立评审，不给对方评分。填 reviewer、review_type（human/ai）、AI model、independent=true。\n\n'
        '每轮先填 requirements：每条本轮生效要求的 status 为 met/partial/missed/na，非met需在 note 写原因。'
        '指令分由instruction类要求的状态推导；事实类要求的未满足项必须计入factuality counts，清单外事实错误可另加；usefulness类要求只供实用性参考。同一问题不跨维度重复扣分。\n\n'
        '每维 reason 写具体解释；evidence 是精确引文列表，引文至少4个非空白字符（除非引用整段短文本）。例如 {"kind":"answer","turn":1,"quote":"原文片段"}；'
        '其他kind有 prompt、intervention、operator_notes（操作员声明）、artifact（还需name文件名）、material（需name，不需turn）、execution（需turn和index）、requirement（需id，只能引用本轮生效的要求）。'
        '引用不得跨越当前评分轮次。未知或不适用留score=null并说明原因。\n\n'
        '按rubric确定score；不要把程序验引文通过当语义正确。每个sample的corrections记录纠正情况，没有则写“未观察到纠正”。\n\n'
        '未完成的会话只评已观察轮次，不补写未来分数。任务完成情况与质量分并列；报告只按固定口径为每位评审分别计算总分，不跨评审平均。'
        '两评不一致时由第三位评审填写scores-adjudicated.json，保留原双评分并写裁决原因。\n', encoding='utf-8')
    return destination


def valid_text(value):
    return isinstance(value, str) and len(''.join(value.split())) >= 6


def verify_quote(ref, sample, current_turn):
    if not isinstance(ref, dict) or not isinstance(ref.get('quote'), str) or not ref['quote'].strip():
        raise ValueError('证据必须含非空精确引文')
    kind = ref.get('kind')
    if kind == 'material':
        text = sample['materials'].get(ref.get('name'))
    elif kind == 'requirement':
        req = next((r for r in active_requirements(sample, current_turn) if r['id'] == ref.get('id')), None)
        if req is None: raise ValueError('只能引用本轮生效的要求')
        text = req['text']
    else:
        number = ref.get('turn')
        if type(number) is not int or not 1 <= number <= current_turn:
            raise ValueError('证据轮次无效或引用未来轮次')
        turn = sample['turns'][number-1]
        if kind in ('prompt', 'answer', 'operator_notes'): text = turn[kind]
        elif kind == 'intervention': text = turn['intervention']['text']
        elif kind == 'artifact': text = turn['artifacts'].get(ref.get('name'))
        elif kind == 'execution':
            index = ref.get('index')
            if type(index) is not int or not 0 <= index < len(turn['execution_evidence']):
                raise ValueError('执行证据索引无效')
            text = turn['execution_evidence'][index]['text']
        else: raise ValueError('未知证据类型')
    if not isinstance(text, str) or ref['quote'] not in text:
        raise ValueError('引文与评审快照不匹配')
    if len(''.join(ref['quote'].split())) < MIN_QUOTE and ref['quote'].strip() != text.strip():
        raise ValueError(f'引文过短：至少{MIN_QUOTE}个非空白字符，或引用整段原文')


def expected_score(field, counts):
    if not isinstance(counts, dict): raise ValueError('缺少问题计数')
    keys = ('critical', 'minor') if field == 'factuality' else ('critical_missed', 'critical_partial', 'minor_missed')
    if any(type(counts.get(k)) is not int or counts[k] < 0 for k in keys):
        raise ValueError('问题计数必须为非负整数')
    if field == 'factuality':
        if type(counts.get('fabricated_evidence')) is not bool: raise ValueError('编造证据标记必须为布尔值')
        if counts['fabricated_evidence'] or counts['critical'] >= 2: return 1
        if counts['critical']: return 2
        return 3 if counts['minor'] >= 2 else 4 if counts['minor'] else 5
    if counts['critical_missed'] >= 2: return 1
    if counts['critical_missed']: return 2
    if counts['critical_partial'] or counts['minor_missed'] >= 2: return 3
    return 4 if counts['minor_missed'] else 5


def validate_sheet(sheet, packet, packet_hash, adjudicated=False):
    if sheet.get('version') != 3 or sheet.get('packet_sha256') != packet_hash:
        raise ValueError('评分版本或评审包散列不匹配')
    if not isinstance(sheet.get('reviewer'), str) or not sheet['reviewer'].strip():
        raise ValueError('缺少评审者身份')
    if sheet.get('review_type') not in ('human', 'ai') or (sheet['review_type'] == 'ai' and not sheet.get('model')):
        raise ValueError('需填写真实评审类型与AI模型')
    if not adjudicated and sheet.get('independent') is not True: raise ValueError('未声明独立评审')
    if adjudicated and not valid_text(sheet.get('adjudication_reason')): raise ValueError('缺少裁决说明')
    submitted = sheet.get('samples')
    if not isinstance(submitted, list) or any(not isinstance(s, dict) for s in submitted) or [s.get('id') for s in submitted] != [s['id'] for s in packet['samples']]:
        raise ValueError('评分样本缺失、重复或顺序不符')
    for row, sample in zip(submitted, packet['samples']):
        if row.get('sample_sha256') != sample['sample_sha256']: raise ValueError('样本散列不匹配')
        if not valid_text(row.get('corrections')): raise ValueError('需记录纠正情况，不得以最终成绩覆盖历史')
        turns = row.get('turns')
        if not isinstance(turns, list) or any(not isinstance(t, dict) for t in turns) or [t.get('number') for t in turns] != [t['number'] for t in sample['turns']]:
            raise ValueError('评分轮次缺失、重复或虚构未提交轮次')
        for turn in turns:
            active = active_requirements(sample, turn['number'])
            statuses = check_statuses(turn, active)
            derived = {}
            if active:
                critical, partial, minor = requirement_counts(active, statuses, 'instruction')
                derived['instruction_following'] = dict(critical_missed=critical, critical_partial=partial, minor_missed=minor)
                derived['factuality'] = requirement_counts(active, statuses, 'factuality')
            graded = bool((sample['case'].get('evaluation') or {}).get('requirements'))
            value = turn.get('instruction_following')
            if (graded and isinstance(value, dict) and value.get('score') is not None
                    and not any(dimension_of(r) == 'instruction' for r in active)):
                raise ValueError('本轮没有instruction类要求，instruction_following的score须为null')
            for field in FIELDS:
                value = turn.get(field)
                if not (isinstance(value, dict) and value.get('score') is not None and active): continue
                own = [statuses[r['id']] for r in active if dimension_of(r) == DIMENSION[field]]
                if None in own:
                    raise ValueError(f'{field}已打分，本轮{DIMENSION[field]}类要求状态未填完')
                # na adds nothing to the miss counts, so a score would treat the unknown as satisfied.
                if 'na' in own:
                    raise ValueError(f'{field}有本轮无法判定（na）的要求，该维度score须为null并说明')
            for field in FIELDS:
                value = turn.get(field)
                if not isinstance(value, dict) or not valid_text(value.get('reason')):
                    raise ValueError(f'{field}需逐维填写依据或不可判定原因')
                score = value.get('score')
                if score is not None and (type(score) is not int or not 1 <= score <= 5): raise ValueError('分数必须为1–5或null')
                refs = value.get('evidence')
                if not isinstance(refs, list) or (score is not None and not refs): raise ValueError('数值评分缺少证据')
                for ref in refs: verify_quote(ref, sample, turn['number'])
                if score is None or field == 'usefulness': continue
                counts = value.get('counts')
                if field == 'instruction_following' and active:
                    if counts is not None and counts != derived[field]:
                        raise ValueError('指令计数由要求状态推导，不得另填不同数值')
                    counts = derived[field]
                if field == 'factuality' and active:
                    expected_score(field, counts)  # validates the structure first
                    critical, partial, minor = derived['factuality']
                    if counts['critical'] < critical + partial or counts['minor'] < minor:
                        raise ValueError('事实类要求未满足，但factuality计数未计入')
                if score != expected_score(field, counts):
                    raise ValueError('分数与错误严重程度/数量不一致')
    return sheet


def check_statuses(turn, active):
    """Statuses for exactly the requirements active in this turn, in order."""
    rows = turn.get('requirements', [] if not active else None)
    if not isinstance(rows, list) or any(not isinstance(x, dict) for x in rows) or [x.get('id') for x in rows] != [r['id'] for r in active]:
        raise ValueError('要求状态必须逐条覆盖本轮生效要求，不得遗漏、虚构或调换顺序')
    for row in rows:
        if row.get('status') is not None and row['status'] not in STATUSES:
            raise ValueError('要求状态只能为met/partial/missed/na或null')
        if row.get('status') not in (None, 'met') and not valid_text(row.get('note')):
            raise ValueError('未满足、部分满足或不可判定的要求需在note说明原因')
    return {row['id']: row.get('status') for row in rows}


def bound_sheets(folder, name, by_job):
    """Packet, identity mapping, valid sheets and [(reviewer, error)] of one export; raises when the binding is broken."""
    directory = folder/name
    load = lambda p: json.loads(p.read_text(encoding='utf-8'))
    binding = load(folder/(name+'-BINDING.json')); packet = load(directory/'review.json')
    mapping = load(folder/(name+'-KEY-DO-NOT-SHARE.json'))
    if digest(packet) != binding['packet_sha256']: raise ValueError('评审包被修改')
    if digest(mapping) != binding['mapping_sha256']: raise ValueError('身份映射被修改')
    for job, expected in binding['records'].items():
        if digest(by_job[job]) != expected: raise ValueError('原始记录已改变，旧评分不得绑定到新答案')
    sheets = {}; invalid = []
    for reviewer in ('r1', 'r2', 'adjudicated'):
        sheet = load(directory/f'scores-{reviewer}.json')
        if not sheet.get('reviewer'):
            # A filled score without an identity is invalid, not an untouched template.
            if any(t.get(f, {}).get('score') is not None for s in sheet.get('samples', []) for t in s.get('turns', []) for f in FIELDS):
                raise ValueError(f'{reviewer}已打分但缺少评审者')
            continue
        try:
            sheets[reviewer] = validate_sheet(sheet, packet, binding['packet_sha256'], reviewer == 'adjudicated')
        except (ValueError, TypeError, KeyError) as error:
            invalid.append((reviewer, str(error)))
    identities = [s['reviewer'] for s in sheets.values()]
    if len(set(identities)) != len(identities): raise ValueError('独立评审/裁决者身份重复')
    return packet, mapping, sheets, invalid


def sample_score(turns):
    """(mean of the dimensions that have a score, {dimension: mean over scored turns}); None when nothing is scored."""
    dims = {}
    for field in FIELDS:
        marks = [t[field]['score'] for t in turns if t[field]['score'] is not None]
        if marks: dims[field] = sum(marks)/len(marks)
    return (sum(dims.values())/len(dims) if dims else None), dims


def suite_of(case):
    """Component suite a case belongs to; cases built before suites were tagged return None."""
    return case.get('suite')


def totals(folder, records):
    """Equal-weight total per export, reviewer, product and component suite.

    Reviewers are never merged; unfinished samples are left out and counted. Advanced5 and
    Challenge3 are reported on separate rows, so the harder challenge cases are never averaged
    into the same total as the advanced cases."""
    output = []; by_job = {r['job']: r for r in records}
    for binding_file in sorted(folder.glob('blind-*-BINDING.json')):
        name = binding_file.name[:-len('-BINDING.json')]
        try:
            packet, mapping, sheets, _ = bound_sheets(folder, name, by_job)
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue  # rows() reports the broken binding
        for slot, sheet in sheets.items():
            groups = {}
            for sample, row in zip(packet['samples'], sheet['samples']):
                record = by_job[mapping[sample['id']]]
                key = record['product'], suite_of(record['case'])
                group = groups.setdefault(key, dict(scores=[], dims={f: [] for f in FIELDS}, unfinished=0, unscored=0))
                if not sample['coverage']['final_available']: group['unfinished'] += 1; continue
                score, dims = sample_score(row['turns'])
                if score is None: group['unscored'] += 1; continue
                group['scores'].append(score)
                for field, value in dims.items(): group['dims'][field].append(value)
            for (product, suite), group in sorted(groups.items(), key=lambda item: (item[0][0], item[0][1] or '')):
                mean = lambda values: sum(values)/len(values) if values else None
                total = mean(group['scores'])
                output.append(dict(export=name, slot=slot, reviewer=sheet['reviewer'], product=product, suite=suite,
                    total=None if total is None else total*20, samples=len(group['scores']),
                    unfinished=group['unfinished'], unscored=group['unscored'],
                    dimensions={f: dict(mean=mean(v), samples=len(v)) for f, v in group['dims'].items()}))
    return output


def totals_markdown(items):
    if not items: return ''
    show = lambda v, digits=2: '—' if v is None else f'{v:.{digits}f}'
    lines = ['', '## 评审总分', '',
             '每题先按轮平均各维度，再平均该题有分数的维度；同一题组内各题等权，乘以20换算为百分制。Advanced5与Challenge3分行计算，不合并。留空不计，未完成全部轮次的样本不计入。'
             '每位评审单独一行，不合并、不平均；总分不代表任务完成度，评审之间的差异见逐轮结果。', '',
             '| 导出 | 评审 | 配置 | 题组 | 总分 / 100 | 计分题数 | 未完成 | 事实（题数） | 指令（题数） | 实用性（题数） |', '|---|---|---|---|---:|---:|---:|---:|---:|---:|']
    for x in items:
        dims = ' | '.join(f'{show(x["dimensions"][f]["mean"])}（{x["dimensions"][f]["samples"]}）' for f in FIELDS)
        lines.append(f'| {x["export"]} | {x["slot"]} · {x["reviewer"]} | {x["product"]} | {x["suite"] or "—"} | {show(x["total"])} | {x["samples"]} | {x["unfinished"]} | {dims} |')
    return '\n'.join(lines) + '\n'


def rows(folder, records):
    """Report independent judgments without averaging; reject changed inputs or invalid scores."""
    output = []; by_job = {r['job']: r for r in records}
    for binding_file in sorted(folder.glob('blind-*-BINDING.json')):
        name = binding_file.name[:-len('-BINDING.json')]
        try:
            packet, mapping, sheets, invalid = bound_sheets(folder, name, by_job)
            for reviewer, message in invalid:
                output.append([name, reviewer, '', '', '', '', '', '', '', '评分无效：'+message])
            for i, sample in enumerate(packet['samples']):
                r = by_job[mapping[sample['id']]]
                cov = sample['coverage']
                coverage = f'{cov["submitted_turns"]}/{cov["planned_turns"]}；{cov["termination"]}'
                if not cov['final_available']: coverage += '；最终阶段未完成'
                if not sheets or not sample['turns']:
                    output.append([name, sample['id'], r['product'], coverage, '无已评轮次', '', '', '', '', '未评分'])
                for j, turn in enumerate(sample['turns']):
                    marks = {k: [v['samples'][i]['turns'][j][f]['score'] for f in FIELDS] for k, v in sheets.items()}
                    status = '单评，未复核'
                    if 'r1' in marks and 'r2' in marks:
                        status = '两评一致（未证明语义正确）' if marks['r1'] == marks['r2'] else '有分歧，待裁决'
                        if 'adjudicated' in marks: status = '已裁决，保留双评分'
                    elif 'adjudicated' in marks: status = '裁决缺少完整双评，不采纳'
                    stage = '初始' if turn['number'] == 1 else '中间'
                    if cov['final_available'] and turn['number'] == cov['planned_turns']: stage += '/最终'
                    for k, values in marks.items():
                        row = sheets[k]['samples'][i]['turns'][j]
                        evidence = json.dumps({**{f: row[f] for f in FIELDS}, 'requirements': row.get('requirements', []),
                            'corrections': sheets[k]['samples'][i]['corrections'],
                            'reviewer': sheets[k]['reviewer'], 'review_type': sheets[k]['review_type'],
                            'model': sheets[k]['model'], 'adjudication_reason': sheets[k].get('adjudication_reason', '')}, ensure_ascii=False)
                        output.append([name, sample['id'], r['product'], coverage, f'{turn["number"]}({stage})/{k}',
                                       *['不可判定' if v is None else v for v in values], status, evidence])
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            output.append([name, '', '', '', '', '', '', '', '', '评审绑定无效：'+str(error)])
    return output
