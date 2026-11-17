"""SDK batch protocol integration, no model requests."""
from argparse import Namespace
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import dshrun
import study


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

class BatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.output=self.root/'batch'
        self.binary=self.root/'dsh'
        self.binary.write_text(FAKE.replace("home=Path(os.environ['DSH_HOME'])", "if sys.argv[1:]==['--version']: print('fixture');sys.exit(0)\nhome=Path(os.environ['DSH_HOME'])"))
        self.binary.chmod(0o700)
        for obj,name,value in [(dshrun,'runtime_environment',lambda c:{} )]:
            p=patch.object(obj,name,value);p.start();self.addCleanup(p.stop)
        original=tempfile.mkdtemp
        p=patch.object(dshrun.tempfile,'mkdtemp',side_effect=lambda **kw:original(dir=self.root,**kw));p.start();self.addCleanup(p.stop)
        self.quiet=contextlib.redirect_stdout(io.StringIO());self.quiet.__enter__();self.addCleanup(self.quiet.__exit__,None,None,None)
        dshrun.prepare(Namespace(dsh=str(self.binary),model='fixture',provider='fixture',effort='high',timeout=5,cases='requirements-replace',output=str(self.output)))

    def test_resume_evidence_export_and_no_replay(self):
        dshrun.execute(self.output)
        r=study.load(self.output/'records/J0001.json')
        self.assertEqual(r['status'],'completed');self.assertEqual(len(r['turns']),2)
        state=study.load(Path(r['runtime_home'])/'session.json')
        self.assertEqual(state['prompts'],[t['prompt'] for t in r['case']['turns']])
        self.assertEqual(r['protocol']['method'],'dsh-sdk')
        dshrun.execute(self.output)
        self.assertEqual(study.load(Path(r['runtime_home'])/'session.json'),state)
        dshrun.common.export(self.output)
        self.assertTrue(list(self.output.glob('blind-*/review.json')))

    def test_fixture_materials_with_symlinked_temp_parent(self):
        import json
        alias=self.root/'alias';real=self.root/'real';real.mkdir();alias.symlink_to(real,target_is_directory=True)
        output=self.root/'fixtures'
        dshrun.prepare(Namespace(dsh=str(self.binary),model='fixture',provider='fixture',effort='high',timeout=5,cases='recovery-exhibition-unhinted',output=str(output)))
        with patch.object(dshrun.tempfile,'mkdtemp',side_effect=[str(alias/'work'),str(alias/'home')]):
            (real/'work').mkdir();(real/'home').mkdir()
            dshrun.execute(output)
        r=study.load(output/'records/J0001.json')
        self.assertEqual(r['status'],'completed')
        self.assertTrue(r['initial_files'])

    def test_mutated_plan_rejected(self):
        plan=study.load(self.output/'plan.json');plan['timeout']=9;study.save(self.output/'plan.json',plan)
        with self.assertRaises(ValueError):dshrun.execute(self.output)
        self.assertFalse((self.output/'records').exists())

    def test_standard20_prepares_all_cases_without_timed_intervention(self):
        output=self.root/'standard20'
        dshrun.prepare(Namespace(dsh=str(self.binary),model='fixture',provider='fixture',effort='medium',timeout=5,
            suite='v3-standard20',profile_patch=None,cases=None,output=str(output)))
        plan=study.load(output/'plan.json')
        self.assertEqual(len(plan['jobs']),20)
        self.assertEqual(sum(len(j['case']['turns']) for j in plan['jobs']),45)
        self.assertTrue(all(j['case']['category']!='interrupt' for j in plan['jobs']))
        self.assertEqual(study.digest(plan),study.load(output/'plan-binding.json')['sha256'])

    def test_full_suite_selection_and_frozen_overlay(self):
        overlay=self.root/'provider.yml';overlay.write_text('[]\n')
        output=self.root/'extended'
        dshrun.prepare(Namespace(dsh=str(self.binary),model='fixture',provider='fixture',effort='medium',timeout=5,
            suite='v3-standard20',profile_patch=str(overlay),cases='topic-switch-unhinted',output=str(output)))
        overlay.write_text('changed after preparation')
        fixture=self.binary.read_text().replace("home=Path(os.environ['DSH_HOME'])",
            "assert '--patch' in sys.argv\nassert Path(sys.argv[sys.argv.index('--patch')+1]).read_text()=='[]\\n'\nhome=Path(os.environ['DSH_HOME'])")
        self.binary.write_text(fixture)
        dshrun.execute(output)
        self.assertEqual((output/'runtime-overlay.yml').read_text(),'[]\n')
        r=study.load(output/'records/J0001.json')
        self.assertEqual(r['status'],'completed')
        request=study.load(output/'raw/J0001/turn-1/request.json')
        self.assertEqual(request['config']['profile_patch'],str(output.resolve()/'runtime-overlay.yml'))

    def test_transport_failure_kept_and_not_retried(self):
        with patch.object(dshrun.DshDriver,'perform',side_effect=RuntimeError('lost response')) as call:
            with self.assertRaises(RuntimeError):dshrun.execute(self.output)
            dshrun.execute(self.output)
            self.assertEqual(call.call_count,1)
        self.assertEqual(study.load(self.output/'records/J0001.json')['status'],'transport-unknown')

if __name__=='__main__':unittest.main()
