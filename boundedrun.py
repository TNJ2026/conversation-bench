"""Deliver once from bounded source evidence; add --repair for one local revision."""
import argparse
import json
import os
import re
from pathlib import Path
import shutil
import time

import bounded_delivery as contract
import longrun
import bounded_runtime as engine
from webhost_driver import WebHostDriver

ROOT=Path(__file__).resolve().parent
CONTROLLER=ROOT/'plugins/bounded-delivery-controller/index.cjs'
FILES=('boundedrun.py','bounded_delivery.py','plugins/bounded-delivery-controller/index.cjs','webhost_driver.py','bounded_runtime.py','history_plugin.py','dsh_driver.py','longrun.py','longcase.py','checks.py')


def runtime_environment(config,smoke=False):
    """Bridge only the official API key; never persist credentials in records.

    Accept the simple scalar format written by DSH, not arbitrary YAML.
    Complex/ambiguous documents fail closed rather than guessing a secret.
    """
    if smoke or config.get('provider')!='deepseek-official' or os.environ.get('DEEPSEEK_API_KEY'):
        return {}
    home=Path(os.environ.get('DSH_HOME') or Path.home()/'.dsh')
    source=home/'.credentials.yaml'
    if not source.exists():return {}
    if source.stat().st_mode & 0o077:raise ValueError('DSH credentials must be owner-only (chmod 600).')
    lines=source.read_text().splitlines();inside=False;values=[];sections=0
    for line in lines:
        if line and not line[0].isspace() and not line.startswith('#'):
            inside=line.strip()=='refs:'
            if inside:sections+=1
        elif inside:
            match=re.fullmatch(r'  DEEPSEEK_API_KEY: *(.*)',line)
            if match:values.append(match[1])
    if not values:return {}
    if sections!=1 or len(values)!=1:raise ValueError('Ambiguous DSH API key entry.')
    raw=values[0]
    try:
        value=json.loads(raw) if raw.startswith('"') else raw[1:-1].replace("''", "'") if raw.startswith("'") and raw.endswith("'") else raw
        if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_.-]+',value):raise ValueError()
    except ValueError:
        raise ValueError('Unsupported DSH API key scalar; use the launch environment instead.') from None
    return {'DEEPSEEK_API_KEY':value}


def input_data(value):
    if not isinstance(value,dict) or not {'task','summary','originals'}<=set(value) or set(value)-{'task','summary','originals','verbatim_guards'}:
        raise ValueError('Input accepts only task, summary, originals and optional source-backed verbatim_guards; no scoring keys.')
    if not isinstance(value['task'],str) or not value['task'].strip() or len(value['task'])>20000:raise ValueError('Nonempty task at most20000 characters required.')
    if not isinstance(value['summary'],str) or len(value['summary'])>80000:raise ValueError('Summary exceeds allowed size.')
    originals=value['originals']
    if not isinstance(originals,list) or not 1<=len(originals)<=5000:raise ValueError('Original user records required.')
    ids=set()
    for item in originals:
        if not isinstance(item,dict) or set(item)!={'id','text'} or not isinstance(item['id'],str) or not item['id'] or item['id'] in ids or not isinstance(item['text'],str) or len(item['text'])>100000:
            raise ValueError('Originals require unique IDs and exact source text.')
        ids.add(item['id'])
    guards=value.get('verbatim_guards',[])
    if not isinstance(guards,list) or len(guards)>12:raise ValueError('At most12 source-backed guard declarations.')
    for guard in guards:
        if not isinstance(guard,dict) or set(guard)!={'original_id','quote'} or not isinstance(guard['original_id'],str) or guard['original_id'] not in ids or not isinstance(guard['quote'],str) or not guard['quote'].strip():
            raise ValueError('Guard declarations need original_id and exact quote.')
    return value


def outcome(result):
    reason=result.get('finish_reason');ends=[e for e in result.get('events',[]) if e.get('type')=='turn/end']
    if reason not in ('completed','max-tokens') or not isinstance(result.get('answer'),str) or not ends or ends[-1]['data'].get('reason',{}).get('kind')!=reason:
        raise ValueError('Unknown/inconsistent phase termination; preserve attention and do not resend.')
    if any(e.get('type') in ('tool/call','tool/ptc-dispatch') for e in result.get('events',[])):raise ValueError('Bounded phases do not permit tools.')
    return dict(finish=reason,empty=not result['answer'].strip())


