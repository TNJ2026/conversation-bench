"""Mock CLI integration only: no provider requests or account usage."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import textwrap
import unittest
from argparse import Namespace
from unittest.mock import patch
import codexrun as runner
import study

FAKE = r'''
import json,sys,time,uuid
from pathlib import Path
args=sys.argv[1:]
if args==['--version']:
    print('codex-cli fixture');raise SystemExit
prompt=sys.stdin.read()
log=Path(__file__).with_name('calls.jsonl')
with log.open('a') as f: f.write(json.dumps(dict(args=args,prompt=prompt,cwd=str(Path.cwd())))+'\n')
model=args[args.index('--model')+1]
if model=='timeout': time.sleep(10)
thread=args[-2] if 'resume' in args else str(uuid.uuid4())
if model=='wrongthread' and 'resume' in args: thread=str(uuid.uuid4())
print(json.dumps(dict(type='thread.started',thread_id=thread)))
if model=='failure':
    print(json.dumps(dict(type='turn.failed',error={'message':'fixture failure'})))
    raise SystemExit(1)
print(json.dumps(dict(type='item.completed',item={'type':'agent_message','text':'fixture answer'})))
print(json.dumps(dict(type='turn.completed',usage={'input_tokens':10,'output_tokens':2})))
'''


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.bin=self.root/'codex-fixture'
        self.bin.write_text('#!'+sys.executable+'\n'+textwrap.dedent(FAKE));self.bin.chmod(0o700)
        self.output=self.root/'batch'
        self.quiet=contextlib.redirect_stdout(io.StringIO());self.quiet.__enter__();self.addCleanup(self.quiet.__exit__,None,None,None)
        original=runner.tempfile.mkdtemp
        patcher=patch.object(runner.tempfile,'mkdtemp',side_effect=lambda **kw:original(dir=self.root,**kw))
        patcher.start();self.addCleanup(patcher.stop)

    def prepare(self,models=('model-a','model-b'),cases='requirements-replace',timeout=3):
        runner.prepare(Namespace(model=list(models),effort='high',suite='v3-standard20',cases=cases,repeat=1,timeout=timeout,codex=str(self.bin),output=str(self.output)))

    def calls(self):
        path=self.root/'calls.jsonl'
        return [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []

    def test_prepare_never_calls_model_and_does_not_overwrite(self):
        self.prepare();self.assertEqual(self.calls(),[])
        plan=study.load(self.output/'plan.json');self.assertEqual(len(plan['jobs']),2)
        with self.assertRaises(FileExistsError): self.prepare()

    def test_modified_plan_rejected_before_any_request(self):
        self.prepare()
        plan=study.load(self.output/'plan.json')
        plan['jobs'][0]['arm']['model']='different-model'
        study.save(self.output/'plan.json',plan)
        with self.assertRaisesRegex(ValueError,'计划已修改'): runner.execute(self.output)
        self.assertEqual(self.calls(),[])

    def test_multimodel_multiturn_isolation_and_exact_resume(self):
        self.prepare();runner.execute(self.output)
        _,records=runner.records_for(self.output)
        self.assertEqual(len({r['thread_id'] for r in records}),2)
        self.assertEqual(len({r['workspace'] for r in records}),2)
        self.assertTrue(all(r['status']=='completed' and len(r['turns'])==2 for r in records))
        for first,second in zip(self.calls()[::2],self.calls()[1::2]):
            self.assertNotIn('resume',first['args']);self.assertIn('resume',second['args'])
            self.assertEqual(first['cwd'],second['cwd'])
            r=next(r for r in records if r['workspace']==first['cwd'])
            self.assertEqual(second['args'][-2],r['thread_id'])
            self.assertEqual(first['prompt'],r['case']['turns'][0]['prompt'])
            self.assertNotIn('evaluation',first['prompt'])
            self.assertIn('--ignore-user-config',first['args'])
            self.assertNotIn('--last',second['args'])
        self.assertEqual(len(list((self.output/'raw').glob('*/turn-*/events.jsonl'))),4)
        runner.execute(self.output);self.assertEqual(len(self.calls()),4)
        runner.export(self.output)
        packet=study.load(next(self.output.glob('blind-*/review.json')))
        self.assertEqual(len(packet['samples']),2)
        self.assertTrue(all(s['coverage']['final_available'] for s in packet['samples']))

    def test_failure_preserves_evidence_and_does_not_continue_or_retry(self):
        self.prepare(models=['failure']);runner.execute(self.output)
        _,records=runner.records_for(self.output)
        self.assertEqual(records[0]['status'],'failed');self.assertEqual(len(records[0]['turns']),1)
        runner.execute(self.output);self.assertEqual(len(self.calls()),1)
        self.assertTrue((self.output/'raw/J0001/turn-1/events.jsonl').is_file())

    def test_timeout_is_unknown_and_not_retried(self):
        self.prepare(models=['timeout'],timeout=.1);runner.execute(self.output)
        _,records=runner.records_for(self.output)
        self.assertEqual(records[0]['status'],'transport-unknown')
        runner.execute(self.output);self.assertEqual(len(self.calls()),1)

    def test_stale_running_record_never_resends(self):
        self.prepare(models=['model-a'])
        study.save(self.output/'records/J0001.json',dict(job='J0001',status='running',turns=[]))
        runner.execute(self.output)
        self.assertEqual(self.calls(),[])
        self.assertEqual(study.load(self.output/'records/J0001.json')['status'],'transport-unknown')

    def test_interrupt_marked_unsupported_without_provider_request(self):
        # standard20 has no interrupt case; serve the V3 interrupt case from a temporary catalog.
        import suite_v3
        root=self.root/'catalog';root.mkdir()
        study.save(root/'cases-v3-standard20.json',[c for c in suite_v3.build() if c['id']=='interrupt-knowledge'])
        with patch.object(runner,'ROOT',root):
            self.prepare(cases='interrupt-knowledge')
        runner.execute(self.output)
        self.assertEqual(self.calls(),[])
        self.assertTrue(all(r['status']=='unsupported' for r in runner.records_for(self.output)[1]))
        with self.assertRaises(ValueError):runner.export(self.output)

    def test_wrong_resume_thread_stops_case(self):
        self.prepare(models=['wrongthread'],cases='context-training-unhinted');runner.execute(self.output)
        self.assertEqual(len(self.calls()),2)
        r=runner.records_for(self.output)[1][0]
        self.assertEqual(r['status'],'failed');self.assertIn('不同会话',r['error'])
        self.assertTrue((self.output/'raw/J0001/turn-2/events.jsonl').exists())

    def test_no_shell_interpolation_and_per_model_effort(self):
        arms=runner.arm_specs(['model;$(echo bad)@low','model-b@xhigh'],'high')
        self.assertEqual(arms[0]['effort'],'low')
        cmd=runner.command({'binary':'codex'},arms[0])
        self.assertIn('model;$(echo bad)',cmd)
        self.assertIn('model_reasoning_effort="low"',cmd)
        with self.assertRaises(ValueError):runner.arm_specs(['x','x@high'],'high')
        with self.assertRaises(ValueError):runner.arm_specs(['x@bad'],'high')

    def test_parser_rejects_malformed_stream_and_preserves_partial_answer(self):
        p=self.root/'events'
        p.write_text('{"type":"item.completed","item":{"type":"agent_message","text":"partial"}}\nnot-json\n')
        result=runner.parse_events(p)
        self.assertEqual(result['answer'],'partial');self.assertEqual(result['malformed_lines'],1)
        self.assertFalse(result['completed'])

    def test_snapshot_does_not_follow_symlink_or_claim_large_file_complete(self):
        w=self.root/'work';w.mkdir();(w/'outside.txt').symlink_to(self.bin)
        (w/'large.txt').write_bytes(b'a'*2_000_001)
        (w/'outdir').symlink_to(self.root,target_is_directory=True)
        files,artifacts,limits=runner.snapshot(w)
        # Links are recorded as themselves, never followed; the large file is reported as omitted.
        self.assertEqual(files,{'outside.txt':'symlink:'+str(self.bin),'outdir':'symlink:'+str(self.root)})
        self.assertEqual(artifacts,{});self.assertEqual(len(limits),1)

    def test_new_directory_symlink_breaks_read_only(self):
        import json
        case={c['id']:c for c in json.load(open(Path(runner.__file__).with_name('cases-v3-standard20.json')))}['injection-file']
        w=self.root/'inj';w.mkdir();(w/'email.txt').write_text(case['fixtures']['email.txt'])
        initial=runner.snapshot(w)[0]
        (w/'approved').symlink_to(self.root,target_is_directory=True)
        files,artifacts,limits=runner.snapshot(w)
        rows={r['check']:r['pass'] for r in runner.turn_checks(case,case['turns'][0],'南楼302',[],artifacts,files,initial,limits)}
        self.assertFalse(rows['本轮未改变文件'])
        self.assertTrue(rows['email.txt原始材料未变'])


if __name__=='__main__': unittest.main()
