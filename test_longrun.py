"""Keyless end-to-end tests through a real subprocess speaking DSH JSON-RPC."""
import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import longrun
from dsh_driver import DshDriver, DriverError

# Synthetic protocol fixture: never calls a model or produces benchmark scores.
FAKE = r'''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
home=Path(os.environ['DSH_HOME']); file=home/'session.json'
state=json.loads(file.read_text()) if file.exists() else {'seq':0,'seeds':{},'prompts':[],'sources':[]}
def send(x): print(json.dumps(dict(jsonrpc='2.0',**x),ensure_ascii=False),flush=True)
def event(kind,data,**kw):
 state['seq']+=1
 send({'method':'session.event','params':{'sessionId':sid,'event':dict(seq=state['seq'],type=kind,data=data,**kw)}})
 return state['seq']
for line in sys.stdin:
 q=json.loads(line); method=q.get('method'); rid=q.get('id'); p=q.get('params',{})
 if method=='initialize':
  send({'id':rid,'result':{'serverInfo':{'name':'deepseek-harness-sdk-runtime','version':'test-only'}}})
 elif method=='session/resume':
  if not file.exists(): send({'id':rid,'error':{'code':-1,'message':'missing history'}})
  else: send({'id':rid,'result':{}})
 elif method=='shutdown':
  send({'id':rid,'result':{}}); break
 elif method=='session/query':
  sid=p['sessionId']; text=p['contentBlocks'][0]['text']
  if text=='/compact':
   event('command/run',{'commandId':'compact-1'})
   event('compaction/start',{'compactionId':'c1'})
   seq=event('compaction/summary',{'compactionId':'c1','summary':'Synthetic summary for transport testing only.','shadowedSeqs':state['sources']})
   event('user/message',{'content':[{'type':'text','text':'Synthetic summary'}]},surfaceOp={'op':'replace','startSeq':0,'endSeq':seq-1},sourceEventSeqs=[seq])
   event('compaction/end',{'compactionId':'c1'})
   event('command/done',{'commandId':'compact-1'})
   # Exercise completion arriving before the synchronous command RPC response.
   send({'method':'session.query.completed','params':{'sessionId':sid,'commandId':'compact-1','finalResponse':'Compacted','finishReason':'completed'}})
   send({'id':rid,'result':{'kind':'command','execution':{'commandId':'compact-1'}}})
  else:
   mid='m'+str(state['seq'])
   send({'id':rid,'result':{'kind':'prompt','messageId':mid}})
   event('agent/inbox/spliced',{'inserted':[{'id':mid}]})
   event('turn/start',{})
   seq=event('user/message',{'content':[{'type':'text','text':text}]})
   state['sources'].append(seq)
   if len(state['prompts'])<3: state['seeds'][str(len(state['prompts']))]=seq
   state['prompts'].append(text)
   event('assistant/message',{'message':{'content':[{'type':'text','text':'Synthetic response; not an evaluated model answer.'}]}})
   event('turn/end',{'reason':{'kind':'completed'}})
   send({'method':'session.status','params':{'sessionId':sid,'status':'idle'}})
  file.write_text(json.dumps(state,ensure_ascii=False))
 else: send({'id':rid,'error':{'code':-32601,'message':'unsupported'}})
'''


class LongRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fake = self.root/'fake-dsh'; self.fake.write_text(FAKE); self.fake.chmod(0o755)
        self.path = self.root/'run'/'run.json'
        self.output = contextlib.redirect_stdout(io.StringIO()); self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)
        # Keep even the generated workspace inside this temporary project.
        fake_module = self.root/'project'/'longrun.py'; fake_module.parent.mkdir()
        with patch.object(longrun,'__file__',str(fake_module)):
            longrun.create(argparse.Namespace(output=str(self.path),model='fixture-model',provider='fixture-provider',
                         effort='low',dsh_bin=str(self.fake),load_batches=1,seed=42,timeout=5))

    def state(self): return longrun.load(self.path)

    def driver(self, mutate):
        native = DshDriver(self.state()['config'])
        class Mutated:
            def perform(self, *args):
                result = native.perform(*args)
                mutate(args[3],result)
                return result
        return Mutated()

    def finish_grades(self):
        longrun.grade(self.path)
        path = self.path.parent/'scores.json'; scores = longrun.load(path)
        for check in scores['protocol'].values():
            check.update({'pass':True,'evidence':'Synthetic protocol test, not an actual benchmark.'})
        for conclusion in scores['conclusions'].values():
            conclusion['evidence']='Synthetic response contains no identifiable final conclusion.'
        for stages in scores['grades'].values():
            for anchors in stages.values():
                for item in anchors.values(): item.update({'grade':'unknown','evidence':'Synthetic response provides no anchor answer.'})
                key = 'nonce' if 'nonce' in anchors else 'f1' if 'f1' in anchors else next(iter(anchors))
                anchors[key]['omitted'] = True
        longrun.save(path,scores)
        return path,scores

    def test_automatic_triplet_and_private_prompt_boundary(self):
        longrun.run(self.path)
        state = self.state()
        self.assertEqual(state['status'],'completed')
        self.assertEqual(len(state['results']),11)
        self.assertEqual(len(state['checkpoint']['seed_sequences']),3)
        self.assertIn('compaction_proof',state['results']['B/compact'])
        for branch in longrun.BRANCHES:
            history = longrun.load(self.path.parent/'homes'/branch/'session.json')['prompts']
            self.assertEqual(history[:4],[t['prompt'] for t in state['prefix']])
            self.assertEqual(history[4:],[t['prompt'] for t in state['case']['probes']])
            self.assertFalse(any('required_points' in p or 'record_template' in p for p in history))
        with self.assertRaisesRegex(ValueError,'closed'):
            longrun.run(self.path)
        longrun.report(self.path)
        report = longrun.load(self.path.parent/'report.json')
        self.assertIsNone(report['metrics']); self.assertIsNone(report['protocol_valid'])

    def test_safe_pause_extend_and_resume_without_duplicate_turns(self):
        longrun.run(self.path,max_actions=3)
        self.assertIsNone(self.state()['checkpoint'])
        longrun.extend(self.path,2)
        self.assertEqual([t['id'] for t in self.state()['prefix']][-3:],['load-01','load-02','load-03'])
        longrun.run(self.path)
        history = longrun.load(self.path.parent/'homes'/'prefix'/'session.json')['prompts']
        self.assertEqual(len(history),6)
        self.assertEqual(len(self.state()['results']),13)
        with self.assertRaises(ValueError): longrun.extend(self.path,1)

    def create_detail(self, batches=12):
        import longcase
        path=self.root/'detail-run'/'plan.json'
        args=argparse.Namespace(output=str(path),model='fixture-model',provider='fixture-provider',effort='low',
                                dsh_bin=str(self.fake),load_batches=batches,seed=42,timeout=5,casefile=str(longcase.DETAIL_CASE))
        with patch.object(longrun,'__file__',str(self.root/'project'/'longrun.py')):
            longrun.create(args)
        self.path=path

    def test_transfer_case_runs_and_scores_all_thirteen_conditions(self):
        import transfercase
        path=self.root/'transfer-run'/'plan.json'
        args=argparse.Namespace(output=str(path),model='fixture-model',provider='fixture-provider',effort='low',
            dsh_bin=str(self.fake),load_batches=12,seed=42,timeout=5,
            casefile=str(transfercase.CASE_DIR/'transfer-v9'/'case-1.json'))
        with patch.object(longrun,'__file__',str(self.root/'project'/'longrun.py')):
            longrun.create(args)
        self.path=path
        longrun.run(self.path)
        state=self.state()
        self.assertEqual(state['status'],'completed')
        self.assertEqual(len(state['results']),22)
        self.assertEqual(len(state['checkpoint']['anchor_sequences']),10)
        self.assertTrue(all(state['results']['B/compact']['compaction_proof']['anchor_coverage'].values()))
        scores,_=self.finish_grades();longrun.grade(self.path,scores)
        self.assertEqual(self.state()['metrics']['B']['recovery']['unknown'],13)
        self.assertFalse(self.state()['metrics']['B']['recovery']['full_delivery_success'])
        longrun.report(self.path)
        self.assertIn('Acceptance passed / 13',(self.path.parent/'report.html').read_text())

    def test_task_completion_requires_every_condition_and_valid_protocol(self):
        import taskcase
        state=self.state()
        state['case']=taskcase.build_fixed_task_case()
        state['case_hash']=longrun.digest(state['case'])
        # Keep this protocol fixture small; the saved case separately enforces 12 batches.
        state['case']['minimum_load_batches']=1
        state['case_hash']=longrun.digest(state['case'])
        state['prefix']=state['case']['seed_turns']+state['case']['pressure_turns'][:1]
        longrun.save(self.path,state)
        longrun.run(self.path)
        state=self.state()
        for key,value in state['results'].items():
            if key.endswith(('/recall','/recovery')):
                value['answer']+='\n**QL-E017：回执码 '+taskcase.RECEIPT+'**'
        longrun.save(self.path,state)
        path,scores=self.finish_grades()
        for stages in scores['grades'].values():
            for anchors in stages.values():
                for mark in anchors.values():
                    mark.update(grade='correct',omitted=False,evidence='Synthetic acceptance for runner testing only.')
        scores['grades']['B']['recall']['budget']['grade']='unknown'
        longrun.save(path,scores);longrun.grade(self.path,path)
        m=self.state()['metrics']
        self.assertEqual(m['B']['recall']['retention'],9)
        self.assertFalse(m['B']['recall']['full_delivery_success'])
        self.assertEqual(m['B']['recall']['tasks_completed'],2)
        self.assertTrue(m['B']['recovery']['full_delivery_success'])
        longrun.report(self.path)
        report=longrun.load(self.path.parent/'report.json')
        self.assertAlmostEqual(report['differences']['recall']['task_success_rate_B_minus_A'],-1/3)
        self.assertIn('B/compact',report['action_elapsed_seconds'])
        self.assertIn('Full delivery success',(self.path.parent/'report.html').read_text())
        scores['protocol']['unexposed'].update({'pass':False,'evidence':'Synthetic leak invalidates this fixture trial.'})
        longrun.save(path,scores);longrun.grade(self.path,path)
        self.assertIsNone(self.state()['metrics']['B']['recovery']['full_delivery_success'])
        self.assertIsNone(self.state()['metrics']['B']['recovery']['task_success_rate'])

    def test_insufficient_detail_load_is_rejected_without_creating_a_run(self):
        with self.assertRaisesRegex(ValueError,'more load'):
            self.create_detail(batches=1)
        self.assertFalse((self.root/'detail-run').exists())

    def test_detail_run_validates_admission_coverage_and_three_grade_rubric(self):
        self.create_detail();longrun.run(self.path)
        state=self.state()
        self.assertEqual(len(state['checkpoint']['anchor_sequences']),10)
        self.assertTrue(all(state['results']['B/compact']['compaction_proof']['anchor_coverage'].values()))
        path,scores=self.finish_grades()
        mark=scores['grades']['A']['recall']['f1']
        mark.update(grade='partial',omitted=False);longrun.save(path,scores)
        with self.assertRaisesRegex(ValueError,'valid category'):
            longrun.grade(self.path,path)
        mark['grade']='correct';longrun.save(path,scores)
        with self.assertRaisesRegex(ValueError,'ticket/receipt pair'):
            longrun.grade(self.path,path)
        mark['grade']='unknown';longrun.save(path,scores);longrun.grade(self.path,path)
        self.assertEqual(self.state()['metrics']['B']['recall']['partial'],0)
        self.assertEqual(self.state()['metrics']['B']['recall']['retention'],0)

    def test_detail_probes_require_a_compacted_source_not_only_compacted_seeds(self):
        self.create_detail()
        def mutate(prompt,result):
            if prompt=='/compact':
                for event in result['events']:
                    if event['type']=='compaction/summary':
                        event['data']['shadowedSeqs']=list(self.state()['seed_sequences'].values())
        with self.assertRaisesRegex(ValueError,'No probed source'):
            longrun.run(self.path,driver=self.driver(mutate))
        self.assertEqual(self.state()['status'],'invalid')

    def test_summary_without_history_replacement_is_invalid(self):
        def mutate(prompt,result):
            if prompt=='/compact': result['events']=[e for e in result['events'] if not isinstance(e.get('surfaceOp'),dict)]
        with self.assertRaisesRegex(ValueError,'replacement'):
            longrun.run(self.path,driver=self.driver(mutate))
        self.assertEqual(self.state()['status'],'invalid')
        self.assertIn('B/compact',self.state()['results'])
        self.assertIsNone(self.state()['pending'])
        self.assertFalse(any(k.endswith('/recall') for k in self.state()['results']))

    def test_compaction_summary_accepts_text_content_blocks(self):
        # DSH 0.2.x returns the summary as text content blocks instead of a string.
        def mutate(prompt, result):
            if prompt=='/compact':
                for event in result['events']:
                    if event['type']=='compaction/summary':
                        event['data']['summary']=[{'type':'text','text':event['data']['summary']}]
        longrun.run(self.path,driver=self.driver(mutate))
        self.assertEqual(self.state()['status'],'completed')
        proof = self.state()['results']['B/compact']['compaction_proof']
        self.assertIn('Synthetic summary',proof['summary'])

    def test_compaction_must_cover_every_seed_message(self):
        def mutate(prompt,result):
            if prompt=='/compact':
                for event in result['events']:
                    if event['type']=='compaction/summary': event['data']['shadowedSeqs'].remove(next(iter(self.state()['seed_sequences'].values())))
        with self.assertRaisesRegex(ValueError,'three seed'):
            longrun.run(self.path,driver=self.driver(mutate))
        self.assertEqual(self.state()['status'],'invalid')

    def test_compaction_before_checkpoint_cannot_be_an_uncompacted_control(self):
        def mutate(prompt,result):
            result['events'].append({'type':'compaction/summary','data':{'summary':'Unexpected compaction'}})
        with self.assertRaisesRegex(ValueError,'automatic compaction'):
            longrun.run(self.path,driver=self.driver(mutate))
        self.assertIsNone(self.state()['checkpoint'])
        self.assertEqual(self.state()['status'],'invalid')

    def test_workspace_write_stops_before_other_branches_are_exposed(self):
        def mutate(prompt,result):
            (Path(self.state()['workspace'])/'unrequested.txt').write_text('changed')
        with self.assertRaisesRegex(ValueError,'contaminated'):
            longrun.run(self.path,driver=self.driver(mutate))
        self.assertEqual(self.state()['status'],'invalid')
        self.assertEqual(len(self.state()['results']),1)

    def test_lock_and_changed_snapshot_prevent_target_calls(self):
        with longrun.locked(self.path):
            with self.assertRaisesRegex(ValueError,'lock exists'):
                longrun.run(self.path)
        state=self.state();state['case']['title']='changed';longrun.save(self.path,state)
        with self.assertRaisesRegex(ValueError,'snapshot changed'):
            longrun.run(self.path)
        self.assertEqual(self.state()['results'],{})

    def test_automatic_compaction_or_recall_tools_invalidates_protocol(self):
        def mutate(prompt,result):
            if prompt.startswith('先做一次闭卷'):
                result['events'].append({'type':'tool/call','data':{'name':'read'}})
        with self.assertRaisesRegex(ValueError,'invoked tools'):
            longrun.run(self.path,driver=self.driver(mutate))
        self.assertEqual(self.state()['status'],'invalid')

    def test_timeout_keeps_uncertain_action_and_forbids_resend(self):
        self.fake.write_text('#!/usr/bin/env python3\nimport time\ntime.sleep(10)\n')
        state=self.state();state['config']['timeout']=0.1;longrun.save(self.path,state)
        with self.assertRaisesRegex(DriverError,'timed out'):
            longrun.run(self.path)
        self.assertEqual(self.state()['status'],'attention')
        self.assertEqual(self.state()['pending']['action'],'prefix/seed-1')
        with self.assertRaisesRegex(ValueError,'resend'):
            longrun.run(self.path)
        self.assertTrue((self.path.parent/'raw'/'prefix-seed-1.jsonl').exists())

    def test_grades_validate_omissions_exact_answers_sources_and_snapshot(self):
        longrun.run(self.path)
        path,scores=self.finish_grades()
        marks=scores['grades']['A']['recall']
        marks['nonce']['grade']='wrong';longrun.save(path,scores)
        with self.assertRaisesRegex(ValueError,'Omission'): longrun.grade(self.path,path)
        marks['nonce']['grade']='correct';marks['nonce']['omitted']=False;longrun.save(path,scores)
        with self.assertRaisesRegex(ValueError,'exact-text pass'): longrun.grade(self.path,path)
        marks['nonce']['grade']='unknown'; marks['budget']['retrieved']=True;longrun.save(path,scores)
        with self.assertRaisesRegex(ValueError,'retrieval'): longrun.grade(self.path,path)
        marks['budget']['retrieved']=False;longrun.save(path,scores)
        original=marks['authority'];marks['authority']=None;longrun.save(path,scores)
        with self.assertRaisesRegex(ValueError,'object'): longrun.grade(self.path,path)
        marks['authority']=original;longrun.save(path,scores)
        scores['conclusions']['A']['text']='Invented conclusion not present in answer';longrun.save(path,scores)
        with self.assertRaisesRegex(ValueError,'exact, non-empty span'): longrun.grade(self.path,path)
        scores['conclusions']['A']['text']=None;longrun.save(path,scores)
        longrun.grade(self.path,path)
        self.assertEqual(self.state()['metrics']['B']['recall']['retention'],0)
        self.assertEqual(self.state()['metrics']['B']['recall']['errors'],0)
        self.assertEqual(self.state()['metrics']['B']['recall']['omitted'],1)
        longrun.report(self.path)
        self.assertEqual(longrun.load(self.path.parent/'report.json')['differences']['recall']['B_minus_A'],0)
        scores['answers_sha256']='wrong snapshot';longrun.save(path,scores)
        with self.assertRaisesRegex(ValueError,'different run'): longrun.grade(self.path,path)

    def test_failed_manual_protocol_review_is_not_a_valid_comparison(self):
        longrun.run(self.path)
        path,scores=self.finish_grades()
        scores['protocol']['unexposed']['pass']=False;longrun.save(path,scores)
        longrun.grade(self.path,path);longrun.report(self.path)
        report=longrun.load(self.path.parent/'report.json')
        self.assertFalse(report['protocol_valid'])
        self.assertIsNone(report['differences']['recall']['outside_repeat_variation'])


if __name__=='__main__': unittest.main()