def request_usage(home,phase,request,result):
    """Keep raw usage; never sum repeated snapshots or treat missing data as zero."""
    path=home/f'bd-{phase}-usage-1.json'
    if not path.is_file():return dict(complete=False,reason='missing_capture',totals=None)
    data=longrun.load(path)
    if any(data.get(k)!=v for k,v in dict(sessionId=request['sessionId'],phase=phase,request=1,mock=request['mock']).items()):
        raise ValueError('Usage capture request identity changed.')
    chunks=data.get('usage_chunks',[])
    valid=(len(chunks)==1 and isinstance(chunks[0],dict) and
           all(type(chunks[0].get(k)) is int and chunks[0][k]>=0 for k in ('inputTokens','outputTokens')) and
           (data.get('finish') or {}).get('kind') in
           ({'stop','completed'} if result['finish_reason']=='completed' else {result['finish_reason']}))
    return dict(complete=valid,reason=None if valid else 'missing_multiple_or_invalid_usage',raw=data,
                totals=chunks[0] if valid else None)


def execute(value,output,config,smoke=False,scenario='success',with_repair=False):
    value=input_data(value);output=Path(output).resolve()
    if output.exists():raise ValueError('Use a new output directory; no automatic resume/retry.')
    # Let DSH resolve provider authentication; one environment variable is not
    # proof of whether the runtime can authenticate.
    environment=runtime_environment(config,smoke)
    if config.get('workflow_version')!=contract.VERSION or type(config.get('max_paragraph_chars')) is not int or not 1<=config['max_paragraph_chars']<=2000:raise ValueError('Invalid workflow/paragraph limit.')
    if any(type(config.get(k)) is not int or config[k]<1 for k in ('timeout','max_tokens')) or not 800<=config.get('evidence_chars',0)<=12000:raise ValueError('Invalid bounded request/evidence budgets.')
    output.mkdir(parents=True);home=output/'homes/trial';home.mkdir(parents=True)
    shutil.copyfile(CONTROLLER,home/'controller.cjs')
    (home/'controlled.patch.yml').write_text('- insert:\n    - id: bench-bd-controller\n      name: ./controller.cjs\n')
    config={**config,'runtime_patch':dict(path=str(home/'controlled.patch.yml'),ready_marker='BENCH_BOUNDED_CONTROLLER_READY 1')}
    record=dict(protocol=contract.VERSION if with_repair else 'bounded-direct-evidence-v2',arm='candidate' if with_repair else 'baseline',mode='repair' if with_repair else 'direct',repair_enabled=with_repair,status='ready',pending=None,input=value,input_sha256=longrun.digest(value),config=config,
        source_hashes={name:engine.sha(ROOT/name) for name in FILES},runtime_fingerprint=engine.runtime_fingerprint(config),stages={},selection=None,
        semantic_verified=False,task_success=None,request_count=0,usage=None)
    if not with_repair:record['source_hashes']['boundedbaseline.py']=engine.sha(ROOT/'boundedbaseline.py')
    path=output/'run.json';workspace=engine.new_workspace('bounded-delivery-');start=time.monotonic();deadline=start+config['timeout']
    def phase(name,prompt,resume):
        remaining=deadline-time.monotonic()
        if remaining<1:raise ValueError('Whole-task budget exhausted; no next phase sent.')
        record.update(status='running',pending=name);longrun.save(path,record)
        payload=dict(phase=name,initial=not resume,summary=value['summary'],prompt=prompt,originals=value['originals'],smoke=smoke,smoke_scenario=scenario,
            maxTokens=config['max_tokens'],provider=config['provider'],model=config['model'],effort=config['effort'],evidence=record.get('evidence_packet'))
        longrun.save(home/'bd-current-input.json',payload);longrun.save(home/f'bd-{name}-input.json',payload)
        now=time.monotonic();result=WebHostDriver({**config,'timeout':remaining},environment=environment).perform(home,workspace,None,prompt,resume,output/'raw'/f'{name}.log')
        record['stages'][name]=dict(prompt=prompt,result=result,elapsed_seconds=time.monotonic()-now);longrun.save(path,record)
        if name=='bootstrap':
            proof=longrun.load(home/'bd-bootstrap-proof.json');complete=longrun.load(home/'bd-bootstrap-completed.json')
            if result.get('answer')!='BOUNDED_BOOTSTRAP_ONLY_NO_PROVIDER_CALL' or result.get('finish_reason')!='completed' or complete!={'sessionId':proof['sessionId'],'provider_calls':0,'bootstrap_only':True}:
                raise ValueError('Zero-provider bootstrap proof failed.')
        else:
            outcome(result)
            captures=list(home.glob(f'bd-{name}-request-*.json'))
            record['request_count']=len(list(home.glob('bd-*-request-*.json')))
            if len(captures)!=1:raise ValueError('Each bounded phase must have exactly one captured model request.')
            request=longrun.load(captures[0]);proof=longrun.load(home/'bd-bootstrap-proof.json')
            if request.get('phase')!=name or request.get('mock')!=smoke or request.get('tools')!=[] or request.get('sessionId')!=proof['sessionId'] or request.get('provider')!=config['provider'] or request.get('model')!=config['model'] or request.get('reasoningEffort')!=config['effort'] or request.get('maxTokens')!=config['max_tokens']:
                raise ValueError('Bounded phase configuration/request changed.')
            users=[m for m in request.get('messages',[]) if m.get('role')=='user' and m.get('source',{}).get('kind')!='runtime-context']
            if not users or '\n'.join(b.get('text','') for b in users[-1].get('content',[]) if b.get('type')=='text')!=prompt:
                raise ValueError('Actual prompt differs from recorded bounded phase.')
            record['stages'][name]['usage']=request_usage(home,name,request,result)
            usages=[s['usage'] for s in record['stages'].values() if 'usage' in s]
            complete=len(usages)==record['request_count'] and all(u['complete'] for u in usages)
            keys=('inputTokens','outputTokens','cacheReadTokens','cacheWriteTokens','totalTokens')
            record['usage']=dict(complete=complete,requests=len(usages),totals={k:sum(u['totals'][k] for u in usages) if all(k in u['totals'] for u in usages) else None for k in keys} if complete else None)
        record['pending']=None;longrun.save(path,record);return result
    try:
        phase('bootstrap','Initialize bounded delivery; no provider calls.',False)
        proof=longrun.load(home/'bd-bootstrap-proof.json');originals=proof['originals']
        if [(s['id'],s['text']) for s in originals]!=[(s['id'],s['text']) for s in value['originals']]:raise ValueError('Admitted history differs from input.')
        packet=contract.evidence_packet(originals,max_chars=config['evidence_chars']);record['evidence_packet']=packet
        seqbyid={s['id']:s['seq'] for s in originals}
        guards=contract.validate_guards([dict(seq=seqbyid[g['original_id']],quote=g['quote']) for g in value.get('verbatim_guards',[])],originals,packet['packet']);record['guards']=guards
        draft=phase('draft',contract.draft_prompt(value['task'],value['summary'],packet),True)
        if draft['finish_reason']!='completed' or not draft['answer'].strip():
            record['selection']=dict(answer=draft['answer'],accepted=False,selected_from='incomplete_draft',errors=['no_completed_draft'],semantic_verified=False,task_success=None)
        elif not with_repair:
            record['selection']=dict(answer=draft['answer'],accepted=False,selected_from='direct_draft',errors=[],semantic_verified=False,task_success=None)
        else:
            edit=contract.editable_paragraph(draft['answer']);record['editable_span']=edit
            repair=phase('repair',contract.repair_prompt(value['task'],packet,edit,guards,config['max_paragraph_chars']),True)
            record['selection']=contract.apply_repair(draft['answer'],repair['answer'],repair['finish_reason'],packet,edit,guards,config['max_paragraph_chars'])
        record.update(status='completed',pending=None,elapsed_seconds=time.monotonic()-start)
    except Exception as error:
        record.update(status='attention',problem=str(error),elapsed_seconds=time.monotonic()-start);longrun.save(path,record);raise
    longrun.save(path,record)
    (output/'draft.md').write_text(record['stages']['draft']['result']['answer'],encoding='utf-8')
    (output/'answer.md').write_text(record['selection']['answer'],encoding='utf-8')
    return record


