"""Check recorded challenge artifacts; with --regress, also run the hidden repair tests.

Plain mode only reads records. --regress executes the submitted allocation.py against
challenge_repair_hidden.py in an OS sandbox and stores the outcome in the record
so export can link it to the repair requirement.
"""
import argparse
import csv
import io
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import sysconfig
import tempfile

from checks import strict_json

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


def csv_rows(artifacts, name):
    return list(csv.reader(io.StringIO(artifacts.get(name, '')), strict=True))


def csv_matches(artifacts, name, expected, ordered=True):
    rows = csv_rows(artifacts, name)
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
SANDBOX_EXEC = Path('/usr/bin/sandbox-exec')
BOOTSTRAP = """import os, resource, runpy, sys, unittest
resource.setrlimit(resource.RLIMIT_FSIZE, (262144, 262144))
sys.path.insert(0, os.getcwd())
print('review sandbox ready', flush=True)
suite = unittest.TestSuite()
namespace = runpy.run_path('challenge_repair_hidden.py')
for item in namespace.values():
    if isinstance(item, type) and issubclass(item, unittest.TestCase):
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(item))
result = unittest.TextTestRunner(verbosity=2).run(suite)
print('review tests finished', flush=True)
sys.exit(0 if result.testsRun and result.wasSuccessful() else 1)
"""


def sandbox_command(directory):
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
    return [str(SANDBOX_EXEC), '-p', profile, str(python), '-I', '-B', '-S', '-c', BOOTSTRAP]


def regress(record, timeout=60):
    """Run the hidden tests against the turn-1 allocation.py; None when the record has nothing to test."""
    turns = record.get('turns') or []
    if record['case']['id'] != REPAIR_CASE or not turns:
        return None
    source = turns[0].get('artifacts', {}).get('allocation.py')
    hidden = HIDDEN.read_text(encoding='utf-8')
    base = dict(turn=1, hidden_sha256=hashlib.sha256(hidden.encode()).hexdigest())
    if source is None:
        return dict(base, **{'pass': False}, summary='第1轮快照中没有 allocation.py')
    with tempfile.TemporaryDirectory(prefix='challenge-regress-') as temporary:
        directory = Path(temporary).resolve()
        command = sandbox_command(directory)
        if command is None:
            return dict(base, **{'pass': None}, summary='缺少受支持的评审沙箱（macOS sandbox-exec）')
        (directory / 'allocation.py').write_text(source, encoding='utf-8')
        (directory / 'challenge_repair_hidden.py').write_text(hidden, encoding='utf-8')
        try:
            with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
                done = subprocess.run(command, cwd=directory, env={'HOME': str(directory)}, stdin=subprocess.DEVNULL,
                                      stdout=stdout, stderr=stderr, timeout=timeout)
                stdout.seek(0)
                stderr.seek(0)
                output = stdout.read(262144).decode('utf-8', errors='replace').splitlines()
                errors = stderr.read(262144).decode('utf-8', errors='replace')
        except subprocess.TimeoutExpired:
            return dict(base, **{'pass': False}, summary=f'超过 {timeout} 秒未结束')
        except OSError as error:
            return dict(base, **{'pass': None}, summary=f'评审沙箱启动失败：{error}')
    if not output or output[0] != 'review sandbox ready':
        return dict(base, **{'pass': None}, summary='评审沙箱未完成初始化')
    lines = [x for x in errors.strip().splitlines() if x.strip()]
    tail = lines[-1] if lines else ''
    failed = [x for x in lines if x.startswith(('FAIL:', 'ERROR:'))]
    passed = done.returncode == 0 and 'review tests finished' in output
    summary = tail + ('；' + '；'.join(failed) if failed else '')
    return dict(base, **{'pass': passed}, summary=summary or '回归测试未完整执行')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--study', required=True, type=Path)
    parser.add_argument('--regress', action='store_true',
                        help='执行被测 allocation.py 与未公开回归测试，并把结果写回记录（会运行被测代码）')
    args = parser.parse_args()
    records = []
    for path in sorted((args.study / 'records').glob('J*.json')):
        record = json.loads(path.read_text(encoding='utf-8'))
        if args.regress and record['case']['id'] == REPAIR_CASE and record.get('status') == 'completed':
            outcome = regress(record)
            if outcome is not None:
                # Export binds record hashes, so run this before export; afterwards the old binding is rejected.
                record['hidden_regression'] = outcome
                path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        records.append({'job': record['job'], 'case': record['case']['id'], 'checks': verify(record),
                        'hidden_regression': record.get('hidden_regression')})
    if not records:
        parser.error('study has no records')
    print(json.dumps(records, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
