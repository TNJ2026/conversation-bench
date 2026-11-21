"""Check recorded challenge artifacts; with --regress, also run the hidden repair scenarios.

Plain mode only reads records. --regress executes the submitted repair on randomized scenarios
inside an OS sandbox: allocation.py for Challenge3 (challenge_repair_hidden.py) and program.py
for the three Extension10 repair cases (extension_repair_hidden.py). It compares the raw results
with the reference implementation outside the sandbox and stores the outcome in the record so
export can link it to the repair requirement.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import random
import secrets
import subprocess
import sys
import sysconfig
import tempfile

from checks import csv_data_rows, strict_json

CHECK_LABELS = {
    'file_scope': '文件范围（challenge_verify）',
    'dispatch_rows': 'dispatch.csv内容（challenge_verify）',
    'routing': 'routing.json仅改kiosk（challenge_verify）',
    'dispatch_kept': 'dispatch.csv未被改动（challenge_verify）',
    'snapshot_complete': '快照完整（challenge_verify）',
}

EXPECTED_DISPATCH = [
    ['id', 'mode', 'status'], ['kiosk', 'pickup', 'ready'], ['frontdesk', 'pickup', 'ready'],
    ['night', 'after_hours', 'blocked'], ['courier', 'courier', 'ready'],
]


def csv_matches(artifacts, name, expected, ordered=True):
    rows = csv_data_rows(artifacts.get(name, ''))
    if ordered or not rows:
        return rows == expected
    return rows[0] == expected[0] and sorted(rows[1:]) == sorted(expected[1:])


def scope(before, after, editable=(), created=()):
    if set(after) != set(before) | set(created):
        return False
    changed = set(editable)
    return (all(after[name] == digest for name, digest in before.items() if name not in changed)
            and all(not after[name].startswith('symlink:') for name in changed | set(created)))


def verify(record):
    case_id = record['case']['id']
    if case_id in EXTENSION_REPAIR_CASES:
        # Extension10 file checks are recorded by study.py; only the hidden regression is added here.
        return []
    previous = initial = record['initial_files']
    results = []
    for n, turn in enumerate(record['turns'], 1):
        files, artifacts = turn['files'], turn['artifacts']
        checks = {}
        if turn.get('snapshot_limits'):
            results.append({'turn': n, 'checks': {'snapshot_complete': None}})
            previous = None
            continue

        def check_scope(editable=(), created=()):
            checks['file_scope'] = None if previous is None else scope(previous, files, editable, created)

        if case_id == 'adv-repair-receipt-replay':
            check_scope(editable=('allocation.py', 'test_allocation.py') if n == 1 else ())
        elif case_id == 'adv-recover-routing-export':
            if n == 1:
                check_scope(created=('dispatch.csv',))
                try:
                    checks['dispatch_rows'] = csv_matches(artifacts, 'dispatch.csv', EXPECTED_DISPATCH, ordered=False)
                except csv.Error:
                    checks['dispatch_rows'] = False
            else:
                check_scope(editable=('routing.json',))
                expected = json.loads(record['case']['fixtures']['routing.json'])
                expected['routes'][0]['mode'] = 'courier'
                try:
                    checks['routing'] = strict_json(artifacts.get('routing.json', '')) == expected
                except ValueError:
                    checks['routing'] = False
                checks['dispatch_kept'] = (None if previous is None else 'dispatch.csv' in previous
                                           and files.get('dispatch.csv') == previous['dispatch.csv'])
        elif case_id == 'adv-release-evidence-gates':
            checks['file_scope'] = scope(initial, files)
        else:
            raise ValueError(f'unknown Challenge3 case: {case_id}')
        results.append({'turn': n, 'checks': checks})
        previous = files
    return results


HIDDEN = Path(__file__).with_name('challenge_repair_hidden.py')
REPAIR_CASE = 'adv-repair-receipt-replay'
REGRESSION_CHECK = '未公开回归测试（challenge_repair_hidden）'
EXTENSION_HIDDEN = Path(__file__).with_name('extension_repair_hidden.py')
EXTENSION_REPAIR_CASES = ('repair-stable-priority', 'repair-atomic-batch', 'repair-overnight-window')
EXTENSION_REGRESSION_CHECK = '未公开回归测试（extension_repair_hidden）'
SANDBOX_EXEC = Path('/usr/bin/sandbox-exec')
# Runs inside the sandbox. It only executes the submission on the given inputs and reports raw
# results; the parent compares them with the reference, so nothing printed here decides a verdict.
BOOTSTRAP = """import io, json, os, resource, sys
resource.setrlimit(resource.RLIMIT_FSIZE, (262144, 262144))
request = json.loads(sys.stdin.read())
sys.path.insert(0, os.getcwd())
print('READY-' + request['nonce'], flush=True)
def encode(value):
    if not isinstance(value, dict):
        return dict(kind='bad', detail='replay did not return a dict')
    try:
        return dict(kind='ok', balances=sorted([list(k) + [v] for k, v in value.items()], key=repr))
    except TypeError:
        return dict(kind='bad', detail='balance keys are not (order, sku) pairs')
