"""Fresh, keyed transfer materials; no benchmark-specific parsing in the plugin."""
import hashlib
import hmac
import json
from pathlib import Path
import secrets

CASE_DIR = Path(__file__).parent/'cases'
RUNNER_FILES = ('transfercase.py','longrun.py','longcase.py','history_plugin.py','webhost_driver.py','dsh_driver.py')


def runner_hashes():
    return {str(Path(__file__).resolve().parent/name):hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()
            for name in RUNNER_FILES}


def build_case(seed):
    key=bytes.fromhex(seed)
    if len(key)!=32:
        raise ValueError('Material seed must contain 32 bytes.')
    def code(label):return hmac.new(key,label.encode(),hashlib.sha256).hexdigest()[:16]
    offset=int(code('identifiers')[:4],16)%600
    ids={f'f{i}':f'LB-{offset+i*37:04}' for i in range(1,11)}
    ids['f6']=f'LB-Ω{offset+222:04}'
    expected={f'f{i}':code(f'final-{i}') for i in range(1,11)}
    expected['f9']=expected['f9'].upper()
    budget=54000+int(code('budget')[:2],16)*100
    latest=budget-7300
    day=10+int(code('date')[:2],16)%10
    launch=f'2027-06-{day:02}'
    review=f'2027-06-{day+3:02}'
    disclaimer='本交接不构成启用、采购或人员调整授权。'
    seeds=[
        {'id':'seed-1','prompt':f'这是虚构的“岚桥设备维保交接”项目，仅在聊天中协助，不创建或修改文件、不写入记忆或技能。初始预算上限{budget}元，不增加人员；计划启用日{launch}，启用前必须完成数据核验；核验预计{review}完成，能否提前未知。项目负责人待定，审批权限归属未说明，工作量、工时和实际支出均未提供。正式结论原样保留“{disclaimer}”。请用180个非空白字符以内区分已知与未知，不使用工具。'},
        {'id':'seed-2','prompt':f'正式更新：预算上限由{budget}元下调为{latest}元，自本条生效，其余约束不变。这是明确决定，无需另行推定审批等级。请确认，不编造外部文件状态。'},
        {'id':'seed-3','prompt':'会上有人建议恢复旧预算、临时增加两名人员、绕过数据核验先行启用；均未批准，能否豁免未核实。下面会分批给巡检历史材料，每条签收回执均为独立码。归档、作废、旧版本不作为最终回执；后续若同一编号有正式替代签收，以明确的最终正式版本为准。请先分析应核实的证据，不批准任何提议。'}]
    pressure=[]
    quotes={}
    def put(anchor,batch,text):
        pressure[batch-1]['prompt']+='\n\n'+text
        quotes[anchor]={'ticket':ids[anchor],'source_turn':f'load-{batch:02}',
                        'field':'receipt','match_mode':'labelled-receipt-line-v1','source_quote':text}
    scenes=['传感器读数与点位对照','巡检附件来源核对','维护日志时间核对','签收人字段待核实']
    for batch in range(1,13):
        lines=[]
        for j in range(32):
            n=(batch-1)*32+j+1
            token=code(f'load-{n}')
            lines.append(f'巡检条目RF-{n:04}｜点位P{n%19:02}，区域Z{n%7}。任务为{scenes[n%4]}。记录由虚构值班组整理，附件仅描述现场现象，尚不足以判断设备损坏或人员责任。条目记载入口、观察时段和当班备注，但缺少连续读数、仪表校准记录及完整照片。应核对采集条件、仪表编号、复核时间与原始留存，再区分偶发观察和持续异常，不以单条备注推断故障频率。归档索引{token}。')
        # More than ten user-event hits for this id; only the final signed entry is effective.
        lines.append(f'归档备忘：{ids["f5"]} 的旧票据版本{batch}，已作废；旧码{code(f"old-repeat-{batch}")}，不可作为正式签收。')
        pressure.append({'id':f'load-{batch:02}','prompt':f'第{batch}批巡检历史。只按问题类型归类，选两条列所需证据；240个非空白字符以内，不改变项目决定，不用工具、不写文件。\n'+'\n'.join(lines)})
    put('f1',1,f'记录编号：{ids["f1"]}\n对象：东侧供水泵\n状态：正式签收\n回执码：{expected["f1"]}')
    put('f2',2,f'对象A编号NEIGHBOR-A，回执码{code("left") }；对象B编号{ids["f2"]}，正式签收回执码{expected["f2"]}；对象C编号NEIGHBOR-C，回执码{code("right")}。三者不可串配。')
    pressure[2]['prompt']+=f'\n记录{ids["f3"]}，旧版本v1，已作废，码{code("old-version")}。'
    put('f3',8,f'记录{ids["f3"]}，正式替代签收v2，最终回执码{expected["f3"]}；此前v1作废，不能沿用。')
    put('f4',4,f'记录编号{ids["f4"]}，正式签收；'+('附注为原始采集位置与核对过程，不能由附注推断审批或采购决定。'*45)+f'最终回执码：{expected["f4"]}。')
    put('f5',12,f'记录编号{ids["f5"]} 正式签收，最终版本v13；回执码：{expected["f5"]}。此前各批归档备忘均为作废版本。')
    put('f6',6,f'易混编号LB-0{offset+222:04}，归档码{code("unicode-neighbor")}。\n正式签收编号{ids["f6"]}，回执码：{expected["f6"]}。')
    put('f7',7,json.dumps({'编号':ids['f7'],'状态':'正式签收','回执码':expected['f7'],'备注':'结构化原始记录'},ensure_ascii=False))
    put('f8',9,f'| 编号 | 状态 | 回执码 |\n|---|---|---|\n| {ids["f8"]} | 正式签收 | {expected["f8"]} |')
    put('f9',10,f'正式签收记录{ids["f9"]}，回执码：{expected["f9"]}。原文大小写必须保留。')
    put('f10',11,f'正式签收单\n编号：{ids["f10"]}\n\n核对备注：北区仪表已完成本单签收，仅描述记录状态，不代表项目启用获批。\n\n回执码：{expected["f10"]}\n单据结束。')
    expected.update(state=f'现行预算{latest}元替代{budget}元，不增加人员；启用{launch}，核验预计{review}且能否提前未知，必须启用前完成；不能确认按期启用，提议未批准。',
                    authority='负责人待定，审批权限归属未说明；不推定未指定、不编造审批等级或外部文件状态。',
                    delivery=f'完整列出10个编号的最终正式码及来源，另给180非空白字符以内交接结论，含现行预算、两个完整日期及原句“{disclaimer}”；全文无编造事实、虚假读取声明或越权批准。')
    task=('完成岚桥设备维保交接。逐行输出下面十个编号的最终正式签收回执码，格式“编号：实际码值（来源定位）”，保留原文大小写；不用作废旧码，未知写“无法确认”，不要猜。'
          +'、'.join(ids.values())+'。另给交接结论：说明现行预算及变更、人员限制、两个日期与核验前置条件、能否按期启用、负责人及审批权限的已知状态；不超过180个非空白字符，包含最早要求保留的固定句。不要把建议当成批准，不推定未提供的外部记录状态。')
    return {'id':'long-context-transfer-lanqiao-v9-'+code('instance')[:8], 'revision':9,
        'title':'陌生材料迁移：岚桥设备维保交接（v9）','protocol':'checkpoint-fork-compaction-v1',
        'generation':{'kind':'transfer-keyed-receipts','private_seed':seed},
        'seed_turns':seeds,'pressure_turns':pressure,'minimum_load_batches':12,
        'probes':[{'id':'recall','tools':'禁止','prompt':'只依据当前可见上下文，不调用工具，不读文件或历史。'+task},
                  {'id':'recovery','tools':'仅允许只读当前分支原始历史','prompt':'现在允许只读核验当前会话原始历史和工作区，不读其他会话、不联网、不写文件或记忆技能。核验并重新完整交付上一轮任务，说明实际查阅来源；没有查阅则明确说明。'+task}],
        'expected':expected,'required_points':{k:[v] for k,v in expected.items()},
        'allowed_grades':['correct','unknown','wrong'],'probe_anchors':quotes,
        'task_groups':{'current_state':['state','authority'],'receipt_handoff':[f'f{i}' for i in range(1,11)],'delivery':['delivery']},
        'conclusion_checks':[],
        'scoring':{'per_item':'全部满足required_points才correct；明确未知/漏答为unknown；错误码、采用作废版本、错误断言为wrong；不得partial。',
            'receipt':'核对原始记录对象、正式/作废状态与最终版本，不能只看码是否出现。工单/编号与码的输出配对由冻结校验器检查。',
            'state':'核对用户正式更新；不能从未知推出未指定，不能推定文件不存在或额外审批等级。',
            'delivery':'全文核对无编造、无越权、来源声明真实；结论只统计独立交接结论正文，最多180非空白字符。',
            'task_success':'13项全correct才完整交付；3个子任务与两阶段非独立样本。',
            'comparison':'版本间以相同材料成对、交错运行；两版独立会话的助手历史仍不同。只作探索性观察。',
            'cost':'分开报告压缩、recall与recovery的实际墙钟和工具调用；未知token/费用/缓存留null。',
            'noise':'报告A_repeat波动；三对材料不支持普遍因果结论。'},
        'pressure_policy':{'send':'必须12批；此版不允许追加负载，需改负载时另建冻结材料。'},
        'target_visibility':'只发送当前seed、负载或探针prompt；不得发送本JSON、私有种子、预期答案或未来问题。'}


