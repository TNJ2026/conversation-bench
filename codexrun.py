#!/usr/bin/env python3
"""Batch Codex CLI conversations; explicit model arms, raw evidence, no automatic grading."""
import argparse
import contextlib
import sys
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time

import checks
import review_v3
import study

ROOT = Path(__file__).resolve().parent
METHOD = 'codex-cli'
TITLE = 'Codex CLI 批量测试'
WORKSPACE_PREFIX = 'codex-bench-'
EXECUTION_COLUMNS = (
    ('elapsed_seconds', '生成耗时（秒）'),
    ('input_tokens', '输入 token'),
    ('cached_input_tokens', '缓存输入 token'),
    ('uncached_input_tokens', '未缓存输入 token'),
    ('output_tokens', '输出 token'),
    ('total_tokens', '总 token'),
)
LIMITATIONS = [
    'CLI测试，不代表桌面UI体验；中断用例不支持。',
    '独立新会话和工作区属于逻辑分离，不是保密读取隔离；workspace-write不禁止读取所有其他路径。',
    '忽略用户config.toml，但保留当前账号认证；全局指令、服务端策略与环境仍可能影响结果。',
    '请求模型名和推理强度已记录；CLI事件未确认实际后端模型时不宣称已独立核实。',
    '程序完成及静态检查不等于任务成功；语义评分需独立评审。',
]