results = []
try:
    import allocation
except Exception as error:
    results = [dict(kind='import_error', detail=type(error).__name__)]
else:
    for scenario in request['scenarios']:
        outcome = []
        for call in scenario['calls']:
            initial = {tuple(k): v for *k, v in call['initial']}
            rows = None
            rows_before = None
            try:
                if call['csv'] is not None:
                    rows = allocation.read_receipts(io.StringIO(call['csv']))
                else:
                    rows = call['receipts']
                rows_before = json.dumps(rows, sort_keys=True)
                result = encode(allocation.replay(initial, rows))
            except ValueError:
                result = dict(kind='error', detail='ValueError')
            except Exception as error:
                result = dict(kind='crash', detail=type(error).__name__)
            if json.dumps(sorted([list(k) + [v] for k, v in initial.items()], key=repr)) != json.dumps(sorted(call['initial'], key=repr)):
                result = dict(kind='bad', detail='initial balances were modified')
            elif rows_before is not None and json.dumps(rows, sort_keys=True) != rows_before:
                result = dict(kind='bad', detail='receipt rows were modified')
            outcome.append(result)
        results.append(outcome)
sys.stdout.write('\\n' + request['nonce'] + json.dumps(results) + '\\n')
sys.stdout.flush()
"""


# Runs inside the sandbox for the Extension10 repairs. Like BOOTSTRAP it only reports raw
# results; mutation and return-shape checks are facts about the call, the verdict is the parent's.
EXTENSION_BOOTSTRAP = """import copy, json, os, resource, sys
resource.setrlimit(resource.RLIMIT_FSIZE, (262144, 262144))
request = json.loads(sys.stdin.read())
sys.path.insert(0, os.getcwd())
print('READY-' + request['nonce'], flush=True)
def bad(detail):
    return dict(kind='bad', detail=detail)
def rank(program, call):
    rows = [dict(row) for row in call['rows']]
    before, identities = copy.deepcopy(rows), [id(row) for row in rows]
    try:
        out = program.rank(rows)
    except ValueError:
        return dict(kind='error')
    if [id(row) for row in rows] != identities or json.dumps(rows) != json.dumps(before):
        return bad('input list or elements were modified')
    if out is rows or not isinstance(out, list):
        return bad('rank did not return a new list')
    position = {id(row): i for i, row in enumerate(rows)}
    if any(id(row) not in position for row in out):
        return bad('returned elements are not the input elements')
    return dict(kind='ok', order=[position[id(row)] for row in out])
def updates(program, call):
    current = dict(call['current'])
    before = json.dumps(current, sort_keys=True)
    try:
        out = program.apply_updates(current, [tuple(item) for item in call['updates']])
    except ValueError:
        out = None
    if json.dumps(current, sort_keys=True) != before:
        return bad('current was modified')
    if out is None:
        return dict(kind='error')
    if out is current or not isinstance(out, dict):
        return bad('apply_updates did not return a new dict')
    try:
        return dict(kind='ok', value=json.loads(json.dumps(sorted([k, v] for k, v in out.items()))))
    except (TypeError, ValueError):
        return bad('result is not a plain mapping of names to numbers')
def window(program, call):
    values = []
    for start, end, minute in call['triples']:
        try:
            value = program.inside(start, end, minute)
        except ValueError:
            return dict(kind='error')
        if not isinstance(value, bool):
            return bad('inside returned a non-bool')
        values.append(value)
    return dict(kind='ok', values=values)
runner = {'repair-stable-priority': rank, 'repair-atomic-batch': updates, 'repair-overnight-window': window}[request['case']]
results = []
try:
    import program
except Exception as error:
    results = [dict(kind='import_error', detail=type(error).__name__)]
