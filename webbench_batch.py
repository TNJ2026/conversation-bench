"""Run and automatically score frozen WebBench records."""
import argparse
from collections import defaultdict
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from threading import Thread

import codexrun
import study
import webbench

GENERATED = {'.git', '.next', 'node_modules'}
ENTRY = {'case08-pelican': 'index.svg'}
# Each case is scored on this run's same seed across models and repetitions.
DEFAULT_SEED = 34021


class SubmissionError(RuntimeError):
    pass


class EnvironmentError(RuntimeError):
    pass


@contextmanager
def listening(handler):
    with ThreadingHTTPServer(('127.0.0.1', 0), handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f'http://127.0.0.1:{server.server_port}'
        finally:
            server.shutdown()
            thread.join()


class StaticHandler(SimpleHTTPRequestHandler):
    def list_directory(self, path):
        self.send_error(404)
        return None

    def log_message(self, *args):
        pass


def stage_candidate(workspace, destination):
    submitted = workspace / 'candidate'
    if submitted.is_symlink() or not submitted.is_dir():
        raise SubmissionError('candidate/ missing or is not a regular directory')

    def copy_dir(src, dest):
        dest.mkdir()
        for item in src.iterdir():
            if item.name in GENERATED:
                continue
            if item.is_symlink():
                raise SubmissionError(f'candidate contains a symbolic link: {item.relative_to(submitted)}')
            target = dest / item.name
            if item.is_dir():
                copy_dir(item, target)
            elif item.is_file():
                shutil.copyfile(item, target)
            else:
                raise SubmissionError(f'unsupported candidate file: {item.relative_to(submitted)}')

    copy_dir(submitted, destination)


def automatic_score(record_path, record, result_dir, seed):
    case = record['case']['id']
    workspace = Path(record['workspace'])
    if not workspace.is_dir():
        raise EnvironmentError('original submission workspace is unavailable')
    final = record['turns'][-1]
    current, _, limits = codexrun.snapshot(workspace, source=True)
    if limits or final.get('snapshot_limits') or current != final['files']:
        raise EnvironmentError('original source no longer matches the recorded snapshot')
    with tempfile.TemporaryDirectory(prefix='webbench-batch-') as temp:
        root = Path(temp).resolve()
        candidate = root/'candidate'
        stage_candidate(workspace, candidate)
        entry = ENTRY.get(case, 'index.html')
        if not (candidate/entry).is_file():
            raise SubmissionError(f'{entry} is missing from candidate/')
        with listening(partial(StaticHandler, directory=str(candidate))) as address:
            webbench.score(argparse.Namespace(case=case, url=address, seed=seed,
                                              output=str(result_dir/'browser'), record=str(record_path)))
    return study.load(result_dir/'browser'/'score.json')


def report(output, outcomes):
    study.save(output/'results.json', outcomes)
    execution_labels = ' | '.join(label for _, label in codexrun.EXECUTION_COLUMNS)
    lines = ['# WebBench automatic scores', '', f'| Job | Model | Case | Status | Automatic | {execution_labels} |',
             '|---|---|---|---|---:|' + '---:|' * len(codexrun.EXECUTION_COLUMNS)]
    groups = defaultdict(list)
    for item in outcomes:
        job, model, case = (item[k] for k in ('job','model','case'))
        earned = item.get('auto_score')
        score = '—' if earned is None else f"{earned}/{item['auto_max']}"
        path = f'[{job}]({job}/browser/score.json)' if item['status'] == 'scored' else job
        execution = ' | '.join(codexrun.execution_cells(item.get('execution', {})))
        lines.append(f"| {path} | {model} | {case} | {item['status']} | {score} | {execution} |")
        groups[model].append(item)
    lines += ['', '| Model | Scored cases | Raw automatic points | Equal-case automatic / 100 |', '|---|---:|---:|---:|']
    for model, items in groups.items():
        scores = [x for x in items if x.get('auto_score') is not None]
        total = f"{sum(x['auto_score'] for x in scores)}/{sum(x['auto_max'] for x in scores)}" if scores else '—'
        by_case = defaultdict(list)
        for row in scores:
            by_case[row['case']].append(row['auto_score']/row['auto_max'])
        balanced = (f'{100 * sum(sum(v)/len(v) for v in by_case.values())/len(by_case):.2f}'
                    if scores and len(scores) == len(items) else '—')
        lines.append(f'| {model} | {len(scores)}/{len(items)} | {total} | {balanced} |')
    lines += ['', 'Missing records and infrastructure failures are kept out of totals. A submission that could not be built or started due to its own files receives zero. Manual review is separate.', '']
    (output/'report.md').write_text('\n'.join(lines), encoding='utf-8')


def batch(args):
    folder = Path(args.study).resolve()
    plan = study.load(folder/'plan.json')
    if study.digest(plan) != study.load(folder/'plan-binding.json')['sha256']:
        raise ValueError('invalid plan binding')
    if not plan['jobs'] or any(job['case']['id'] not in webbench.CASES for job in plan['jobs']):
        raise ValueError('the study must contain WebBench cases only')
    playwright = shutil.which('playwright-cli')
    if not playwright:
        raise EnvironmentError('playwright-cli is required')
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    study.save(output/'configuration.json', {'plan_sha256':study.digest(plan), 'seed':args.seed})
    if args.generate:
        codexrun.execute(folder)
    outcomes = []
    for job in plan['jobs']:
        job_id, case = job['id'], job['case']['id']
        model = f"{job['arm']['model']}@{job['arm']['effort']}"
        item = dict(job=job_id, case=case, model=model)
        path = folder/'records'/f'{job_id}.json'
        record = study.load(path) if path.exists() else None
        bound = (record and record.get('job') == job_id and record.get('case_hash') == job['case_hash']
                 and study.digest(record.get('case')) == job['case_hash'])
        item['execution'] = codexrun.case_execution(record if bound else None)
        if not record or record['status'] != 'completed':
            item['status'] = record['status'] if record else 'pending'
        else:
            dest = output/job_id
            dest.mkdir()
            try:
                if not bound:
                    raise EnvironmentError('record is not bound to the planned case')
                result = automatic_score(path, record, dest, args.seed)
                item.update(status='scored', auto_score=result['auto_score'], auto_max=result['auto_max'])
            except SubmissionError as error:
                item.update(status='submission-failed', auto_score=0,
                            auto_max=100-sum(webbench.MANUAL[case].values()), error=str(error))
            except (EnvironmentError, OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
                item.update(status='evaluation-blocked', error=str(error))
        outcomes.append(item)
        report(output, outcomes)
        print(job_id, model, case, item['status'], item.get('error', item.get('auto_score', '')), flush=True)
    return all(x['status'] in ('scored', 'submission-failed') for x in outcomes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--study', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--generate', action='store_true', help='run the frozen model plan before grading')
    parser.add_argument('--seed', type=int, default=DEFAULT_SEED)
    args = parser.parse_args()
    try:
        return 0 if batch(args) else 1
    except (EnvironmentError, OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    sys.exit(main())
