"""Mock Claude Code CLI integration only: no provider requests or account usage."""
import contextlib
import io
import json
import shutil
from pathlib import Path
import sys
import tempfile
import textwrap
import unittest
from argparse import Namespace
from unittest.mock import patch

import clauderun as runner
import codexrun
import study

FAKE = r'''
import json,os,sys,uuid
from pathlib import Path
args=sys.argv[1:]
if args==['--version']:
    print('2.0.0 (Claude Code fixture)');raise SystemExit
prompt=sys.stdin.read()
log=Path(__file__).with_name('calls.jsonl')
with log.open('a') as f: f.write(json.dumps(dict(args=args,prompt=prompt,cwd=str(Path.cwd()),
    leaked=[k for k in os.environ if k in ('CLAUDECODE','CLAUDE_CODE_SESSION_ID')]))+'\n')
model=args[args.index('--model')+1]
session=args[args.index('--resume')+1] if '--resume' in args else args[args.index('--session-id')+1]
if model=='wrongthread' and '--resume' in args: session=str(uuid.uuid4())
def emit(**e): print(json.dumps(dict(session_id=session,**e)))
emit(type='system',subtype='init',model=model+'-served',tools=['Read','Write'])
if model=='writer':
    Path('note.md').write_text('written')
    emit(type='assistant',message={'content':[{'type':'tool_use','id':'t1','name':'Write','input':{'file_path':'note.md'}}]})
    emit(type='user',message={'content':[{'type':'tool_result','tool_use_id':'t1','content':'ok'}]})
emit(type='assistant',message={'content':[{'type':'text','text':'fixture answer'}]})
if model=='failure':
    emit(type='result',subtype='error_during_execution',is_error=True,result='');raise SystemExit(1)
emit(type='result',subtype='success',is_error=False,result='fixture answer',num_turns=1,total_cost_usd=0.01,
     usage={'input_tokens':10,'output_tokens':2},
     permission_denials=[{'tool_name':'Bash','tool_input':{'command':'curl x'}}] if model=='denied' else [])
'''


class ClaudeRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.bin = self.root/'claude-fixture'
        self.bin.write_text('#!'+sys.executable+'\n'+textwrap.dedent(FAKE)); self.bin.chmod(0o700)
        self.output = self.root/'batch'
        quiet = contextlib.redirect_stdout(io.StringIO()); quiet.__enter__(); self.addCleanup(quiet.__exit__, None, None, None)
        original = codexrun.tempfile.mkdtemp
        patcher = patch.object(codexrun.tempfile, 'mkdtemp', side_effect=lambda **kw: original(dir=self.root, **kw))
        patcher.start(); self.addCleanup(patcher.stop)

    def prepare(self, models=('model-a',), cases='adv-approved-picklist', **extra):
        options = dict(model=list(models), effort='high', suite=study.DEFAULT_SUITE, cases=cases, repeat=1, timeout=5,
                       permission_mode='acceptEdits', allowed_tools=None, max_budget_usd=None,
                       claude=str(self.bin), output=str(self.output)) | extra
        runner.prepare(Namespace(**options))

    def calls(self):
        path = self.root/'calls.jsonl'
        return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []

    def run_plan(self):
        with patch.dict('os.environ', {'CLAUDECODE': '1', 'CLAUDE_CODE_SESSION_ID': 'parent'}):
            return codexrun.execute(self.output, runner)

    def records(self):
        return codexrun.records_for(self.output)[1]

    def test_prepare_never_calls_model(self):
        self.prepare(models=['claude-opus-5-5@high', 'claude-sonnet-5-5@medium'])
        self.assertEqual(self.calls(), [])
        plan = study.load(self.output/'plan.json')
        self.assertEqual(plan['runner'], 'claude-code-cli'); self.assertEqual(len(plan['jobs']), 2)
        with self.assertRaises(ValueError): runner.arm_specs(['m@ultra'], 'high')

    def test_isolation_flags_session_resume_and_clean_env(self):
        self.prepare()
        self.assertTrue(self.run_plan())
        first, second = self.calls()
        for call in (first, second):
            for flag in ('--safe-mode', '--strict-mcp-config', '--disable-slash-commands'):
                self.assertIn(flag, call['args'])
            self.assertEqual(call['args'][call['args'].index('--setting-sources')+1], 'project')
            self.assertEqual(call['args'][call['args'].index('--permission-mode')+1], 'acceptEdits')
            self.assertEqual(call['leaked'], [])
            self.assertNotIn(str(Path(runner.__file__).parent), call['cwd'])
        session = first['args'][first['args'].index('--session-id')+1]
        self.assertEqual(second['args'][second['args'].index('--resume')+1], session)
        self.assertEqual(first['cwd'], second['cwd'])
        r = self.records()[0]
        self.assertEqual((r['status'], r['thread_id'], r['protocol']['method']), ('completed', session, 'claude-code-cli'))
        self.assertEqual(r['turns'][0]['reported_model'], 'model-a-served')
        self.assertEqual(r['turns'][0]['answer'], 'fixture answer')
        self.assertIn('Claude Code CLI', (self.output/'report.md').read_text())

    def test_tool_calls_and_permission_denials_are_execution_evidence(self):
        self.prepare(models=['writer', 'denied'], cases='adv-room-reassignment')
        self.run_plan()
        by_model = {r['config']['model']: r for r in self.records()}
        evidence = by_model['writer']['turns'][0]['execution_evidence']
        self.assertEqual([json.loads(e['text'])['block']['type'] for e in evidence], ['tool_use', 'tool_result'])
        self.assertIn('note.md', by_model['writer']['turns'][0]['files'])
        denial = json.loads(by_model['denied']['turns'][0]['execution_evidence'][0]['text'])
        self.assertEqual(denial['type'], 'permission_denial')

    def test_failure_and_session_change_stop_without_retry(self):
        self.prepare(models=['failure', 'wrongthread'])
        self.assertFalse(self.run_plan())
        by_model = {r['config']['model']: r for r in self.records()}
        self.assertEqual(by_model['failure']['status'], 'failed'); self.assertEqual(len(by_model['failure']['turns']), 1)
        self.assertEqual(by_model['wrongthread']['status'], 'failed')
        self.assertIn('不同会话', by_model['wrongthread']['error'])
        self.assertEqual(len(self.calls()), 3)  # failure 1 turn, wrongthread 2 turns; nothing resent

    def test_plan_options_are_passed_through(self):
        self.prepare(permission_mode='dontAsk', allowed_tools='Bash(ls *)', max_budget_usd=0.5)
        plan = study.load(self.output/'plan.json')
        cmd = runner.command(plan, plan['arms'][0])
        self.assertEqual(cmd[cmd.index('--permission-mode')+1], 'dontAsk')
        self.assertEqual(cmd[cmd.index('--allowed-tools')+1], 'Bash(ls *)')
        self.assertEqual(cmd[cmd.index('--max-budget-usd')+1], '0.5')

    def test_command_cases_allow_python_runs_by_default(self):
        self.prepare(cases='adv-repair-receipt-replay')
        plan = study.load(self.output/'plan.json')
        self.assertEqual(plan['allowed_tools'], runner.COMMAND_TOOLS)
        cmd = runner.command(plan, plan['arms'][0])
        self.assertEqual(cmd[cmd.index('--allowed-tools')+1], 'Bash(python3 -B *)')

    def test_command_allowance_respects_explicit_choice_and_other_cases(self):
        self.prepare(cases='adv-repair-receipt-replay', allowed_tools='')
        self.assertEqual(study.load(self.output/'plan.json')['allowed_tools'], '')
        shutil.rmtree(self.output)
        self.prepare(cases='adv-room-reassignment')
        self.assertEqual(study.load(self.output/'plan.json')['allowed_tools'], '')
        shutil.rmtree(self.output)
        self.prepare(cases='adv-repair-receipt-replay', permission_mode='bypassPermissions')
        self.assertEqual(study.load(self.output/'plan.json')['allowed_tools'], '')

    def test_delete_case_allows_only_the_listed_rm_rules(self):
        self.prepare(cases='guard-confirm-supersede', suite='v3-guard4')
        allowed = study.load(self.output/'plan.json')['allowed_tools']
        self.assertEqual(allowed, 'Bash(rm report-*),Bash(rm -f report-*)')
        self.assertNotIn('python3', allowed)

    def test_conflicting_session_ids_bind_no_thread(self):
        path = self.root/'events.jsonl'
        path.write_text('\n'.join(json.dumps(e) for e in (
            dict(type='system', subtype='init', session_id='a'),
            dict(type='result', subtype='success', is_error=False, result='x', session_id='b'))))
        self.assertIsNone(runner.parse_events(path)['thread'])


if __name__ == '__main__':
    unittest.main()