def smoke(output,config):
    output=Path(output).resolve();output.mkdir(exist_ok=False)
    value=dict(task='逐行保留回执F-1，最后给180个非空白字符内交接结论，区分已知与未知。',summary='F-1：cafe；不能确认按期。',
        originals=[dict(id='decision',text='核验能否提前未知；临时建议未批准。')],verbatim_guards=[dict(original_id='decision',quote='能否提前未知')])
    previous=os.environ.get('DEEPSEEK_API_KEY');os.environ['DEEPSEEK_API_KEY']='bounded-smoke-not-a-real-credential';rows=[]
    try:
        direct=execute(value,output/'direct',config,True)
        assert list(direct['stages'])==['bootstrap','draft'] and direct['request_count']==1
        rows.append(dict(scenario='direct',accepted=False,model_requests=direct['request_count'],selection=direct['selection']['selected_from']))
        for scenario in ('success','repair-max','repair-invalid'):
            r=execute(value,output/scenario,config,True,scenario,with_repair=True);s=r['selection'];draft=r['stages']['draft']['result']['answer']
            assert s['accepted']==(scenario=='success')
            if scenario=='success':assert '能否提前未知' in s['answer'] and s['answer'].split('\n\n')[0]==draft.split('\n\n')[0]
            else:assert s['answer']==draft
            rows.append(dict(scenario=scenario,accepted=s['accepted'],model_requests=2,selection=s['selected_from']))
    finally:
        if previous is None:os.environ.pop('DEEPSEEK_API_KEY',None)
        else:os.environ['DEEPSEEK_API_KEY']=previous
    report=dict(status='passed',fixture_materials=1,native_routes=rows,model_generation_calls=0,mock=True,source_hashes={name:engine.sha(ROOT/name) for name in FILES},
        notice='One fixture, three mechanism routes. Not real-model efficacy or benchmark scores.')
    longrun.save(output/'smoke-report.json',report);return output/'smoke-report.json'


