"""Persistent automatic runner for the shared-checkpoint compaction experiment."""
import argparse
from contextlib import contextmanager
import hashlib
import html
import json
from pathlib import Path
import random
import re
import shutil
import time
import uuid

import longcase
import history_plugin
import checks as text_checks
from dsh_driver import DriverError, DshDriver, text_content
from webhost_driver import WebHostDriver

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


def allowed_grades(case):
    # Frozen v6 runs predate the explicit field, but their published rubric forbids partial.
    default = ('correct','unknown','wrong') if case.get('id','').endswith('-v6') else GRADES
    values = case.get('allowed_grades',default)
    if not isinstance(values,(tuple,list)) or not values or len(set(values)) != len(values) or not set(values).issubset(GRADES):
        raise ValueError('Case allowed_grades is invalid.')
    return tuple(values)


def validate_prefix(case, prefix):
    if case.get('id','').endswith('-v6'):
        raise ValueError('Legacy v6 periodic-topic probes are deprecated; create a new run with the v7 receipt case.')
    allowed_grades(case)
    if 'task_groups' in case:
        groups = case['task_groups']
        if (not isinstance(groups,dict) or not groups or
                any(not isinstance(v,list) or not v or any(not isinstance(a,str) for a in v) for v in groups.values())):
            raise ValueError('Task groups must contain non-empty acceptance lists.')
        members = [a for group in groups.values() for a in group]
        if len(members) != len(set(members)) or set(members) != set(case['expected']):
            raise ValueError('Task groups must partition all acceptance criteria exactly once.')
        if 'partial' in allowed_grades(case):
            raise ValueError('Task outcomes require complete acceptance, without partial grades.')
    if case.get('generation',{}).get('kind') == 'keyed-receipts' and set(case.get('probe_anchors',{})) != set(case['expected']):
        raise ValueError('Every receipt probe must declare its original source turn.')
    turns = {turn['id']:turn['prompt'] for turn in prefix}
    count = sum(turn['id'].startswith('load-') for turn in prefix)
    if count < case.get('minimum_load_batches',0):
        raise ValueError('Selected load does not contain every probed ticket; more load batches are required.')
    for anchor, spec in case.get('probe_anchors',{}).items():
        if spec.get('match_mode') not in (None,'labelled-receipt-line-v1'):
            raise ValueError('Unsupported receipt match mode: '+str(spec['match_mode']))
        source = turns.get(spec['source_turn'],'')
        pattern = rf'^工单 {re.escape(spec["ticket"])}｜[^\n]*回执码：{re.escape(case["expected"][anchor])}。'
        if not re.search(pattern,source,re.M):
            raise ValueError('A probe anchor is absent from its declared source turn: '+anchor)


def create(args):
    path = Path(args.output).resolve()
    if path.parent.exists():
        raise ValueError('Use a new output directory; existing runs are never overwritten.')
    if not args.model.strip() or not args.provider.strip() or args.load_batches < 1:
        raise ValueError('Model, provider and a positive load-batch count are required.')
    if getattr(args,'history_plugin',False) and getattr(args,'transport','sdk') != 'web':
        raise ValueError('The current-history plugin requires --transport web.')
    case = load(getattr(args,'casefile',None) or longcase.CASE)
    pressure = case['pressure_turns'][:args.load_batches]
    if args.load_batches > len(pressure):
        pressure += longcase.extra_batches(case,args.load_batches-len(pressure),first=len(pressure)+1)
    prefix = case['seed_turns']+pressure
    validate_prefix(case,prefix)
    root = path.parent
    root.mkdir(parents=True)
    identity = uuid.uuid4().hex
    # Keep task effects outside operator records, scoring keys, and case snapshots.
    workspace = Path(__file__).resolve().parent.parent/'conversation-bench-workspaces'/('long-'+identity)
    workspace.mkdir(parents=True, exist_ok=False)
    order = list(BRANCHES)
    random.Random(args.seed).shuffle(order)
    transport = getattr(args,'transport','sdk')
    state = {'version':1, 'id':identity,
             'method':'dsh-web-host' if transport == 'web' else 'dsh-sdk', 'case':case, 'case_hash':digest(case),
             'config':{'dsh_bin':args.dsh_bin, 'provider':args.provider, 'model':args.model,
                       'effort':args.effort, 'timeout':args.timeout,
                       'profile':'web' if transport == 'web' else 'sdk', 'transport':transport,
                       'app_version':getattr(args,'app_version','unverified')},
             'workspace':str(workspace), 'initial_files':files(workspace),
             'prefix':prefix, 'branch_order':order, 'results':{},
             'seed_sequences':{}, 'prefix_sequences':{}, 'checkpoint':None, 'pending':None, 'status':'ready', 'problems':[]}
    if getattr(args,'history_plugin',False):
        state['config']['history_plugin'] = history_plugin.freeze(root)
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
        state['prefix'] += longcase.extra_batches(state['case'],count,first=current+1)
        validate_prefix(state['case'],state['prefix'])
        save(path, state)


