#!/usr/bin/env python3
"""Run frozen conversation cases through the installed DSH SDK profile."""
import argparse
import fcntl
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid

import codexrun as common
import study
from dsh_driver import DSH_BIN, runtime_environment
from dsh_driver import DshDriver

LIMITATIONS = [
    'DSH SDK profile测试，不代表桌面UI；中断题不支持。',
    '独立home、会话和工作区仅作逻辑分离，不限制读取其他路径；全局技能和环境可能影响结果。',
    '使用运行时默认工具、系统提示和生成上限；与Codex不同，比较的是产品配置而非纯模型。',
    '凭据仅通过现有认证环境传递，不写入计划；请求模型与推理档位不等于独立确认后端。',
    '每轮关闭运行时并恢复原会话；外部进程状态不保证恢复。完成不等于语义正确。',
]


def prepare(args):
    binary = str(Path(args.dsh).resolve())
    version = subprocess.run([binary, '--version'], capture_output=True, text=True, check=True, timeout=20).stdout.strip()
    suite = getattr(args, 'suite', study.DEFAULT_SUITE)
    cases = study.load_catalog(suite, common.ROOT)
    if args.cases:
        wanted = args.cases.split(',')
        if set(wanted)-{c['id'] for c in cases}: raise ValueError('未知用例')
        cases = [c for c in cases if c['id'] in wanted]
    arm = dict(id='A01',provider=args.provider,model=args.model,effort=args.effort)
    plan = dict(version=1,runner='dsh-sdk',created=study.stamp(),suite=suite,binary=binary,
                cli_version=version,timeout=args.timeout,arms=[arm],limitations=LIMITATIONS,
                jobs=[dict(id=f'J{i:04}',arm=arm,case=c,case_hash=study.digest(c),repeat=1) for i,c in enumerate(cases,1)])
    if getattr(args, 'profile_patch', None):
        plan['profile_patch'] = Path(args.profile_patch).read_text()
    folder=Path(args.output).resolve();folder.mkdir(parents=True,exist_ok=False)
    study.save(folder/'plan.json',plan);study.save(folder/'plan-binding.json',dict(sha256=study.digest(plan)))
    print(folder)


def report(folder):
    common.report(folder)
    p=Path(folder)/'report.md'
    p.write_text(p.read_text().replace('# Codex CLI 批量测试','# DSH SDK 批量测试',1))