def prepare_comparison(root, case_paths, seed=73):
    """Freeze a counterbalanced, interleaved schedule; does not call a model."""
    import random
    from types import SimpleNamespace
    import longrun
    root=Path(root).resolve()
    if root.exists():raise ValueError('Use a new comparison directory.')
    if len(case_paths)!=3:raise ValueError('Exactly three material instances are required.')
    cases=[(Path(p).resolve(),longrun.load(p)) for p in case_paths]
    if len({longrun.digest(c) for _,c in cases})!=3:
        raise ValueError('Use three distinct frozen materials, not three copies of one case.')
    for _,c in cases:
        longrun.validate_prefix(c,c['seed_turns']+c['pressure_turns'])
    rng=random.Random(seed)
    rng.shuffle(cases)
    first_versions=['0.1.0','0.1.1','0.1.0']
    rng.shuffle(first_versions)
    root.mkdir(parents=True)
    jobs=[]
    for pair,((case_path,case),first) in enumerate(zip(cases,first_versions),1):
        for version in (first,'0.1.1' if first=='0.1.0' else '0.1.0'):
            path=root/'runs'/f'pair-{pair}-{version}'/'plan.json'
            args=SimpleNamespace(output=str(path),casefile=str(case_path),model='deepseek-flash',
                provider='deepseek-official',effort='low',timeout=900,load_batches=12,seed=seed+pair,
                dsh_bin='/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh',
                app_version='0.2.2-rc.3',transport='web',history_plugin=True,history_plugin_version=version)
            longrun.create(args)
            state=longrun.load(path)
            jobs.append({'pair':pair,'plugin_version':version,'record':str(path),
                         'case_hash':longrun.digest(case),'config_hash':longrun.digest(state['config'])})
    schedule={'version':1,'case_family':'transfer-lanqiao-v9','seed':seed,
              'order_policy':'Three paired materials, interleaved versions with counterbalanced first position; two old-first, one new-first. Not shared-checkpoint across versions.',
              'runner_files_sha256':runner_hashes(),
              'jobs':jobs,'notice':'No model calls during preparation. Grade each run independently; do not treat anchors, stages or branches as independent samples.'}
    longrun.save(root/'schedule.json',schedule)
    return root/'schedule.json'