def checkpoint(path, state):
    validate_prefix(state['case'],state['prefix'])
    for spec in state['case'].get('probe_anchors',{}).values():
        if spec['source_turn'] not in state.get('prefix_sequences',{}):
            raise ValueError('A probed source turn has no durable admission evidence.')
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
    state['checkpoint']['anchor_sequences'] = {a:state['prefix_sequences'][spec['source_turn']]
                                               for a,spec in state['case'].get('probe_anchors',{}).items()}
    save(path, state)


def summary_text(value):
    """DSH 0.1.x emitted a summary string; 0.2.x emits text content blocks."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ''.join(block.get('text', '') for block in value
                       if isinstance(block, dict) and block.get('type') == 'text')
    return ''


def compact_proof(events, seeds):
    """Require a summary and linked model-history replacement covering all seed messages."""
    for event in events:
        data = event.get('data', {})
        text = summary_text(data.get('summary'))
        if event.get('type') != 'compaction/summary' or not text.strip():
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
                        'covered_seed_sequences':dict(seeds), 'summary':text}
    raise ValueError('No actual history replacement covers all three seed turns; compaction is unconfirmed.')


def validate_result(state, key, prompt, result):
    if result.get('finish_reason') != 'completed':
        raise ValueError('Target action did not complete: '+str(result.get('finish_reason')))
    if not isinstance(result.get('events'), list) or not isinstance(result.get('answer'), str):
        raise ValueError('Target response lacks answer text or event evidence.')
    plugin = state['config'].get('history_plugin')
    proof = result.get('history_plugin')
    if plugin and key.endswith('/recovery'):
        if (not isinstance(proof,dict) or proof.get('registered') is not True or
                any(proof.get(k) != plugin[k] for k in ('name','version','sha256','activation'))):
            raise ValueError('History plugin loading evidence is missing or differs from the frozen plugin.')
    elif proof:
        raise ValueError('History plugin appeared outside its configured recovery phase.')
    server = result.get('server')
    if state.get('server') and server != state['server']:
        raise ValueError('DSH runtime identity/version changed during the run.')
    state['server'] = server
    events = result['events']
    if key != 'B/compact' and any(e.get('type', '').startswith('compaction/') for e in events):
        raise ValueError('Unexpected automatic compaction; the uncompacted control or probe is no longer equivalent.')
    if key.startswith('prefix/'):
        matches = [e['seq'] for e in events if e.get('type') == 'user/message' and text_content(e) == prompt]
        if len(matches) != 1:
            raise ValueError('Cannot locate the admitted prefix message in durable events.')
        turn_id = key.split('/')[1]
        state.setdefault('prefix_sequences',{})[turn_id] = matches[0]
        if turn_id.startswith('seed-'):
            state['seed_sequences'][turn_id] = matches[0]
    if key == 'B/compact':
        if len(state['seed_sequences']) != len(state['case']['seed_turns']):
            raise ValueError('Seed sequence evidence is incomplete.')
        result['compaction_proof'] = compact_proof(events, state['seed_sequences'])
        summary_seq = result['compaction_proof']['summary_seq']
        covered = next(e['data']['shadowedSeqs'] for e in events if e.get('seq') == summary_seq)
        result['compaction_proof']['anchor_coverage'] = {a:seq in covered for a,seq in state['checkpoint'].get('anchor_sequences',{}).items()}
        if result['compaction_proof']['anchor_coverage'] and not any(result['compaction_proof']['anchor_coverage'].values()):
            raise ValueError('No probed source message was actually compacted; the detail comparison is invalid.')
    if key.endswith('/recall') and any(e.get('type') in ('tool/call','tool/ptc-dispatch') for e in events):
        raise ValueError('Closed-book recall invoked tools; its closed-book protocol is invalid.')
    if files(Path(state['workspace'])) != state['initial_files']:
        raise ValueError('The target changed workspace files; shared-workspace branches would be contaminated.')


def run(path, max_actions=None, driver=None):
    with locked(path):
        state = load(path)
        if digest(state['case']) != state['case_hash']:
            raise ValueError('The frozen case snapshot changed; start a new plan.')
        validate_prefix(state['case'],state['prefix'])
        if state['pending']:
            raise ValueError('Previous target action has an uncertain outcome; inspect raw logs. Automatic resend is forbidden.')
        if state['status'] in ('invalid','attention','completed'):
            raise ValueError('This run is closed or needs investigation; it cannot be automatically continued.')
        supplied_driver = driver
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
                active_driver = supplied_driver
                if active_driver is None:
                    config = dict(state['config'],history_plugin_active=key.endswith('/recovery'))
                    active_driver = WebHostDriver(config) if config.get('transport') == 'web' else DshDriver(config)
                result = active_driver.perform(home, Path(state['workspace']), state['id'], prompt, resume, wire)
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


def task_outcomes(case, anchors, protocol_valid):
    """Diagnostic checks are not independent tasks or valid trials by themselves."""
    groups = case.get('task_groups')
    if groups is None:
        return {}
    passed = {task:all(anchors[a]['grade'] == 'correct' for a in criteria)
              for task,criteria in groups.items()}
    count = sum(passed.values())
    return {'task_passes':passed, 'tasks_completed':count, 'tasks_total':len(groups),
            'task_success_rate':count/len(groups) if protocol_valid else None,
            'full_delivery_success':all(passed.values()) if protocol_valid else None,
            'task_protocol_eligible':protocol_valid}


def receipt_display_text(line):
    """Unwrap paired emphasis at field boundaries, never repair token contents."""
    emphasis = re.compile(
        r'(?<![A-Za-z0-9])(?P<mark>\*\*|__|`{1,3}|\*|_)'
        r'(?=\S)(?P<body>.*?\S)(?P=mark)(?![A-Za-z0-9])')
    while True:
        unwrapped = emphasis.sub(lambda m:m['body'],line)
        if unwrapped == line:
            return line
        line = unwrapped


def receipt_assertions(spec, answer):
    """Collect every actual assertion, including malformed and conflicting values."""
    ticket = re.compile(r'(?<![A-Za-z0-9_-])'+re.escape(spec['ticket'])+
                        r'(?![A-Za-z0-9_-])[ \t]*[:：][ \t]*')
    example = re.compile(r'示例|例如|比如|引用|e\.g\.|example',re.I)
    actual = re.compile(r'^(?:#{1,6}[ \t]*)?(?:实际答案|正式答案|我的答案|最终答案|答案|回答|核对结果)[ \t]*(?:[:：]|$)')
    label = re.compile(r'^回执码(?:[ \t]*(?:为|是))?[ \t]*[:：]?[ \t]*')
    brackets = {'（':'）','(':')','[':']','【':'】'}
    example_block = False
    values = []
    for raw in answer.splitlines():
        line = receipt_display_text(raw.strip())
        if actual.match(line):
            example_block = False
        matches = list(ticket.finditer(line))
        # A standalone example heading scopes following lines until an explicit
        # answer heading. Blank lines do not turn example content into an answer.
        if not matches and example.search(line):
            example_block = True
        if example_block or line.startswith('>'):
            continue
        for index,match in enumerate(matches):
            if example.search(line[:match.start()]):
                continue
            end = matches[index+1].start() if index+1 < len(matches) else len(line)
            body = label.sub('',line[match.end():end],count=1).strip()
            if body[:1] in brackets:
                close = body.find(brackets[body[0]],1)
                value = body[1:close] if close >= 0 else None
            else:
                token = re.match(r'[^\s,，;；。:：()（）\[\]【】]+',body)
                value = token[0] if token else None
            values.append(value)
    return values


def receipt_pair_matches(spec, expected, answer):
    if spec.get('match_mode') == 'labelled-receipt-line-v1':
        values = receipt_assertions(spec,answer)
        return bool(values) and all(value == expected for value in values)
    if spec.get('match_mode') is not None:
        raise ValueError('Unsupported receipt match mode: '+str(spec['match_mode']))
    # Preserve the published v7/v8 rule for frozen runs.
    pattern = re.escape(spec['ticket'])+r'\s*[:：]\s*'+re.escape(expected)+r'(?![0-9A-Za-z])'
    return bool(re.search(pattern,answer))


def grade(path, score_path=None):
    state = load(path)
    if state['status'] != 'completed':
        raise ValueError('Only a completed, protocol-checked run can receive final grades.')
    template = {'run_id':state['id'], 'case_hash':state['case_hash'], 'answers_sha256':answer_manifest(state),
                'allowed_grades':allowed_grades(state['case']),
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
    protocol_valid = all(c['pass'] for c in scores['protocol'].values())
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
                if value not in allowed_grades(state['case']) or not isinstance(mark.get('evidence'), str) or len(''.join(mark['evidence'].split())) < 6:
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
                spec = state['case'].get('probe_anchors',{}).get(anchor)
                if spec and value == 'correct':
                    if not receipt_pair_matches(spec,state['case']['expected'][anchor],result['answer']):
                        raise ValueError('A receipt pass contradicts the ticket/receipt pair in the answer.')
                if mark['retrieved'] and (stage != 'recovery' or not tools or not isinstance(mark.get('sources'), list)
                                          or not mark['sources'] or not all(isinstance(s,str) and s.strip() for s in mark['sources'])):
                    raise ValueError('Claimed retrieval needs recorded tools and concrete source locations in the recovery stage.')
                counts[value] += 1; omitted += mark['omitted']; retrieved += mark['retrieved']
            metrics[branch][stage] = dict(counts, retention=counts['correct']+0.5*counts['partial'],
                                           errors=counts['wrong'], omitted=omitted, retrieved=retrieved)
            metrics[branch][stage].update(task_outcomes(state['case'],anchors,protocol_valid))
    save(path.parent/'scores-reviewed.json', scores)
    state['protocol_valid'] = protocol_valid
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
              'action_elapsed_seconds':{k:r['elapsed_seconds'] for k,r in state['results'].items()},
              'history_plugin':{k:r['history_plugin'] for k,r in state['results'].items() if 'history_plugin' in r},
              'tokens':None,
              'conclusion_checks':state.get('conclusion_checks'),
              'notice':('Web-host runtime experiment (no native window), not a desktop-UI score. '
                        if state['config'].get('transport') == 'web' else
                        'SDK-profile experiment, not a desktop-UI score. ') + 'A single triplet does not establish a causal effect.'}
    rows = []
    metrics = state.get('metrics')
    task_mode = bool(state['case'].get('task_groups'))
    if metrics:
        output['differences'] = {}
        for stage in ('recall','recovery'):
            a, repeat, b = [metrics[branch][stage] for branch in BRANCHES]
            delta, noise = b['retention']-a['retention'], repeat['retention']-a['retention']
            output['differences'][stage] = {'B_minus_A':delta, 'A_repeat_minus_A':noise,
                                           'outside_repeat_variation':abs(delta)>abs(noise) if state.get('protocol_valid') else None,
                                           'B_errors_minus_A':b['errors']-a['errors']}
            if task_mode:
                output['differences'][stage]['task_success_rate_B_minus_A'] = (
                    b['task_success_rate']-a['task_success_rate'] if state.get('protocol_valid') else None)
        for branch in BRANCHES:
            for stage in ('recall','recovery'):
                m = metrics[branch][stage]
                row = [branch,stage,m['retention'],m['errors'],m['omitted'],m['retrieved']]
                if task_mode:
                    row += [str(m['tasks_completed'])+'/'+str(m['tasks_total']),m['full_delivery_success']]
                rows.append(row)
    save(path.parent/'report.json', output)
    e = lambda v:html.escape(str(v))
    headers = ['Branch','Stage',('Acceptance passed / ' if task_mode else 'Retention / ')+str(len(state['case']['expected'])),'Wrong','Omitted','Retrieved']
    if task_mode:
        headers += ['Subtasks passed (diagnostic)','Full delivery success (valid trials only)']
    table = '<table border="1"><tr>'+''.join('<th>'+e(h)+'</th>' for h in headers)+'</tr>'
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
    c.add_argument('--case',dest='casefile',help='Case JSON path; defaults to the shipped case')
    c.add_argument('--load-batches',type=positive,default=12); c.add_argument('--seed',type=int,default=42)
    c.add_argument('--timeout',type=positive,default=900)
    c.add_argument('--history-plugin',action='store_true',help='Freeze the current-session read-only plugin; enable it only during recovery (web transport).')
    c.add_argument('--transport',choices=('sdk','web'),default='sdk',
                   help='sdk: stdio JSON-RPC; web: the shipped browser runtime over its local /api transport')
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