else:
    for scenario in request['scenarios']:
        outcome = []
        for call in scenario['calls']:
            try:
                outcome.append(runner(program, call))
            except Exception as error:
                outcome.append(dict(kind='crash', detail=type(error).__name__))
        results.append(outcome)
sys.stdout.write('\\n' + request['nonce'] + json.dumps(results) + '\\n')
sys.stdout.flush()
"""


def wire(calls):
    """JSON-safe form of scenario calls; tuple keys become [order, sku, value] rows."""
    return [dict(initial=[[*k, v] for k, v in initial.items()],
                 csv=receipts if isinstance(receipts, str) else None,
                 receipts=None if isinstance(receipts, str) else receipts) for initial, receipts in calls]


def reference_form(want):
    return [dict(kind='ok', balances=sorted([[*k, v] for k, v in balances.items()], key=repr)) if kind == 'ok'
            else dict(kind='error', detail='ValueError') for kind, balances in want]


def sandbox_command(directory, bootstrap=BOOTSTRAP):
    if sys.platform != 'darwin' or not SANDBOX_EXEC.is_file():
        return None
    python = Path(sys.executable).resolve()
    libraries = {Path(sysconfig.get_path(kind)).resolve() for kind in ('stdlib', 'platstdlib')}
    read_dirs = [directory, *sorted(libraries), Path('/usr/lib'), Path('/System/Library')]
    library_parents = {library.parent for library in libraries}
    shared_library = sysconfig.get_config_var('LDLIBRARY')
    libdir = sysconfig.get_config_var('LIBDIR')
    read_files = {Path('/'), python, python.parent, *library_parents}
    if shared_library and libdir:
        read_files.add((Path(libdir) / shared_library).resolve())

    literals = ' '.join(f'(literal {json.dumps(str(path))})' for path in sorted(read_files))
    subpaths = ' '.join(f'(subpath {json.dumps(str(path))})' for path in read_dirs)
    profile = (
        '(version 1) (deny default) (allow file-read-metadata) (allow sysctl-read) '
        f'(allow process-exec (literal {json.dumps(str(python))})) '
        f'(allow file-read-data {literals} {subpaths})'
    )
    return [str(SANDBOX_EXEC), '-p', profile, str(python), '-I', '-B', '-S', '-c', bootstrap]


def repair_spec(case_id):
    """How to run the hidden regression for a repair case, or None for other cases."""
    if case_id == REPAIR_CASE:
        import challenge_repair_hidden as hidden
        return dict(artifact='allocation.py', check=REGRESSION_CHECK, hidden=HIDDEN, bootstrap=BOOTSTRAP,
                    scenarios=hidden.scenarios, inputs=wire, request={}, strict=False,
                    reference=lambda calls: reference_form(hidden.expected(calls)))
    if case_id in EXTENSION_REPAIR_CASES:
        import extension_repair_hidden as hidden
        return dict(artifact='program.py', check=EXTENSION_REGRESSION_CHECK, hidden=EXTENSION_HIDDEN,
                    bootstrap=EXTENSION_BOOTSTRAP, scenarios=lambda rng: hidden.scenarios(case_id, rng),
                    inputs=lambda calls: calls, request=dict(case=case_id), strict=True,
                    reference=lambda calls: hidden.expected(case_id, calls))
    return None


def regress(record, timeout=60, *, seed=None):
    """Run randomized hidden scenarios against the turn-1 repair; None when there is nothing to test.

    The submission only ever sees scenario inputs. Its raw results are compared with the
    reference implementation here, outside the sandbox, so printing success markers,
    exiting early or patching unittest inside the sandbox cannot produce a pass.
    """
    turns = record.get('turns') or []
    spec = repair_spec(record['case']['id'])
    if spec is None or not turns:
        return None
    artifact = spec['artifact']
    source = turns[0].get('artifacts', {}).get(artifact)
    hidden = spec['hidden'].read_text(encoding='utf-8')
    base = dict(turn=1, hidden_sha256=hashlib.sha256(hidden.encode()).hexdigest())
    if source is None:
        return dict(base, **{'pass': False}, summary=f'第1轮快照中没有 {artifact}')
    seed = secrets.randbits(64) if seed is None else seed
    cases = spec['scenarios'](random.Random(seed))
    nonce = 'RESULT-' + secrets.token_hex(16) + ':'
    inputs = [dict(name=name, calls=spec['inputs'](calls)) for name, calls in cases]
    base.update(seed=seed, inputs_sha256=hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest())
    request = json.dumps(dict(nonce=nonce, scenarios=inputs, **spec['request']))
    with tempfile.TemporaryDirectory(prefix='challenge-regress-') as temporary:
        directory = Path(temporary).resolve()
        command = sandbox_command(directory, spec['bootstrap'])
        if command is None:
            return dict(base, **{'pass': None}, summary='缺少受支持的评审沙箱（macOS sandbox-exec）')
        try:
            (directory / artifact).write_text(source, encoding='utf-8')
            with tempfile.TemporaryFile() as stdin, tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
                stdin.write(request.encode()); stdin.seek(0)
                try:
                    completed = subprocess.run(command, cwd=directory, env={'HOME': str(directory)}, stdin=stdin,
                                               stdout=stdout, stderr=stderr, timeout=timeout)
                except subprocess.TimeoutExpired:
                    completed = None
                stdout.seek(0)
                output = stdout.read(262144).decode('utf-8', errors='replace').splitlines()
        except OSError as error:
            return dict(base, **{'pass': None}, summary=f'评审沙箱启动失败：{error}')
    if not output or output[0] != 'READY-' + nonce:
        status = f'退出码 {completed.returncode}' if completed is not None else f'超过 {timeout} 秒'
        return dict(base, **{'pass': None}, summary=f'评审沙箱未完成初始化（{status}）')
    if completed is None:
        return dict(base, **{'pass': False}, summary=f'回归执行超过 {timeout} 秒未结束')
    if completed.returncode != 0:
        return dict(base, **{'pass': False}, summary=f'被测回归进程异常退出（退出码 {completed.returncode}）')
    reports = [line[len(nonce):] for line in output[1:] if line.startswith(nonce)]
    try:
        results = json.loads(reports[-1]) if reports else None
    except (ValueError, RecursionError):
        results = None
    if not isinstance(results, list):
        return dict(base, **{'pass': False}, summary='沙箱内没有返回可解析的运行结果（被测代码崩溃、提前退出或截断了输出）')
    if len(results) == 1 and isinstance(results[0], dict) and results[0].get('kind') == 'import_error':
        return dict(base, **{'pass': False}, summary=f'导入 {artifact} 失败：{results[0].get("detail")}')
    failed = []
    for (name, calls), got in zip(cases, results + [None] * (len(cases) - len(results))):
        want = spec['reference'](calls)
        # Extension10 compares JSON text so True and 1, or 5 and 5.0, are not treated as equal;
        # Challenge3 keeps its original value comparison.
        same = (json.dumps(got, sort_keys=True) == json.dumps(want, sort_keys=True)) if spec['strict'] else got == want
        if not same:
            failed.append(name)
    total = len(cases)
    summary = (f'{total - len(failed)}/{total} 个场景与参考实现一致' +
               ('；不一致：' + '、'.join(failed) if failed else '') + '；判定在沙箱外完成')
    return dict(base, **{'pass': not failed}, summary=summary)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--study', required=True, type=Path)
    parser.add_argument('--regress', action='store_true',
                        help='执行被测 allocation.py 或 program.py 与未公开回归测试，并把结果写回记录（会运行被测代码）')
    parser.add_argument('--seed', type=int, help='复跑指定的回归输入；省略时为本批次随机生成一个种子')
    args = parser.parse_args()
    if args.seed is not None and not args.regress:
        parser.error('--seed requires --regress')
    seed = secrets.randbits(64) if args.regress and args.seed is None else args.seed
    records = []
    for path in sorted((args.study / 'records').glob('J*.json')):
        record = json.loads(path.read_text(encoding='utf-8'))
        if record['case'].get('suite') != 'v3-challenge3' and record['case']['id'] not in EXTENSION_REPAIR_CASES:
            continue
        if args.regress and repair_spec(record['case']['id']) and record.get('status') == 'completed':
            outcome = regress(record, seed=seed)
            if outcome is not None and outcome['pass'] is None:
                print(f'{record["job"]}: 回归未执行，结果记为待定（{outcome["summary"]}）；R2 不受约束，需人工判断',
                      file=sys.stderr)
            if outcome is not None:
                # Export binds record hashes, so run this before export; afterwards the old binding is rejected.
                record['hidden_regression'] = outcome
                path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        records.append({'job': record['job'], 'case': record['case']['id'], 'checks': verify(record),
                        'hidden_regression': record.get('hidden_regression')})
    if not records:
        parser.error('study has no Challenge3 or Extension10 repair records')
    print(json.dumps(records, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