def positive(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError('必须是有限正数')
    return number


def case_execution(record):
    """Sum observed CLI turns. Each invocation requests exactly one turn."""
    turns = record.get('turns', []) if record else []
    durations = [turn.get('metrics', {}).get('elapsed') for turn in turns]
    elapsed = sum(durations) if durations and all(
        type(value) in (int, float) and math.isfinite(value) and value >= 0 for value in durations
    ) else None
    payloads = [turn.get('usage') for turn in turns]
    usage = [payload[0] for payload in payloads if isinstance(payload, list) and len(payload) == 1
             and isinstance(payload[0], dict)]

    def tokens(key):
        values = [event.get(key) for event in usage]
        if values and len(values) == len(turns) and all(type(value) is int and value >= 0 for value in values):
            return sum(values)
        return None

    input_tokens = tokens('input_tokens')
    cached = tokens('cached_input_tokens')
    output_tokens = tokens('output_tokens')
    if cached is not None and (input_tokens is None or any(
        event['cached_input_tokens'] > event['input_tokens'] for event in usage
    )):
        cached = None
    return {
        'elapsed_seconds': elapsed,
        'input_tokens': input_tokens,
        'cached_input_tokens': cached,
        'uncached_input_tokens': input_tokens-cached if input_tokens is not None and cached is not None else None,
        'output_tokens': output_tokens,
        'total_tokens': input_tokens+output_tokens if input_tokens is not None and output_tokens is not None else None,
    }


def execution_cells(execution):
    cells = []
    for key, _ in EXECUTION_COLUMNS:
        value = execution.get(key)
        cells.append('—' if value is None else f'{value:.2f}' if key == 'elapsed_seconds' else f'{value:,}')
    return cells


def arm_specs(values, effort):
    arms = []
    for value in values:
        model, sep, override = value.rpartition('@')
        model, selected = (model, override) if sep else (value, effort)
        if not model.strip() or model.startswith('-') or selected not in ('minimal','low','medium','high','xhigh','max','ultra'):
            raise ValueError('模型格式为模型ID或模型ID@推理强度；强度需由目标模型支持')
        arm = dict(id=f'A{len(arms)+1:02}', model=model, effort=selected)
        if any((a['model'],a['effort']) == (model,selected) for a in arms):
            raise ValueError('模型与推理强度组合重复')
        arms.append(arm)
    return arms


def prepare(args, catalog=None):
    arms = arm_specs(args.model, args.effort)
    if catalog is None:
        catalog = study.load_catalog(args.suite, ROOT)
    requested = args.cases.split(',') if args.cases else None
    if requested and (len(set(requested)) != len(requested) or set(requested)-{c['id'] for c in catalog}):
        raise ValueError('案例ID重复或不在所选套件内')
    cases = [c for c in catalog if requested is None or c['id'] in requested]
    if args.repeat < 1: raise ValueError('repeat必须为正整数')
    destination = Path(args.output).expanduser().resolve()
    binary = shutil.which(args.codex)
    if not binary: raise ValueError('找不到Codex CLI：'+args.codex)
    version = subprocess.run([binary,'--version'],capture_output=True,text=True,check=True,timeout=15).stdout.strip()
    jobs = []
    for repeat in range(1,args.repeat+1):
        for index,case in enumerate(cases):
            ordered = study.product_order(arms,index,repeat)
            for arm in ordered:
                jobs.append(dict(id=f'J{len(jobs)+1:04}',arm=arm,case=case,case_hash=study.digest(case),repeat=repeat))
    plan = dict(version=1,runner='codex-cli',created=study.stamp(),suite=args.suite,
                binary=str(Path(binary).resolve()),cli_version=version,timeout=args.timeout,
                arms=arms,jobs=jobs,limitations=LIMITATIONS)
    destination.mkdir(parents=True,exist_ok=False)
    study.save(destination/'plan.json',plan)
    study.save(destination/'plan-binding.json',{'sha256':study.digest(plan)})
    print(f'已准备 {len(cases)} 例 × {len(arms)} 组 × {args.repeat} 轮 = {len(jobs)} 次会话；尚未调用模型。')
    print(destination/'plan.json')
    return destination


def command(plan, arm, thread=None):
    # Parent flags select sandbox for exec/resume. Child flags explicitly select output/model/config.
    config = ['--ignore-user-config','--ignore-rules','--skip-git-repo-check','--json',
              '--model',arm['model'],'-c','model_reasoning_effort='+json.dumps(arm['effort']),
              '-c','approval_policy="never"']
    base = [plan['binary'],'exec','--sandbox','workspace-write']
    if thread:
        return base + ['resume'] + config + [thread,'-']
    return base + config + ['-']


def parse_events(path):
    events = []; malformed = 0
    for line in path.read_text(encoding='utf-8',errors='replace').splitlines():
        if not line.strip(): continue
        try:
            event = json.loads(line)
            if not isinstance(event,dict): raise ValueError('not object')
            events.append(event)
        except ValueError: malformed += 1
    starts = [e.get('thread_id') for e in events if e.get('type')=='thread.started']
    thread = starts[-1] if starts else None
    answers = [e['item'].get('text','') for e in events if e.get('type')=='item.completed'
               and isinstance(e.get('item'),dict) and e['item'].get('type')=='agent_message']
    failed = any(e.get('type') in ('turn.failed','error') for e in events)
    completed = any(e.get('type')=='turn.completed' for e in events)
    usage = [e.get('usage') for e in events if e.get('type')=='turn.completed']
    evidence = [dict(kind='tool',text=json.dumps(e,ensure_ascii=False)) for e in events
                if e.get('type') in ('item.started','item.completed') and isinstance(e.get('item'),dict)
                and e['item'].get('type') in ('command_execution','file_change','mcp_tool_call','web_search')]
    return dict(thread=thread,answer=answers[-1] if answers else '',failed=failed,completed=completed,
                malformed_lines=malformed,usage=usage,execution_evidence=evidence)


def child_env():
    return None  # inherit the caller's environment unchanged


def invoke(cmd, prompt, workspace, raw, timeout, parse=None, env=None):
    raw.mkdir(parents=True,exist_ok=False)
    (raw/'prompt.txt').write_text(prompt,encoding='utf-8')
    study.save(raw/'command.json',cmd)
    started = time.monotonic(); timed_out = False
    with (raw/'events.jsonl').open('wb') as out, (raw/'stderr.log').open('wb') as err:
        process = subprocess.Popen(cmd,cwd=workspace,stdin=subprocess.PIPE,stdout=out,stderr=err,start_new_session=True,env=env)
        try:
            process.communicate(prompt.encode(),timeout=timeout)
        except (subprocess.TimeoutExpired,KeyboardInterrupt) as error:
            with contextlib.suppress(ProcessLookupError): os.killpg(process.pid,signal.SIGTERM)
            try: process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError): os.killpg(process.pid,signal.SIGKILL)
                process.communicate()
            if isinstance(error,KeyboardInterrupt): raise
            timed_out = True
    result = (parse or parse_events)(raw/'events.jsonl')
    result.update(returncode=process.returncode,timeout=timed_out,elapsed=time.monotonic()-started)
    return result