def run_comparison(schedule_path):
    import longrun
    import history_plugin
    schedule=longrun.load(schedule_path)
    if schedule.get('runner_files_sha256')!=runner_hashes():
        raise ValueError('Frozen comparison runner changed; prepare a new comparison.')
    jobs=schedule['jobs']
    if len(jobs)!=6:raise ValueError('Comparison requires six frozen runs.')
    # Validate every job before spending model usage on any of them.
    for job in jobs:
        state=longrun.load(job['record'])
        if (state['case_hash']!=job['case_hash'] or longrun.digest(state['case'])!=job['case_hash'] or
                longrun.digest(state['config'])!=job['config_hash'] or
                state['config']['history_plugin']['version']!=job['plugin_version']):
            raise ValueError('Frozen comparison inputs changed.')
        meta=state['config']['history_plugin']
        if history_plugin.hashes(Path(meta['snapshot']))!=meta['sha256']:
            raise ValueError('Frozen comparison plugin changed.')
        if state['status'] not in ('ready','completed') or state['pending']:
            raise ValueError('A run needs investigation; no automatic retry or replacement: '+job['record'])
    for job in jobs:
        path=Path(job['record'])
        state=longrun.load(path)
        if state['status']=='completed':continue
        if state['status']!='ready' or state['pending']:
            raise ValueError('A run needs investigation; no automatic retry or replacement: '+str(path))
        longrun.run(path)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    build=sub.add_parser('build-suite');build.add_argument('--output',required=True)
    prepare=sub.add_parser('prepare');prepare.add_argument('--output',required=True)
    prepare.add_argument('--cases',nargs=3,default=[str(CASE_DIR/'transfer-v9'/f'case-{n}.json') for n in (1,2,3)])
    prepare.add_argument('--seed',type=int,default=73)
    run=sub.add_parser('run');run.add_argument('--schedule',required=True)
    args=parser.parse_args()
    try:
        if args.command=='build-suite':
            root=Path(args.output)
            if root.exists():raise ValueError('Existing material is never overwritten.')
            root.mkdir(parents=True)
            for n in (1,2,3):
                (root/f'case-{n}.json').write_text(json.dumps(build_case(secrets.token_hex(32)),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        elif args.command=='prepare':print(prepare_comparison(args.output,args.cases,args.seed))
        else:run_comparison(args.schedule)
    except (ValueError,OSError) as error:
        parser.exit(1,str(error)+'\n')
