"""Persistent automatic runner for the shared-checkpoint compaction experiment."""
import argparse
from contextlib import contextmanager
import hashlib
import html
import json
from pathlib import Path
import random
import shutil
import time
import uuid

import longcase
import checks as text_checks
from dsh_driver import DriverError, DshDriver, text_content

BRANCHES = ('A', 'A_repeat', 'B')
GRADES = ('correct', 'partial', 'unknown', 'wrong')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    temp.replace(path)


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


@contextmanager
def locked(path):
    lock = path.with_suffix('.lock')
    try:
        handle = lock.open('x')
    except FileExistsError:
        raise ValueError('Runner lock exists. Verify the previous process has stopped before removing it.') from None
    try:
        with handle:
            handle.write(str(__import__('os').getpid()))
        yield
    finally:
        lock.unlink()


def files(folder):
    result = {}
    for p in sorted(folder.rglob('*')):
        if p.is_symlink():
            result[str(p.relative_to(folder))] = {'symlink':str(p.readlink())}
        elif p.is_file():
            result[str(p.relative_to(folder))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return result


def create(args):
    path = Path(args.output).resolve()
    if path.parent.exists():
        raise ValueError('Use a new output directory; existing runs are never overwritten.')
    if not args.model.strip() or not args.provider.strip() or args.load_batches < 1:
        raise ValueError('Model, provider and a positive load-batch count are required.')
    case = load(longcase.CASE)
    root = path.parent
    root.mkdir(parents=True)
    identity = uuid.uuid4().hex
    # Keep task effects outside operator records, scoring keys, and case snapshots.
    workspace = Path(__file__).resolve().parent.parent/'conversation-bench-workspaces'/('long-'+identity)
    workspace.mkdir(parents=True, exist_ok=False)
    order = list(BRANCHES)
    random.Random(args.seed).shuffle(order)
    pressure = case['pressure_turns'][:args.load_batches]
    if args.load_batches > len(pressure):
        pressure += longcase.batches(args.load_batches-len(pressure), first=len(pressure)+1)
    state = {'version':1, 'id':identity, 'method':'dsh-sdk', 'case':case, 'case_hash':digest(case),
             'config':{'dsh_bin':args.dsh_bin, 'provider':args.provider, 'model':args.model,
                       'effort':args.effort, 'timeout':args.timeout, 'profile':'sdk',
                       'app_version':getattr(args,'app_version','unverified')},
             'workspace':str(workspace), 'initial_files':files(workspace),
             'prefix':case['seed_turns']+pressure, 'branch_order':order, 'results':{},
             'seed_sequences':{}, 'checkpoint':None, 'pending':None, 'status':'ready', 'problems':[]}
    save(path, state)
    print(path)


def action(state):
    for turn in state['prefix']:
        key = 'prefix/'+turn['id']
        if key not in state['results']:
            return key, turn['prompt']
    if state['checkpoint'] is None:
        return 'checkpoint', None
    if 'B/compact' not in state['results']:
        return 'B/compact', '/compact'
    for branch in state['branch_order']:
        for probe in state['case']['probes']:
            key = branch+'/'+probe['id']
            if key not in state['results']:
                return key, probe['prompt']
    return None, None


def extend(path, count):
    with locked(path):
        state = load(path)
        if count < 1 or state['checkpoint'] is not None or state['pending'] or state['status'] in ('completed','invalid','attention'):
            raise ValueError('Append positive load only before checkpointing a run with no uncertain action.')
        current = len(state['prefix'])-len(state['case']['seed_turns'])
        state['prefix'] += longcase.batches(count, first=current+1)
        save(path, state)


def checkpoint(path, state):
    source = path.parent/'homes'/'prefix'
    if not source.is_dir():
        raise ValueError('No stopped runtime home is available to clone.')
    manifest = files(source)
    if not manifest:
        raise ValueError('Runtime home is empty; persisted history was not established.')
    for branch in BRANCHES:
        destination = path.parent/'homes'/branch
        if destination.exists():
            if files(destination) != manifest:
                raise ValueError('An existing branch differs from the checkpoint; refusing to reuse it.')
            continue
        temporary = destination.with_name(branch+'.copying')
        if temporary.exists():
            raise ValueError('Incomplete checkpoint copy exists; inspect it before recovery.')
        shutil.copytree(source, temporary, symlinks=True)
        if files(temporary) != manifest:
            raise ValueError('Checkpoint copy verification failed.')
        temporary.rename(destination)
    prefix = [state['results']['prefix/'+t['id']] for t in state['prefix']]
    state['checkpoint'] = {'home_manifest_sha256':digest(manifest), 'home_manifest':manifest,
                           'history_sha256':digest([r['events'] for r in prefix]),
                           'history_hash_method':'Exact captured prefix event envelopes; byte-identical persisted homes establish the shared checkpoint, not an inferred request reconstruction.',
                           'seed_sequences':dict(state['seed_sequences'])}
    save(path, state)


def compact_proof(events, seeds):
    """Require a summary and linked model-history replacement covering all seed messages."""
    for event in events:
        data = event.get('data', {})
        if event.get('type') != 'compaction/summary' or not isinstance(data.get('summary'), str) or not data['summary'].strip():
            continue
        covered = data.get('shadowedSeqs', [])
        if not set(seeds.values()).issubset(covered):
            continue
        for replacement in events:
            op = replacement.get('surfaceOp')
            if (replacement.get('type') == 'user/message' and isinstance(op, dict) and op.get('op') == 'replace'
                    and event.get('seq') in replacement.get('sourceEventSeqs', [])
                    and all(isinstance(op.get(k), int) for k in ('startSeq','endSeq'))
                    and all(op['startSeq'] <= seq <= op['endSeq'] for seq in seeds.values())):
                return {'summary_seq':event['seq'], 'replacement_seq':replacement['seq'],
                        'covered_seed_sequences':dict(seeds), 'summary':data['summary']}
    raise ValueError('No actual history replacement covers all three seed turns; compaction is unconfirmed.')


def validate_result(state, key, prompt, result):
    if result.get('finish_reason') != 'completed':
        raise ValueError('Target action did not complete: '+str(result.get('finish_reason')))
    if not isinstance(result.get('events'), list) or not isinstance(result.get('answer'), str):
        raise ValueError('Target response lacks answer text or event evidence.')
    server = result.get('server')
    if state.get('server') and server != state['server']:
        raise ValueError('DSH runtime identity/version changed during the run.')
    state['server'] = server
    events = result['events']
    if key != 'B/compact' and any(e.get('type', '').startswith('compaction/') for e in events):
        raise ValueError('Unexpected automatic compaction; the uncompacted control or probe is no longer equivalent.')
    if key.startswith('prefix/seed-'):
        matches = [e['seq'] for e in events if e.get('type') == 'user/message' and text_content(e) == prompt]
        if len(matches) != 1:
            raise ValueError('Cannot locate the admitted seed message in durable events.')
        state['seed_sequences'][key.split('/')[1]] = matches[0]
    if key == 'B/compact':
        if len(state['seed_sequences']) != len(state['case']['seed_turns']):
            raise ValueError('Seed sequence evidence is incomplete.')
        result['compaction_proof'] = compact_proof(events, state['seed_sequences'])
    if key.endswith('/recall') and any(e.get('type') in ('tool/call','tool/ptc-dispatch') for e in events):
        raise ValueError('Closed-book recall invoked tools; its closed-book protocol is invalid.')
    if files(Path(state['workspace'])) != state['initial_files']:
        raise ValueError('The target changed workspace files; shared-workspace branches would be contaminated.')


def run(path, max_actions=None, driver=None):
    with locked(path):
        state = load(path)
        if digest(state['case']) != state['case_hash']:
            raise ValueError('The frozen case snapshot changed; start a new plan.')
        if state['pending']:
            raise ValueError('Previous target action has an uncertain outcome; inspect raw logs. Automatic resend is forbidden.')
        if state['status'] in ('invalid','attention','completed'):
            raise ValueError('This run is closed or needs investigation; it cannot be automatically continued.')
        driver = driver or DshDriver(state['config'])
        done = 0
        while True:
            key, prompt = action(state)
            if key is None:
                state['status'] = 'completed'; save(path, state)
                print('All branches completed; semantic grading is still required.')
                return
            if max_actions is not None and done >= max_actions:
                state['status'] = 'ready'; save(path, state)
                print('Stopped at an action boundary; safe to resume.')
                return
            if key == 'checkpoint':
                checkpoint(path, state)
                continue
            branch = key.split('/')[0]
            home = path.parent/'homes'/branch
            resume = branch != 'prefix' or any(k.startswith('prefix/') for k in state['results'])
            wire = path.parent/'raw'/(key.replace('/','-')+'.jsonl')
            state['pending'] = {'action':key, 'wire_log':str(wire)}
            state['status'] = 'running'; save(path, state)
            print('Running '+key, flush=True)
            started = time.monotonic()
            try:
                result = driver.perform(home, Path(state['workspace']), state['id'], prompt, resume, wire)
            except (Exception, KeyboardInterrupt):
                # The target may have committed work. Never guess that a retry is safe.
                state['status'] = 'attention'; save(path, state)
                raise
            result['elapsed_seconds'] = time.monotonic()-started
            state['results'][key] = result
            state['pending'] = None
            try:
                validate_result(state, key, prompt, result)
            except ValueError as error:
                state['status'] = 'invalid'; state['problems'].append(str(error)); save(path, state)
                raise
            save(path, state)
            done += 1


def answer_manifest(state):
    return digest({k:digest(v) for k,v in state['results'].items()})


def grade(path, score_path=None):
    state = load(path)
    if state['status'] != 'completed':
        raise ValueError('Only a completed, protocol-checked run can receive final grades.')
    template = {'run_id':state['id'], 'case_hash':state['case_hash'], 'answers_sha256':answer_manifest(state),
                'protocol':{key:{'pass':None,'evidence':''} for key in ('unexposed','no_external_writes_or_learning','equivalent_configuration')},
                'conclusions':{b:{'text':None,'evidence':''} for b in BRANCHES},
                'rubric':state['case']['scoring'], 'required_points':state['case']['required_points'], 'grades':{}}
    for branch in BRANCHES:
        template['grades'][branch] = {p['id']:{a:{'grade':None,'evidence':'','omitted':False,'retrieved':False,'sources':[]}
                                              for a in state['case']['expected']} for p in state['case']['probes']}
    if score_path is None:
        target = path.parent/'scores.json'
        if not target.exists():
            save(target, template)
        print(target)
        return
    scores = load(score_path)
    if not isinstance(scores, dict):
        raise ValueError('Score sheet must be a JSON object.')
    for key in ('run_id','case_hash','answers_sha256'):
        if scores.get(key) != template[key]:
            raise ValueError('Score sheet belongs to a different run or answer snapshot.')
    if not isinstance(scores.get('protocol'), dict) or set(scores['protocol']) != set(template['protocol']):
        raise ValueError('Protocol review is required; workspace snapshots cannot prove absence of external side effects.')
    for check in scores['protocol'].values():
        if not isinstance(check, dict) or type(check.get('pass')) is not bool or not isinstance(check.get('evidence'),str) or len(''.join(check['evidence'].split())) < 6:
            raise ValueError('Every protocol review needs an explicit verdict and concrete evidence.')
    if not isinstance(scores.get('conclusions'),dict) or set(scores['conclusions']) != set(BRANCHES):
        raise ValueError('Identify each recovery conclusion, or explain why it cannot be identified.')
    conclusion_checks = {}
    for branch, fragment in scores['conclusions'].items():
        if not isinstance(fragment,dict) or not isinstance(fragment.get('evidence'),str) or len(''.join(fragment['evidence'].split())) < 6:
            raise ValueError('Every conclusion selection needs concrete evidence.')
        text = fragment.get('text')
        if text is None:
            conclusion_checks[branch] = [{'check':'最终结论范围','pass':None,'detail':fragment['evidence']}]
        elif not isinstance(text,str) or not text.strip() or text not in state['results'][branch+'/recovery']['answer']:
            raise ValueError('Selected conclusion must be an exact, non-empty span of the actual recovery answer.')
        else:
            conclusion_checks[branch] = text_checks.check(text,state['case'].get('conclusion_checks',[]),[])
    metrics = {}
    if not isinstance(scores.get('grades'), dict) or set(scores['grades']) != set(BRANCHES):
        raise ValueError('All three branches must be graded.')
    for branch in BRANCHES:
        metrics[branch] = {}
        if not isinstance(scores['grades'][branch], dict) or set(scores['grades'][branch]) != {'recall','recovery'}:
            raise ValueError('Both probe stages must be graded.')
        for stage, anchors in scores['grades'][branch].items():
            if not isinstance(anchors, dict) or set(anchors) != set(state['case']['expected']):
                raise ValueError('Every anchor must be assessed.')
            counts = dict.fromkeys(GRADES, 0)
            omitted, retrieved = 0, 0
            result = state['results'][branch+'/'+stage]
            tools = [e for e in result['events'] if e.get('type') in ('tool/call','tool/ptc-dispatch')]
            for anchor, mark in anchors.items():
                if not isinstance(mark, dict):
                    raise ValueError('Each anchor grade must be an object, not a bare score or null.')
                value = mark.get('grade')
                if value not in GRADES or not isinstance(mark.get('evidence'), str) or len(''.join(mark['evidence'].split())) < 6:
                    raise ValueError('Every grade needs a valid category and concrete evidence (at least 6 non-whitespace characters).')
                if type(mark.get('omitted')) is not bool or type(mark.get('retrieved')) is not bool:
                    raise ValueError('Omitted and retrieved must be booleans.')
                if mark['omitted'] and value != 'unknown':
                    raise ValueError('Omission must be unknown, not a wrong assertion.')
                if anchor in ('verbatim','nonce'):
                    if value == 'partial':
                        raise ValueError('Exact-text anchors do not permit partial credit.')
                    if value == 'correct' and state['case']['expected'][anchor] not in result['answer']:
                        raise ValueError('An exact-text pass contradicts the actual answer.')
                if mark['retrieved'] and (stage != 'recovery' or not tools or not isinstance(mark.get('sources'), list)
                                          or not mark['sources'] or not all(isinstance(s,str) and s.strip() for s in mark['sources'])):
                    raise ValueError('Claimed retrieval needs recorded tools and concrete source locations in the recovery stage.')
                counts[value] += 1; omitted += mark['omitted']; retrieved += mark['retrieved']
            metrics[branch][stage] = dict(counts, retention=counts['correct']+0.5*counts['partial'],
                                           errors=counts['wrong'], omitted=omitted, retrieved=retrieved)
    save(path.parent/'scores-reviewed.json', scores)
    state['protocol_valid'] = all(c['pass'] for c in scores['protocol'].values())
    state['conclusion_checks'] = conclusion_checks
    state['metrics'] = metrics; state['scores_sha256'] = digest(scores); save(path, state)
    print('Grades validated and saved. Run report to view the comparison.')


def report(path):
    state = load(path)
    output = {'id':state['id'], 'method':state['method'], 'status':state['status'], 'config':state['config'],
              'case_hash':state['case_hash'], 'server':state.get('server'), 'problems':state['problems'],
              'checkpoint':state['checkpoint'], 'metrics':state.get('metrics'), 'protocol_valid':state.get('protocol_valid'),
              'compaction_proof':state['results'].get('B/compact',{}).get('compaction_proof'),
              'elapsed_seconds':{b:sum(r['elapsed_seconds'] for k,r in state['results'].items() if k.startswith(b+'/')) for b in ('prefix',*BRANCHES)},
              'tokens':None,
              'conclusion_checks':state.get('conclusion_checks'),
              'notice':'SDK-profile experiment, not a desktop-UI score. A single triplet does not establish a causal effect.'}
    rows = []
    metrics = state.get('metrics')
    if metrics:
        output['differences'] = {}
        for stage in ('recall','recovery'):
            a, repeat, b = [metrics[branch][stage] for branch in BRANCHES]
            delta, noise = b['retention']-a['retention'], repeat['retention']-a['retention']
            output['differences'][stage] = {'B_minus_A':delta, 'A_repeat_minus_A':noise,
                                           'outside_repeat_variation':abs(delta)>abs(noise) if state.get('protocol_valid') else None,
                                           'B_errors_minus_A':b['errors']-a['errors']}
        for branch in BRANCHES:
            for stage in ('recall','recovery'):
                m = metrics[branch][stage]
                rows.append([branch,stage,m['retention'],m['errors'],m['omitted'],m['retrieved']])
    save(path.parent/'report.json', output)
    e = lambda v:html.escape(str(v))
    table = '<table border="1"><tr>'+''.join('<th>'+e(h)+'</th>' for h in ('Branch','Stage','Retention / 10','Wrong','Omitted','Retrieved'))+'</tr>'
    table += ''.join('<tr>'+''.join('<td>'+e(v)+'</td>' for v in row)+'</tr>' for row in rows)+'</table>'
    page = '<!doctype html><meta charset="utf-8"><title>Compaction comparison</title><h1>Compaction comparison</h1>'
    page += '<p>'+e(output['notice'])+'</p>'+table+'<pre>'+e(json.dumps(output,ensure_ascii=False,indent=2))+'</pre>'
    target = path.parent/'report.html'; target.write_text(page, encoding='utf-8'); print(target)


def positive(raw):
    value = int(raw)
    if value < 1:
        raise argparse.ArgumentTypeError('Must be a positive integer.')
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(prog='study.py long', description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    c = sub.add_parser('create'); c.add_argument('--output',required=True); c.add_argument('--model',required=True)
    c.add_argument('--provider',default='deepseek-official'); c.add_argument('--effort'); c.add_argument('--dsh-bin',default='dsh')
    c.add_argument('--app-version',default='unverified',help='Actual DSH app/CLI version; serverInfo.version is only the SDK protocol version')
    c.add_argument('--load-batches',type=positive,default=12); c.add_argument('--seed',type=int,default=42)
    c.add_argument('--timeout',type=positive,default=900)
    for command in ('run','next','extend','grade','report'):
        p = sub.add_parser(command); p.add_argument('--record',required=True)
        if command == 'run': p.add_argument('--max-actions',type=positive)
        if command == 'extend': p.add_argument('--batches',type=positive,required=True)
        if command == 'grade': p.add_argument('--scores')
    args = parser.parse_args(argv)
    try:
        if args.command == 'create':
            create(args); return
        path = Path(args.record).resolve()
        if args.command == 'run': run(path, args.max_actions)
        elif args.command == 'extend': extend(path,args.batches)
        elif args.command == 'grade':
            with locked(path): grade(path,args.scores)
        elif args.command == 'report': report(path)
        else:
            state = load(path); key,prompt = action(state)
            print(json.dumps({'status':state['status'],'next_action':key,'pending':state['pending'],'prompt':prompt},ensure_ascii=False,indent=2))
    except (ValueError,DriverError,OSError) as error:
        parser.exit(1, str(error)+'\n')


if __name__ == '__main__':
    main()