def snapshot(workspace, text_files=(), source=False):
    files = {}; artifacts = {}; limits = []
    # Bounded, no symlink traversal. Record omissions rather than silently treating snapshots as complete.
    for base,dirs,names in os.walk(workspace,followlinks=False):
        if source:
            excluded = {'.git', '.next', 'node_modules'}
            if Path(base).relative_to(workspace).parts[:1] != ('candidate',):
                excluded.add('vendor')
            dirs[:] = [d for d in dirs if d not in excluded]
        for d in dirs:
            p = Path(base)/d
            # The link itself is a workspace change; its target is never read.
            if p.is_symlink(): files[str(p.relative_to(workspace))] = study.link_entry(p)
            # A new empty directory has no file to hash, so record the directory itself.
            elif not any(p.iterdir()): files[study.dir_entry(p, workspace)] = study.EMPTY_DIR
        dirs[:] = [d for d in dirs if not (Path(base)/d).is_symlink()]
        for name in sorted(names):
            p = Path(base)/name; relative = str(p.relative_to(workspace))
            if p.is_symlink():
                files[relative] = study.link_entry(p); continue
            if not p.is_file(): continue
            if len(files)>=200 or p.stat().st_size>2_000_000:
                limits.append(relative+': snapshot limit'); continue
            data = p.read_bytes(); files[relative]=hashlib.sha256(data).hexdigest()
            if (source and p.suffix.lower() in {'.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx', '.css', '.svg'}) or relative in text_files or p.suffix.lower() in ('.txt','.md','.html','.csv','.json'):
                try: artifacts[relative]=data.decode('utf-8')
                except UnicodeDecodeError: limits.append(relative+': not UTF-8')
    return files,artifacts,limits


def turn_checks(case, spec, answer, earlier, artifacts, files, initial, limits):
    result = checks.check(answer,spec.get('checks',[]),earlier)
    def add(label,passed,detail): result.append(dict(check=label,pass_=passed,detail=detail))
    result.extend(study.fixture_checks(case,len(earlier)+1,files,initial,limits))
    if spec.get('read_only'):
        previous = earlier[-1]['files'] if earlier else initial
        add('本轮未改变文件',None if limits else files==previous,'只比较轮末文件；工具日志需独立审阅')
    if spec.get('sections'):
        page=artifacts.get('report.html','')
        add('指定section齐全',all(checks.section(page,x) is not None for x in spec['sections']),'静态结构，不验证预览')
        linked=checks.linked_resources(page)
        add('单文件无外部资源',bool(page) and not linked,'静态资源扫描：'+str(linked)+'；非浏览器验证')
    if spec.get('keeps_sections') and earlier:
        page=artifacts.get('report.html',''); original=earlier[0]['artifacts'].get('report.html','')
        for name in spec['keeps_sections']:
            before,after=checks.section(original,name),checks.section(page,name)
            add(name+'保持不变',bool(before and before==after),'与首轮section原始HTML比较')
    previous = earlier[-1]['files'] if earlier else initial
    result.extend(study.artifact_checks(spec,files,previous,artifacts,limits))
    for row in result:
        if 'pass_' in row: row['pass']=row.pop('pass_')
    return result