def main(argv=None,with_repair=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=('smoke','run'));parser.add_argument('--output',required=True);parser.add_argument('--input',type=Path)
    parser.add_argument('--dsh-bin',default=engine.DSH_BIN);parser.add_argument('--provider',default='deepseek-official');parser.add_argument('--model',default='deepseek-flash');parser.add_argument('--effort',default='low')
    parser.add_argument('--app-version',default='0.2.2-rc.3');parser.add_argument('--max-tokens',type=int,default=4096);parser.add_argument('--timeout',type=int,default=300);parser.add_argument('--evidence-chars',type=int,default=3200);parser.add_argument('--max-paragraph-chars',type=int,default=180)
    parser.add_argument('--repair',action='store_true',help='Explicitly add one local paragraph repair; default is one direct delivery request.')
    args=parser.parse_args(argv)
    if with_repair is False and args.repair:parser.error('The baseline alias only supports direct delivery; use boundedrun.py run --repair.')
    repair_enabled=args.repair if with_repair is None else with_repair
    config=dict(dsh_bin=args.dsh_bin,app_version=args.app_version,provider=args.provider,model=args.model,effort=args.effort,max_tokens=args.max_tokens,timeout=args.timeout,evidence_chars=args.evidence_chars,max_paragraph_chars=args.max_paragraph_chars,workflow_version=contract.VERSION)
    try:
        if args.max_tokens<1 or args.timeout<1:raise ValueError('Positive request/time budgets required.')
        if args.command=='smoke':print(smoke(args.output,config))
        else:
            if args.input is None:raise ValueError('--input is required for a single run.')
            r=execute(longrun.load(args.input),args.output,config,with_repair=repair_enabled);print(contract.dump(dict(status=r['status'],mode=r['mode'],selection=r['selection']['selected_from'],patch_accepted=r['selection']['accepted'],errors=r['selection']['errors'],requests=r['request_count'],usage=r['usage'],elapsed_seconds=r['elapsed_seconds'],answer_file=str(Path(args.output).resolve()/'answer.md'),semantic_verified=False,task_success=None)))
    except (ValueError,RuntimeError,OSError) as error:parser.exit(1,str(error)+'\n')


if __name__=='__main__':main()
