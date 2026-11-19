#!/usr/bin/env python3
"""Prepare web benchmark trials and score a local submission."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
from urllib.parse import urlsplit
import uuid

import codexrun

ROOT = Path(__file__).resolve().parent
SUPPORT = ROOT / 'webbench'
UPSTREAM = '8126f1ac2875282c92842e62fea7cbfecda440ec'
CUBE_5X5 = 'case09-cube-5x5'
CASES = ('case02-gravity', CUBE_5X5, 'case10-raymaze', 'case08-pelican')
MANUAL = {
    'case02-gravity': {'visual-clarity': 8, 'interactive-camera': 6, 'overlays-and-explanation': 6},
    CUBE_5X5: {'3d-clarity': 8, 'visible-turns': 7, 'interaction': 5},
    'case10-raymaze': {'visual-depth': 8, 'controls': 7, 'level-and-feedback': 5},
    'case08-pelican': {'character-and-composition': 15, 'natural-motion': 15, 'clarity-and-controls': 10},
}


def catalog(selected):
    cases = []
    for slug in selected:
        if slug not in CASES:
            raise ValueError(f'case is unavailable for new plans: {slug}')
        prompt = (SUPPORT / f'{slug}.txt').read_text(encoding='utf-8')
        cases.append({
            'id': slug, 'title': slug, 'category': 'web-bench',
            'revision': 2 if slug == CUBE_5X5 else 1, 'suite_version': 3,
            'upstream_commit': UPSTREAM, 'acceptance': [],
            'turns': [{'prompt': prompt, 'checks': []}],
            'fixtures': {},
            'snapshot_source': True,
        })
    return cases


def loopback_url(value):
    url = urlsplit(value)
    if (url.scheme != 'http' or url.hostname not in ('127.0.0.1', 'localhost')
            or url.username or url.password or url.query or url.fragment):
        raise ValueError('provide a local HTTP URL at localhost or 127.0.0.1')
    return value.rstrip('/')


def score(args):
    base = loopback_url(args.url)
    target = urlsplit(base)
    with socket.create_connection((target.hostname, target.port or 80), timeout=3):
        pass
    is_cube = args.case == CUBE_5X5
    seed = args.seed if is_cube else None
    solve_timeout = 0
    source_record = None
    candidate_files = None
    if args.record:
        raw_record = Path(args.record).read_bytes()
        record = json.loads(raw_record)
        if record['case']['id'] != args.case or record['status'] != 'completed':
            raise ValueError('record must match a completed benchmark case')
        if is_cube and record['case'].get('revision', 1) == 1:
            solve_timeout = 90000
        final = record['turns'][-1]
        files, _, limits = codexrun.snapshot(Path(record['workspace']), source=True)
        if limits or final.get('snapshot_limits') or files != final['files']:
            raise ValueError('workspace source differs from the completed record or the snapshot is incomplete')
        source_record = {'job': record['job'], 'record_sha256': hashlib.sha256(raw_record).hexdigest()}
        candidate_files = sorted(name for name in files if name.startswith('candidate/'))
    cli = shutil.which('playwright-cli')
    if cli is None:
        raise ValueError('playwright-cli is required for scoring')
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    session = 'webbench-' + uuid.uuid4().hex[:12]
    version = subprocess.check_output([cli, '--version'], text=True, timeout=15).strip()
    origins = ['http://' + target.netloc]
    config = {'base': base, 'origins': origins, 'seed': seed, 'output': str(output), 'candidateFiles': candidate_files}
    if is_cube:
        config['solveTimeout'] = solve_timeout
    source = (SUPPORT / f'{args.case}.js').read_text(encoding='utf-8')
    if is_cube:
        oracle = (SUPPORT / 'cube-oracle.js').read_text(encoding='utf-8')
        source = source.replace('__CUBE_ORACLE__', oracle, 1)
    with tempfile.TemporaryDirectory(prefix='webbench-browser-') as temp:
        snippet = Path(temp) / 'score.js'
        snippet.write_text(source.replace('__BENCH_CONFIG__', json.dumps(config), 1), encoding='utf-8')

        def call(*command, timeout=30):
            return subprocess.run([cli, f'-s={session}', *command], cwd=temp,
                                  capture_output=True, text=True, timeout=timeout)

        try:
            opened = call('open', 'about:blank')
            if opened.returncode:
                raise RuntimeError(opened.stderr or opened.stdout)
            timeout = (240 if solve_timeout else None) if is_cube else 180
            result = call('run-code', '--filename', str(snippet), timeout=timeout)
            (output / 'browser.log').write_text(result.stdout + result.stderr, encoding='utf-8')
            line = next((x for x in result.stdout.splitlines() if x.startswith('"WEBBENCH_RESULT ')), '')
            if result.returncode or not line:
                raise RuntimeError(f'browser evaluator did not return results; see {output / "browser.log"}')
            checks = json.loads(json.loads(line).removeprefix('WEBBENCH_RESULT '))
        finally:
            call('close')
    automatic = sum(c['points'] for c in checks if c['pass'])
    maximum = sum(c['points'] for c in checks)
    expected = 100 - sum(MANUAL[args.case].values())
    if maximum != expected:
        raise ValueError(f'unexpected rubric points: {maximum}')
    report = {'case': args.case, 'url': base, 'mock_seed': seed, 'playwright_cli': version,
              'record': source_record, 'auto_score': automatic, 'auto_max': maximum, 'manual_score': None,
              'manual_max': 100 - maximum, 'manual_rubric': MANUAL[args.case], 'total': None, 'checks': checks}
    (output / 'score.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'{automatic}/{maximum} automatic; human review pending ({100-maximum} points): {output}')



def manual(args):
    original = Path(args.score).read_bytes()
    auto = json.loads(original)
    rubric = MANUAL[auto['case']]
    marks = {}
    for entry in args.mark:
        key, sep, value = entry.partition('=')
        if not sep or key not in rubric or key in marks:
            raise ValueError(f'invalid or duplicate manual criterion: {key}')
        points = int(value)
        if not 0 <= points <= rubric[key]:
            raise ValueError(f'{key} must be between 0 and {rubric[key]}')
        marks[key] = points
    if marks.keys() != rubric.keys() or not args.reviewer.strip() or not args.note.strip():
        raise ValueError('provide a reviewer, rationale, and one mark for each criterion')
    report = {'case': auto['case'], 'automatic_report_sha256': hashlib.sha256(original).hexdigest(),
              'reviewer': args.reviewer, 'note': args.note, 'marks': marks,
              'auto_score': auto['auto_score'], 'manual_score': sum(marks.values()),
              'total': auto['auto_score'] + sum(marks.values())}
    with Path(args.output).open('x', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print(f"{report['total']}/100 for {args.reviewer}")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='action', required=True)
    a = sub.add_parser('prepare')
    a.add_argument('--model', action='append', required=True)
    a.add_argument('--case', action='append', choices=CASES)
    a.add_argument('--effort', default='medium')
    a.add_argument('--repeat', type=int, default=1)
    a.add_argument('--timeout', type=codexrun.positive, default=1800)
    a.add_argument('--codex', default='codex')
    a.add_argument('--output', required=True)
    s = sub.add_parser('score')
    s.add_argument('--case', choices=CASES, required=True)
    s.add_argument('--url', required=True)
    s.add_argument('--output', required=True)
    s.add_argument('--record', help='verify source workspace against a completed job record')
    s.add_argument('--seed', type=int, help='generate alternate oracle-only scrambles for the cube')
    r = sub.add_parser('manual')
    r.add_argument('--score', required=True)
    r.add_argument('--reviewer', required=True)
    r.add_argument('--mark', action='append', required=True, help='criterion=points')
    r.add_argument('--note', required=True)
    r.add_argument('--output', required=True)
    args = p.parse_args()
    try:
        if args.action == 'prepare':
            args.suite = 'webbench'
            args.cases = None
            codexrun.prepare(args, catalog=catalog(list(dict.fromkeys(args.case or CASES))))
        elif args.action == 'score':
            score(args)
        else:
            manual(args)
    except (KeyError, ValueError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        p.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