def execute(folder, backend=None):
    """Run a frozen plan. backend supplies METHOD, WORKSPACE_PREFIX, command, parse_events and child_env."""
    backend = backend or sys.modules[__name__]
    folder=Path(folder).resolve(); plan=study.load(folder/'plan.json')
    webbench = plan.get('suite') == 'webbench'
    if study.digest(plan)!=study.load(folder/'plan-binding.json')['sha256']:
        raise ValueError('计划已修改；请为新配置创建新计划，避免混合结果')
    with (folder/'.run.lock').open('a') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise ValueError('该计划正在运行，拒绝并发重复请求')
        # Do not silently change runtime midway through a comparison.
        version=subprocess.run([plan['binary'],'--version'],capture_output=True,text=True,check=True,timeout=15).stdout.strip()
        if version!=plan['cli_version']: raise ValueError('CLI版本已改变，请重新创建计划')
        for job in plan['jobs']:
            rp=folder/'records'/(job['id']+'.json')
            if rp.exists():
                record=study.load(rp)
                if record['status']=='running':
                    record.update(status='transport-unknown',error='上次运行中断；不重发，需新计划复测')
                    study.save(rp,record)
                continue
            case=job['case']; arm=job['arm']
            record=dict(job=job['id'],product=arm['id'],config=arm,case=case,case_hash=job['case_hash'],repeat=job['repeat'],
                        status='running',created=study.stamp(),turns=[],protocol=dict(method=backend.METHOD,isolated=False,unexposed=None),
                        valid=None,initial_files={},workspace=None,thread_id=None)
            if case['category']=='interrupt':
                record.update(status='unsupported',error='CLI批量运行器未实现真实运行中指令干预；不通过杀进程模拟')
                study.save(rp,record); print(job['id'],case['id'],'unsupported',flush=True); continue
            # Outside repository and report directory, with a separate directory per model/case/repeat.
            workspace=Path(tempfile.mkdtemp(prefix=backend.WORKSPACE_PREFIX)).resolve()
            record['workspace']=str(workspace)
            study.save(rp,record)
            try:
                def inside(p):
                    if p.is_absolute() and workspace not in p.resolve().parents: raise ValueError('非法材料路径')
                study.write_fixtures(case, workspace, inside)
                record['initial_files']=snapshot(workspace, source=case.get('snapshot_source', False))[0];study.save(rp,record)
                for number,spec in enumerate(case['turns'],1):
                    raw=folder/'raw'/job['id']/f'turn-{number}'
                    result=invoke(backend.command(plan,arm,record['thread_id']),spec['prompt'],workspace,raw,plan['timeout'],
                                  parse=backend.parse_events,env=backend.child_env())
                    thread=result['thread'] or record['thread_id']
                    thread_error = None
                    if result['thread'] and record['thread_id'] and result['thread']!=record['thread_id']:
                        thread_error = 'resume返回不同会话ID，不继续后续轮次'
                    if thread is not None and (not isinstance(thread,str) or not thread.strip() or thread.startswith('-')):
                        thread_error = 'CLI返回无效会话ID'
                    if not thread_error: record['thread_id']=thread
                    files,artifacts,limits=snapshot(workspace, case.get('snapshot_artifacts', ()), source=case.get('snapshot_source', False))
                    turn=dict(number=number,prompt=spec['prompt'],answer=result['answer'],files=files,artifacts=artifacts,
                              snapshot_limits=limits,execution_evidence=result['execution_evidence'],usage=result['usage'],
                              notes='快照限制：'+str(limits) if limits else '',
                              metrics={'elapsed':result['elapsed']},interruption_observed=False,
                              transport={k:result[k] for k in ('returncode','timeout','completed','failed','malformed_lines')})
                    if result.get('model'): turn['reported_model']=result['model']
                    turn['checks']=turn_checks(case,spec,result['answer'],record['turns'],artifacts,files,record['initial_files'],limits)
                    record['turns'].append(turn)
                    (raw/'answer.txt').write_text(result['answer'],encoding='utf-8')
                    good=(result['returncode']==0 and not result['timeout'] and result['completed'] and not result['failed']
                          and result['malformed_lines']==0 and bool(result['answer'].strip()) and bool(thread) and not thread_error)
                    if not good:
                        record.update(status='transport-unknown' if result['timeout'] else 'failed',error=thread_error or '本轮未取得完整可靠响应；原始输出已保留，不自动重试')
                    study.save(rp,record)
                    if not webbench or (good and number < len(case['turns'])):
                        print(job['id'],arm['model'],case['id'],f'{number}/{len(case["turns"])}',record['status'],flush=True)
                    if not good: break
                if record['status']=='running': record['status']='completed'
            except KeyboardInterrupt:
                record.update(status='transport-unknown',error='操作员中断；原始事件可能含部分响应，不自动重试')
                study.save(rp,record);raise
            except Exception as error:
                record.update(status='failed',error=f'{type(error).__name__}: {error}')
            record['finished']=study.stamp();study.save(rp,record)
            if webbench:
                execution = case_execution(record)
                measurements = '，'.join(f'{label} {value}' for (_, label), value in
                                         zip(EXECUTION_COLUMNS, execution_cells(execution)))
                print(job['id'], arm['model'], case['id'], record['status'], measurements, flush=True)
    report(folder, backend.TITLE)
    return not any(r['status'] in ('failed','transport-unknown') for r in records_for(folder)[1])


