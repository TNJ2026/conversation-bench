#!/usr/bin/env python3
"""Human-operated desktop comparison; never gives the target future prompts."""
import argparse
import datetime as dt
import hashlib
import html
import json
from pathlib import Path
import random
import re
import uuid
import checks as text_checks

ROOT = Path(__file__).resolve().parent
DEFAULT_PRODUCTS = ('dsh', 'chatgpt')

def product_list(value):
    products = value.split(',') if isinstance(value, str) else list(value)
    products = [p.strip().lower() for p in products]
    if not products or any(not p for p in products):
        raise argparse.ArgumentTypeError('应用列表不能为空，使用逗号分隔。')
    if len(products) != len(set(products)):
        raise argparse.ArgumentTypeError('应用不能重复。')
    unknown = set(products) - set(text_checks.PRODUCTS)
    if unknown:
        raise argparse.ArgumentTypeError('未知应用：' + ', '.join(sorted(unknown)) +
                                         '；可选：' + ', '.join(text_checks.PRODUCTS))
    return products

def plan_products(plan):
    # Older v2 plans recorded the products only in their jobs.
    return plan['products'] if 'products' in plan else list(dict.fromkeys(j['product'] for j in plan['jobs']))

def product_order(products, index, repeat):
    if len(products) == 2:
        # Preserve the original two-product order and job numbering.
        return products if (index + repeat) % 2 else products[::-1]
    step = index + repeat - 1
    offset = step % len(products)
    order = products[offset:] + products[:offset]
    return order if (step // len(products)) % 2 == 0 else order[::-1]

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    temporary.replace(path)

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def stamp():
    return dt.datetime.now().astimezone().isoformat()

def snapshot(workspace):
    return {str(p.relative_to(workspace)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in workspace.rglob('*') if p.is_file() and not p.is_symlink()}

def eligible(record):
    p = record['protocol']
    return p['method']=='desktop' and p['isolated'] and p['unexposed'] and record.get('valid') is True

def create(args):
    products = product_list(getattr(args, 'products', DEFAULT_PRODUCTS))
    catalog = load(ROOT/'cases-v2.json')
    chosen = [c for c in catalog if not args.cases or c['id'] in args.cases.split(',')]
    if args.cases and set(args.cases.split(',')) != {c['id'] for c in chosen}:
        raise SystemExit('存在未知案例 ID。运行 python3 study.py list 查看。')
    if args.repeat < 1:
        raise SystemExit('repeat 必须至少为1。')
    rng = random.Random(args.seed)
    rng.shuffle(chosen)
    jobs = []
    for repeat in range(1,args.repeat+1):
        for i,c in enumerate(chosen):
            order = product_order(products, i, repeat)
            for product in order:
                jobs.append({'id':f'J{len(jobs)+1:03}', 'case':c, 'case_hash':digest(c), 'product':product, 'repeat':repeat})
    plan = {'version':2,'created':stamp(),'mode':args.mode,'seed':args.seed,'products':products,'jobs':jobs}
    destination = Path(args.output).resolve() if args.output else ROOT/'studies'/('study-'+uuid.uuid4().hex[:8])/'plan.json'
    if destination.exists():
        raise SystemExit('计划已存在，不覆盖。')
    save(destination,plan)
    print(f'{destination}\n{len(chosen)} 案例 × {len(products)} 应用 × {args.repeat} 次 = {len(jobs)} 次会话。')
    print('应用：' + ', '.join(products))
    print('下一步：python3 study.py next --plan '+str(destination))

def record_path(plan_path, job):
    return plan_path.parent/'records'/(job['id']+'.json')

def display(record):
    index=len(record['turns'])
    if index==len(record['case']['turns']):
        print('全部轮次已记录。运行 finish 完成人工验收；失败也可以 finish。')
        return
    turn=record['case']['turns'][index]
    print(f'当前第 {index+1} 轮；仅把下面提示词交给目标应用：\n\n{turn["prompt"]}')
    if turn.get('capture_before'):
        print('\n操作员：发送前保留 report.html 副本。submit 会自动保存每轮 HTML/Markdown/CSV 快照。')
    if turn.get('interrupt_with'):
        print('\n操作员：'+turn['operator']+'\n在目标仍运行时发送：\n'+turn['interrupt_with'])
    print('\n回答保存到 UTF-8 文本后，用 submit 记录。工具日志写 notes，不混进待检查的正文。')

def next_job(args):
    path=Path(args.plan).resolve(); plan=load(path)
    for job in plan['jobs']:
        rp=record_path(path,job)
        r=load(rp) if rp.exists() else None
        if r and r['status'] in ('completed','failed','invalid'):
            continue
        print(f'{job["id"]} | {job["product"]} | {job["case"]["title"]} | repeat {job["repeat"]}')
        if r:
            print('记录：',rp); display(r)
        else:
            print('请使用新会话。执行 begin --plan <计划> --job '+job['id']+' --model <实际模型> ...')
        return
    print('计划内会话均已结案。运行 report 生成报告。')

def begin(args):
    path=Path(args.plan).resolve(); plan=load(path)
    job=next((j for j in plan['jobs'] if j['id']==args.job),None)
    if not job:
        raise SystemExit('未知 job。')
    rp=record_path(path,job)
    if rp.exists():
        raise SystemExit('已开始，使用 next 或 submit 继续；不会覆盖。')
    workspace=ROOT.parent/'conversation-bench-workspaces'/path.parent.name/job['id']
    workspace.mkdir(parents=True, exist_ok=False)
    for name,content in job['case']['fixtures'].items():
        (workspace/name).write_text(content,encoding='utf-8')
    r={'version':2,'job':job['id'],'case':job['case'],'case_hash':job['case_hash'],
       'product':job['product'],'repeat':job['repeat'],'mode':plan['mode'],'created':stamp(),
       'config':{'model':args.model,'app_version':args.app_version,'permissions':args.permissions,'plugins':args.plugins,'memory':args.memory},
       'protocol':{'method':args.method,'isolated':args.isolated,'unexposed':args.unexposed},
       'workspace':str(workspace),'initial_files':snapshot(workspace),'turns':[],'status':'running','valid':None}
    save(rp,r)
    print('记录：',rp,'\n目标工作区：',workspace,'\n只给目标应用这个工作区，不要开放测试项目目录。')
    display(r)

def submit(args):
    path=Path(args.record).resolve(); r=load(path)
    if r['status']!='running':
        raise SystemExit('记录已结案，不可再提交。')
    index=len(r['turns'])
    if index>=len(r['case']['turns']):
        raise SystemExit('所有轮次已录入，请 finish。')
    answer=Path(args.answer).read_text(encoding='utf-8')
    if not answer.strip():
        raise SystemExit('回答为空；未完成的失败可以直接 finish --outcome failed。')
    turn=r['case']['turns'][index]
    checks=text_checks.check(answer,turn.get('checks',[]),r['turns'])
    workspace=Path(r['workspace'])
    artifacts={}
    for filename in ('report.html','report.md','timeline.csv','meeting.txt'):
        p=workspace/filename
        if p.is_file() and not p.is_symlink():
            artifacts[filename]=p.read_text(encoding='utf-8')
    current_files=snapshot(workspace)
    if 'meeting.txt' in r['initial_files']:
        checks.append({'check':'原始材料未变','pass':current_files.get('meeting.txt')==r['initial_files']['meeting.txt'],'detail':'与创建工作区时的SHA256比较'})
    if r['case']['category']=='review' and index>0:
        first=r['turns'][0]['artifacts'].get('report.html','')
        current=artifacts.get('report.html','')
        for section in ('overview','decisions'):
            pattern=rf'<section\b[^>]*\bid=[\"\']{section}[\"\'][^>]*>.*?</section>'
            before=re.search(pattern,first,re.S|re.I); after=re.search(pattern,current,re.S|re.I)
            checks.append({'check':section+'保持不变','pass':bool(before and after and before.group()==after.group()),'detail':'比较section原始HTML，缺失section判失败；不证明视觉显示正常'})
        if index==2:
            checks.append({'check':'讨论轮未改变文件','pass':current_files==r['turns'][-1]['files'],'detail':'轮末哈希不能发现改后恢复；工具日志仍需人工审阅'})
    item={'prompt':turn['prompt'],'answer':answer,'recorded':stamp(),'checks':checks,
          'metrics':{k:getattr(args,k) for k in ('elapsed','first_feedback','active_seconds','corrections','actions','interrupt_delay')},
          'interruption_observed':args.interruption_observed,'notes':Path(args.notes).read_text(encoding='utf-8') if args.notes else '',
          'files':snapshot(workspace),'artifacts':artifacts}
    r['turns'].append(item); save(path,r)
    print('已保存第',index+1,'轮。检查：',json.dumps(checks,ensure_ascii=False)); display(r)

def form(r):
    return {'valid':None,'invalid_reason':'','acceptance':[{'criterion':x,'pass':None,'evidence':''} for x in r['case']['acceptance']],
            'clarity':None,'cooperation':None,'summary':'说明具体事件；未知留null。'}

def finish(args):
    path=Path(args.record).resolve(); r=load(path)
    if r['status']!='running':
        raise SystemExit('记录已结案，不覆盖；复测创建新计划。')
    if not args.scores:
        target=path.with_name(path.stem+'-scores.json')
        if not target.exists(): save(target,form(r))
        print('填写评分文件后再次运行 finish --scores：',target)
        return
    scores=load(args.scores)
    if type(scores.get('valid')) is not bool:
        raise SystemExit('valid 必须明确为 true 或 false；无效测试需填写原因。')
    if not scores['valid'] and not scores.get('invalid_reason','').strip():
        raise SystemExit('请记录测试无效原因。')
    expected=r['case']['acceptance']; actual=scores.get('acceptance',[])
    if [x.get('criterion') for x in actual]!=expected:
        raise SystemExit('验收条目与本次快照不一致。')
    for x in actual:
        if x.get('pass') is not None and type(x['pass']) is not bool:
            raise SystemExit('验收 pass 只能 true / false / null。')
        if x.get('pass') is not None and not x.get('evidence','').strip():
            raise SystemExit('每个已评分项需填写 evidence。')
    for k in ('clarity','cooperation'):
        value=scores.get(k)
        if value is not None and (type(value) is not int or not 1<=value<=5):
            raise SystemExit('主观分只能为1–5或null。')
    if args.outcome=='completed' and len(r['turns'])!=len(r['case']['turns']):
        raise SystemExit('轮次未完成；可使用 --outcome failed 记录失败。')
    if r['case']['category']=='interrupt' and scores['valid'] and not any(t['interruption_observed'] for t in r['turns']):
        raise SystemExit('没有观察到运行中干预，不能标为有效。')
    r.update({'valid':scores['valid'],'scores':scores,'status':args.outcome if scores['valid'] else 'invalid','finished':stamp()})
    save(path,r); print('已结案：',r['status'])

def collect(path):
    plan=load(path); records=[]
    for job in plan['jobs']:
        rp=record_path(path,job)
        if rp.exists(): records.append(load(rp))
    return plan,records

def pair_records(records, products=None):
    """Complete comparison groups; the historical function name is retained."""
    products = list(dict.fromkeys(products if products is not None else (r['product'] for r in records)))
    required = set(products)
    if len(required) < 2:
        return []
    groups={}
    for r in records:
        if r['product'] in required and eligible(r) and r['status'] in ('completed','failed'):
            group = groups.setdefault((r['case_hash'],r['repeat'],r['mode']),{})
            group.setdefault(r['product'],[]).append(r)
    # Ambiguous duplicate samples must not silently replace each other.
    return [{p:g[p][0] for p in products} for g in groups.values()
            if set(g)==required and all(len(samples)==1 for samples in g.values())]

def report(args):
    path=Path(args.plan).resolve(); plan,records=collect(path)
    e=lambda x:html.escape(str(x))
    products=plan_products(plan)
    groups=pair_records(records, products)
    chunks=['<!doctype html><meta charset="utf-8"><title>会话体验研究</title><style>body{font:16px system-ui;max-width:1200px;margin:40px auto;padding:20px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:10px}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>',
            '<h1>会话体验研究</h1>',f'<p>计划 {len(plan["jobs"])} 次会话；已建档 {len(records)} 次；有效完整对照 {len(groups)} 组。</p>',
            '<p>有效性来自操作员声明，并非软件验证。控制模式也不自动保证模型相同。失败会话保留；未测值不是零。自动检查不是独立样本。不合并自测、无效或协议未确认记录。</p>']
    chunks.append('<p>本计划应用：'+e(', '.join(products))+'。完整对照要求同一案例、重复编号、模式下，所选应用全部有效结案；缺少任何一方不作为完整对照。</p>')
    if len(products)==1:
        chunks.append('<p>单应用计划只记录测试结果，不形成跨应用对照或匿名对照导出。</p>')
    for title,items in [('有效正式测试',[r for r in records if eligible(r)]),('自测、无效或待确认',[r for r in records if not eligible(r)])]:
        chunks.append('<h2>'+title+'</h2><table><tr><th>案例 / 应用</th><th>状态</th><th>模型</th><th>自动检查</th><th>验收</th><th>清晰 / 合作</th></tr>')
        for r in items:
            checks=[c for t in r['turns'] for c in t['checks'] if c['pass'] is not None]
            scores=r.get('scores',{}); accepted=[x['pass'] for x in scores.get('acceptance',[]) if x['pass'] is not None]
            vals=[r['case']['title']+' / '+r['product'],r['status'],r['config']['model'],f'{sum(x["pass"] for x in checks)}/{len(checks)}' if checks else '不适用',f'{sum(accepted)}/{len(accepted)} 已评项' if accepted else '未评',str(scores.get('clarity'))+' / '+str(scores.get('cooperation'))]
            chunks.append('<tr>'+''.join('<td>'+e(v)+'</td>' for v in vals)+'</tr>')
        chunks.append('</table>')
    chunks.append('<h2>完整对照样本</h2>')
    for g in groups:
        first=next(iter(g.values()))
        members=[e(product+' '+r['job']+'（模型：'+r['config']['model']+'）') for product,r in g.items()]
        chunks.append('<p>'+e(first['case']['title'])+'：'+' ↔ '.join(members)+'</p>')
    chunks.append('<h2>各轮证据及观测指标</h2>')
    for r in records:
        chunks.append('<details><summary>'+e(r['job']+' '+r['product']+' '+r['case']['title'])+'</summary><pre>'+e(json.dumps(r,ensure_ascii=False,indent=2))+'</pre></details>')
    out=path.parent/'report.html'; out.write_text('\n'.join(chunks)+'\n',encoding='utf-8'); print(out)

def blind(args):
    path=Path(args.plan).resolve(); plan,records=collect(path)
    groups=pair_records(records, plan_products(plan))
    if not groups: raise SystemExit('没有可导出的有效完整对照。单应用、自测或缺少任一应用的组不进入匿名对照评审。')
    destination=path.parent/('blind-'+uuid.uuid4().hex[:8]); destination.mkdir()
    rng=random.SystemRandom(); mapping={}; entries=[]
    for i,g in enumerate(groups,1):
        ordered=list(g.values()); rng.shuffle(ordered)
        for index,r in enumerate(ordered):
            letter=chr(ord('A')+index)
            label=f'P{i:03}-{letter}'; mapping[label]=r['job']
            entries.append({'id':label,'case':r['case']['title'],'turns':[{'prompt':t['prompt'],'answer':t['answer']} for t in r['turns']]})
    save(destination/'review.json',{'notice':'只评文本，不评桌面操作。配置、来源和产品标签已去除，但回答自身可能暴露身份，分享前检查。','samples':entries})
    save(destination/'scores.json',{'samples':[{'id':x['id'],'factuality':None,'instruction_following':None,'usefulness':None,'evidence':''} for x in entries]})
    save(path.parent/(destination.name+'-KEY-DO-NOT-SHARE.json'),mapping)
    print('只把此目录交给评审者：',destination,'\n身份映射独立保存在计划目录，勿分享。各项1–5分，并注明原文依据。')

def nonnegative(raw):
    value=float(raw)
    if value<0 or not __import__('math').isfinite(value): raise argparse.ArgumentTypeError('必须为非负有限数')
    return value

def main():
    p=argparse.ArgumentParser(description=__doc__); sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('list')
    c=sub.add_parser('create'); c.add_argument('--cases'); c.add_argument('--products',type=product_list,default=DEFAULT_PRODUCTS,help='逗号分隔的应用：dsh,chatgpt,hermes；默认 dsh,chatgpt，可只选一个'); c.add_argument('--repeat',type=int,default=1); c.add_argument('--seed',type=int,default=42); c.add_argument('--mode',choices=['default','controlled'],default='default'); c.add_argument('--output')
    for name in ('next','report','blind'):
        sub.add_parser(name).add_argument('--plan',required=True)
    b=sub.add_parser('begin'); b.add_argument('--plan',required=True); b.add_argument('--job',required=True); b.add_argument('--model',required=True)
    for field in ('app-version','permissions','plugins','memory'): b.add_argument('--'+field,default='未记录')
    b.add_argument('--method',choices=['desktop','selftest'],default='selftest'); b.add_argument('--isolated',action='store_true'); b.add_argument('--unexposed',action='store_true')
    s=sub.add_parser('submit'); s.add_argument('--record',required=True); s.add_argument('--answer',required=True); s.add_argument('--notes')
    for field in ('elapsed','first-feedback','active-seconds','interrupt-delay'): s.add_argument('--'+field,type=nonnegative)
    for field in ('corrections','actions'): s.add_argument('--'+field,type=int)
    s.add_argument('--interruption-observed',action='store_true')
    f=sub.add_parser('finish'); f.add_argument('--record',required=True); f.add_argument('--scores'); f.add_argument('--outcome',choices=['completed','failed'],default='completed')
    args=p.parse_args()
    if args.command=='list':
        for c in load(ROOT/'cases-v2.json'): print(c['id']+'\t'+c['title'])
    else:
        for key in ('corrections','actions'):
            if getattr(args,key,None) is not None and getattr(args,key)<0: p.error(key+'不能为负数')
        {'create':create,'next':next_job,'begin':begin,'submit':submit,'finish':finish,'report':report,'blind':blind}[args.command](args)

if __name__=='__main__': main()