def execute(folder):
    folder=Path(folder).resolve();plan=study.load(folder/'plan.json')
    if plan['runner']!='dsh-sdk' or study.digest(plan)!=study.load(folder/'plan-binding.json')['sha256']:
        raise ValueError('计划类型错误或已修改')
    with (folder/'.run.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        version=subprocess.run([plan['binary'],'--version'],capture_output=True,text=True,check=True,timeout=20).stdout.strip()
        if version!=plan['cli_version']: raise ValueError('运行时版本已改变')
        patch_path = folder/'runtime-overlay.yml'
        if 'profile_patch' in plan:
            # Rebuild only from the bound plan; changes to the input file cannot affect a run.
            patch_path.write_text(plan['profile_patch'])
        for job in plan['jobs']:
            rp=folder/'records'/(job['id']+'.json')
            if rp.exists():
                old=study.load(rp)
                if old['status']=='running':
                    old.update(status='transport-unknown',error='上次执行未确认结束；不重发');study.save(rp,old)
                continue
            case=job['case'];arm=job['arm']
            r=dict(job=job['id'],product=arm['id'],config=arm,case=case,case_hash=job['case_hash'],repeat=1,
                   status='running',created=study.stamp(),turns=[],protocol=dict(method='dsh-sdk',isolated=False,unexposed=None),
                   valid=None,initial_files={},workspace=None,thread_id='bench-'+uuid.uuid4().hex)
            if case['category']=='interrupt':
                r.update(status='unsupported',error='不通过杀进程模拟运行中指令干预');study.save(rp,r);continue
            workspace=Path(tempfile.mkdtemp(prefix='dsh-bench-')).resolve();home=Path(tempfile.mkdtemp(prefix='dsh-bench-home-')).resolve()
            r.update(workspace=str(workspace),runtime_home=str(home));study.save(rp,r)
            config=dict(dsh_bin=plan['binary'],timeout=plan['timeout'],**arm)
            if 'profile_patch' in plan:
                config['profile_patch'] = str(patch_path)
            saved={k:os.environ.get(k) for k in runtime_environment(config)}
            os.environ.update(runtime_environment(config))
            try:
                def inside(p):
                    if workspace not in p.resolve().parents: raise ValueError('材料路径越界')
                study.write_fixtures(case, workspace, inside)
                r['initial_files']=common.snapshot(workspace)[0];study.save(rp,r)
                for number,spec in enumerate(case['turns'],1):
                    raw=folder/'raw'/job['id']/f'turn-{number}';raw.mkdir(parents=True,exist_ok=False)
                    (raw/'prompt.txt').write_text(spec['prompt']);study.save(raw/'request.json',dict(config=config,session=r['thread_id'],resume=number>1))
                    started=time.monotonic()
                    result=DshDriver(config).perform(home,workspace,r['thread_id'],spec['prompt'],number>1,raw/'events.jsonl')
                    study.save(raw/'result.json',result);(raw/'answer.txt').write_text(result['answer'])
                    files,artifacts,limits=common.snapshot(workspace, case.get('snapshot_artifacts', ()))
                    turn=dict(number=number,prompt=spec['prompt'],answer=result['answer'],files=files,artifacts=artifacts,
                              snapshot_limits=limits,execution_evidence=[dict(kind='tool',text=__import__('json').dumps(e,ensure_ascii=False)) for e in result['events'] if 'tool' in e.get('type','')],
                              usage=[e for e in result['events'] if 'usage' in e.get('type','')],notes='',metrics=dict(elapsed=time.monotonic()-started),
                              interruption_observed=False,transport=dict(finish_reason=result['finish_reason'],server=result['server']))
                    turn['checks']=common.turn_checks(case,spec,result['answer'],r['turns'],artifacts,files,r['initial_files'],limits)
                    r['turns'].append(turn)
                    if result['finish_reason']!='completed' or not result['answer'].strip():
                        r.update(status='failed',error='未取得正常完整回答，不重试')
                    study.save(rp,r);print(job['id'],case['id'],number,r['status'],flush=True)
                    if r['status']!='running': break
                if r['status']=='running': r['status']='completed'
            except BaseException as e:
                r.update(status='transport-unknown',error=f'{type(e).__name__}: {e}')
                study.save(rp,r)
                # Stop the batch on transport/config errors instead of repeating a shared failure.
                raise
            finally:
                for k,v in saved.items():
                    if v is None: os.environ.pop(k,None)
                    else: os.environ[k]=v
                r['finished']=study.stamp();study.save(rp,r)
    report(folder)


def main():
    p=argparse.ArgumentParser(description=__doc__);s=p.add_subparsers(dest='action',required=True)
    a=s.add_parser('prepare');a.add_argument('--output',required=True);a.add_argument('--model',required=True)
    a.add_argument('--provider',default='deepseek-official');a.add_argument('--effort',default='high')
    a.add_argument('--dsh',default=DSH_BIN);a.add_argument('--timeout',type=common.positive,default=600);a.add_argument('--cases')
    a.add_argument('--suite',choices=study.SUITES,default=study.DEFAULT_SUITE)
    a.add_argument('--profile-patch',help='Non-secret provider overlay, frozen into the plan; use apiKeyEnv for credentials')
    for name in ('run','report','export'): s.add_parser(name).add_argument('--study',required=True)
    args=p.parse_args()
    if args.action=='prepare': prepare(args)
    elif args.action=='run':
        try: execute(args.study)
        finally: report(args.study)
    elif args.action=='report': report(args.study)
    else: common.export(args.study)

if __name__=='__main__': main()