def records_for(folder):
    plan=study.load(folder/'plan.json')
    records=[study.load(folder/'records'/(j['id']+'.json')) for j in plan['jobs'] if (folder/'records'/(j['id']+'.json')).exists()]
    return plan,records


def report(folder, title=TITLE):
    folder=Path(folder).resolve();plan,records=records_for(folder)
    webbench = plan.get('suite') == 'webbench'
    lines=['# '+title,'',*['- '+x for x in plan['limitations']],'',
           '完成仅表示已收到全部轮次响应；语义未评分。未执行、失败和不支持的样本均保留。','',
           '| 记录 | 模型 / 推理强度 | 用例 | 状态 | 轮次 | 静态通过/失败/待定 |','|---|---|---|---|---|---|']
    if webbench:
        lines[-2] += ' ' + ' | '.join(label for _, label in EXECUTION_COLUMNS) + ' |'
        lines[-1] += '---:|' * len(EXECUTION_COLUMNS)
    by_id={r['job']:r for r in records}
    for job in plan['jobs']:
        r=by_id.get(job['id']);arm=job['arm']
        tests=[c for t in r['turns'] for c in t['checks']] if r else []
        counts='/'.join(str(sum(c['pass'] is v for c in tests)) for v in (True,False,None))
        lines.append(f'| {job["id"]} | {arm["model"]} / {arm["effort"]} | {job["case"]["id"]} | {r["status"] if r else "pending"} | {len(r["turns"]) if r else 0}/{len(job["case"]["turns"])} | {counts} |')
        if webbench:
            lines[-1] += ' ' + ' | '.join(execution_cells(case_execution(r))) + ' |'
    (folder/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    reviewed=review_v3.rows(folder,records)
    study.save(folder/'review-results.json',reviewed)
    if reviewed:
        with (folder/'report.md').open('a',encoding='utf-8') as output:
            output.write('\n## 独立评审回收\n\n逐轮分数、复核状态和依据见 [review-results.json](review-results.json)。无效评分不采纳，分歧不自动平均。\n')
            output.write(review_v3.totals_markdown(review_v3.totals(folder,records)))
    print(folder/'report.md')


def export(folder):
    folder=Path(folder).resolve();plan,records=records_for(folder)
    groups={}
    for r in records:
        if r['status'] in ('running','unsupported'): continue
        key=(r['case_hash'],r['repeat'])
        groups.setdefault(key,{})[r['product']]=r
    groups=[g for g in groups.values() if set(g)=={a['id'] for a in plan['arms']}]
    if not groups: raise ValueError('没有所有配置均已结案的可评审组；不支持的中断用例不导出')
    print(review_v3.export(folder,groups))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('prepare',help='创建冻结计划，不调用模型')
    p.add_argument('--model',action='append',required=True,help='可重复；模型ID或模型ID@推理强度')
    p.add_argument('--effort',default='high',choices=['minimal','low','medium','high','xhigh','max','ultra'])
    p.add_argument('--suite',default=study.DEFAULT_SUITE,choices=study.SUITES)
    p.add_argument('--cases');p.add_argument('--repeat',type=int,default=1)
    p.add_argument('--timeout',type=positive,default=600,help='每轮秒数')
    p.add_argument('--codex',default='codex');p.add_argument('--output',required=True)
    for name in ('run','report','export'):
        sub.add_parser(name).add_argument('--study',required=True)
    args=parser.parse_args()
    try:
        if args.action=='prepare': prepare(args)
        elif args.action=='run':
            if not execute(args.study): raise SystemExit(1)
        elif args.action=='report': report(args.study)
        else: export(args.study)
    except KeyboardInterrupt:
        report(args.study);print('已停止；未自动重发未确认请求。',file=__import__('sys').stderr);raise SystemExit(130)
    except (ValueError,OSError,subprocess.SubprocessError) as error: parser.exit(1,str(error)+'\n')


if __name__=='__main__': main()
