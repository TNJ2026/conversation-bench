"""Check recorded challenge artifacts without executing submitted code."""
import argparse
import csv
import io
import json
from pathlib import Path

EXPECTED_DISPATCH = [
    ['id', 'mode', 'status'], ['kiosk', 'pickup', 'ready'], ['frontdesk', 'pickup', 'ready'],
    ['night', 'after_hours', 'blocked'], ['courier', 'courier', 'ready'],
]


def csv_rows(artifacts, name):
    return list(csv.reader(io.StringIO(artifacts.get(name, '')), strict=True))


def json_object(artifacts, name):
    def unique(items):
        result = dict(items)
        if len(result) != len(items):
            raise ValueError('duplicate JSON key')
        return result
    return json.loads(artifacts.get(name, ''), object_pairs_hook=unique)


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
                    checks['routing'] = json_object(artifacts, 'routing.json') == expected
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', required=True, type=Path)
    args = parser.parse_args()
    records = []
    for path in sorted((args.study / 'records').glob('J*.json')):
        record = json.loads(path.read_text(encoding='utf-8'))
        records.append({'job': record['job'], 'case': record['case']['id'], 'checks': verify(record)})
    if not records:
        parser.error('study has no records')
    print(json.dumps(records, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
