"""Bounded workflow keeps useful drafts and never retries unknown requests."""
import os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import boundedrun as run
import bounded_delivery as contract
import longrun

class BoundedRunnerTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  p=patch.object(run.Path,'home',return_value=self.root);p.start();self.addCleanup(p.stop)
  self.config=dict(dsh_bin='fixture',app_version='fixture',provider='deepseek-official',model='deepseek-flash',effort='low',max_tokens=4096,timeout=30,evidence_chars=3200,max_paragraph_chars=180,workflow_version=contract.VERSION)
  self.value=dict(task='保留F-1并给结论。',summary='F-1：cafe',originals=[dict(id='decision',text='核验能否提前未知；建议未批准。')],verbatim_guards=[dict(original_id='decision',quote='能否提前未知')])
  p=patch.object(run.engine,'runtime_fingerprint',return_value={'runtime':'fixture'});p.start();self.addCleanup(p.stop)
  p=patch.object(run.engine,'new_workspace',return_value=self.root/'workspace');p.start();self.addCleanup(p.stop)
 @staticmethod
 def perform(driver,home,workspace,session,prompt,resume,transcript):
  home=Path(home);value=longrun.load(home/'bd-current-input.json');phase=value['phase'];scenario=value['smoke_scenario']
  if phase=='bootstrap':
   longrun.save(home/'bd-bootstrap-proof.json',dict(sessionId='fixture',originals=[dict(id=s['id'],seq=10+i,text=s['text']) for i,s in enumerate(value['originals'])]))
   longrun.save(home/'bd-bootstrap-completed.json',dict(sessionId='fixture',provider_calls=0,bootstrap_only=True))
   return dict(answer='BOUNDED_BOOTSTRAP_ONLY_NO_PROVIDER_CALL',finish_reason='completed',events=[])
  assert resume
  if phase=='repair' and scenario=='transport-unknown':raise RuntimeError('Unknown transport outcome')
  raw='F-1：cafe（摘要）\n\n交接结论：不能确认按期。'
  finish='completed'
  if phase=='draft' and scenario=='draft-max':raw='';finish='max-tokens'
  if phase=='repair':
   raw=contract.dump(dict(replacement='交接结论：核验能否提前未知，建议未批准。',source_ids=['s10@0'],unresolved=[]))
   if scenario=='repair-max':raw='{"replacement":';finish='max-tokens'
   if scenario=='repair-invalid':raw='not-json'
  request=dict(phase=phase,mock=value['smoke'],sessionId='fixture',provider=value['provider'],model=value['model'],reasoningEffort=value['effort'],maxTokens=value['maxTokens'],tools=[],messages=[{'role':'user','content':[{'type':'text','text':prompt}]}])
  longrun.save(home/f'bd-{phase}-request-1.json',request)
  return dict(answer=raw,finish_reason=finish,events=[dict(type='turn/end',data={'reason':{'kind':finish}})])
 def execute(self,scenario):
  with patch.object(run.WebHostDriver,'perform',self.perform):return run.execute(self.value,self.root/scenario,self.config,True,scenario,with_repair=True)
 def test_no_inventory_provider_phase_and_safe_patch(self):
  r=self.execute('success');self.assertEqual(list(r['stages']),['bootstrap','draft','repair']);self.assertTrue(r['selection']['accepted'])
  self.assertIn('能否提前未知',r['selection']['answer']);self.assertTrue(r['selection']['answer'].startswith('F-1：cafe（摘要）\n\n'))
  self.assertFalse(r['semantic_verified']);self.assertIsNone(r['task_success'])
 def test_baseline_and_candidate_share_evidence_and_actual_draft_request(self):
  with patch.object(run.WebHostDriver,'perform',self.perform):
   baseline=run.execute(self.value,self.root/'baseline',self.config,True,with_repair=False)
   candidate=run.execute(self.value,self.root/'candidate',self.config,True,with_repair=True)
  self.assertEqual(baseline['evidence_packet'],candidate['evidence_packet'])
  self.assertEqual(baseline['stages']['draft']['prompt'],candidate['stages']['draft']['prompt'])
  self.assertEqual(list(baseline['stages']),['bootstrap','draft'])
  self.assertEqual(baseline['request_count'],1);self.assertEqual(candidate['request_count'],2)
  self.assertEqual(baseline['selection']['answer'],baseline['stages']['draft']['result']['answer'])
  self.assertEqual(baseline['selection']['selected_from'],'direct_draft')
  self.assertEqual(baseline['protocol'],'bounded-direct-evidence-v2')
  a=longrun.load(self.root/'baseline/homes/trial/bd-draft-request-1.json')
  b=longrun.load(self.root/'candidate/homes/trial/bd-draft-request-1.json')
  self.assertEqual(a,b);self.assertEqual(a['maxTokens'],4096);self.assertEqual(a['tools'],[])
 def test_baseline_keeps_truncation_without_repair(self):
  with patch.object(run.WebHostDriver,'perform',self.perform):
   r=run.execute(self.value,self.root/'baseline-max',self.config,True,'draft-max',with_repair=False)
  self.assertEqual(list(r['stages']),['bootstrap','draft'])
  self.assertEqual(r['selection']['selected_from'],'incomplete_draft')
  self.assertEqual(r['request_count'],1)
 def test_actual_request_configuration_drift_stops_both_arms(self):
  def drift(driver,home,workspace,session,prompt,resume,transcript):
   result=self.perform(driver,home,workspace,session,prompt,resume,transcript)
   p=Path(home)/'bd-draft-request-1.json'
   if p.exists():
    request=longrun.load(p);request['maxTokens']=256000;longrun.save(p,request)
   return result
  with patch.object(run.WebHostDriver,'perform',drift):
   for arm in (True,False):
    path=self.root/str(arm)
    with self.assertRaisesRegex(ValueError,'configuration/request changed'):
     run.execute(self.value,path,self.config,True,with_repair=arm)
    r=longrun.load(path/'run.json');self.assertEqual(r['status'],'attention')
    self.assertNotIn('repair',r['stages'])
 def test_truncated_and_invalid_patch_keep_usable_draft(self):
  for scenario in ('repair-max','repair-invalid'):
   r=self.execute(scenario);self.assertEqual(r['selection']['answer'],r['stages']['draft']['result']['answer']);self.assertFalse(r['selection']['accepted']);self.assertEqual(r['status'],'completed')
 def test_truncated_draft_does_not_trigger_costly_repair(self):
  r=self.execute('draft-max');self.assertEqual(list(r['stages']),['bootstrap','draft']);self.assertEqual(r['selection']['selected_from'],'incomplete_draft');self.assertIsNone(r['task_success'])
 def test_unknown_repair_stops_without_retry_and_retains_draft(self):
  with self.assertRaisesRegex(RuntimeError,'Unknown transport'):self.execute('transport-unknown')
  r=longrun.load(self.root/'transport-unknown/run.json');self.assertEqual(r['status'],'attention');self.assertEqual(r['pending'],'repair');self.assertIn('draft',r['stages'])
  with self.assertRaisesRegex(ValueError,'new output'):self.execute('transport-unknown')
 def test_missing_key_delegates_authentication_to_runtime(self):
  with patch.dict(os.environ,{},clear=True),patch.object(run.WebHostDriver,'perform',self.perform):
   r=run.execute(self.value,self.root/'runtime-auth',self.config,with_repair=True)
  self.assertEqual(r['status'],'completed');self.assertTrue(r['selection']['accepted'])
  self.assertEqual(list(r['stages']),['bootstrap','draft','repair'])
 def test_runtime_auth_failure_is_saved_without_retry(self):
  with patch.dict(os.environ,{},clear=True),patch.object(run.WebHostDriver,'perform',side_effect=RuntimeError('Provider authentication unavailable')) as perform:
   with self.assertRaisesRegex(RuntimeError,'authentication unavailable'):
    run.execute(self.value,self.root/'runtime-auth-error',self.config)
  self.assertEqual(perform.call_count,1)
  r=longrun.load(self.root/'runtime-auth-error/run.json')
  self.assertEqual(r['status'],'attention');self.assertEqual(r['pending'],'bootstrap')
  self.assertIn('authentication unavailable',r['problem'])
 def test_saved_key_is_scoped_and_not_copied_to_config(self):
  home=self.root/'desktop';home.mkdir();source=home/'.credentials.yaml'
  source.write_text('version: 1\nrefs:\n  DEEPSEEK_API_KEY: sk-fixture\n  OTHER_KEY: hidden\nrecords: {}\n');source.chmod(0o600)
  config={**self.config,'provider':'deepseek-official'}
  with patch.dict(os.environ,{'DSH_HOME':str(home)},clear=True):
   self.assertEqual(run.runtime_environment(config),{'DEEPSEEK_API_KEY':'sk-fixture'})
   self.assertEqual(run.runtime_environment(config,True),{})
   self.assertEqual(run.runtime_environment({**config,'provider':'deepseek-account'}),{})
   with patch.dict(os.environ,{'DEEPSEEK_API_KEY':'existing'}):self.assertEqual(run.runtime_environment(config),{})
  self.assertNotIn('sk-fixture',str(config))
 def test_saved_key_rejects_unsafe_permissions_and_scalars(self):
  home=self.root/'desktop';home.mkdir();source=home/'.credentials.yaml'
  config={**self.config,'provider':'deepseek-official'}
  source.write_text('refs:\n  DEEPSEEK_API_KEY: sk-fixture\n');source.chmod(0o644)
  with patch.dict(os.environ,{'DSH_HOME':str(home)},clear=True):
   with self.assertRaisesRegex(ValueError,'owner-only'):run.runtime_environment(config)
   source.chmod(0o600);source.write_text('refs:\n  DEEPSEEK_API_KEY: |\n    secret\n')
   with self.assertRaisesRegex(ValueError,'Unsupported'):run.runtime_environment(config)
 def test_default_is_one_request_and_writes_exact_delivery(self):
  with patch.object(run.WebHostDriver,'perform',self.perform):
   r=run.execute(self.value,self.root/'default',self.config,True)
  self.assertEqual(r['mode'],'direct');self.assertFalse(r['repair_enabled'])
  self.assertEqual(list(r['stages']),['bootstrap','draft']);self.assertEqual(r['request_count'],1)
  self.assertEqual((self.root/'default/answer.md').read_text(),r['selection']['answer'])
  self.assertEqual((self.root/'default/draft.md').read_text(),r['selection']['answer'])
 def test_cli_repair_is_explicit_and_baseline_cannot_enable_it(self):
  import io,contextlib
  import boundedbaseline
  inp=self.root/'input.json';longrun.save(inp,self.value)
  with patch.object(run.WebHostDriver,'perform',self.perform):
   for enabled in (False,True):
    output=self.root/('cli-repair' if enabled else 'cli-direct')
    args=['run','--input',str(inp),'--output',str(output)]
    if enabled:args.append('--repair')
    with contextlib.redirect_stdout(io.StringIO()):run.main(args)
    r=longrun.load(output/'run.json')
    self.assertEqual(r['repair_enabled'],enabled);self.assertEqual(r['request_count'],2 if enabled else 1)
  with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):
   boundedbaseline.main(['--input',str(inp),'--output',str(self.root/'bad'),'--repair'])
 def test_input_cannot_include_scoring_keys(self):
  with self.assertRaisesRegex(ValueError,'no scoring keys'):run.input_data({**self.value,'expected':{'state':'gold'}})
 def test_usage_is_request_bound_and_not_double_counted(self):
  request=dict(sessionId='fixture',mock=False)
  result=dict(finish_reason='completed')
  p=self.root/'bd-draft-usage-1.json'
  self.assertFalse(run.request_usage(self.root,'draft',request,result)['complete'])
  raw=dict(sessionId='fixture',phase='draft',request=1,mock=False,finish={'kind':'completed'},usage_chunks=[dict(inputTokens=10,outputTokens=20,totalTokens=30)])
  longrun.save(p,raw)
  self.assertEqual(run.request_usage(self.root,'draft',request,result)['totals']['totalTokens'],30)
  longrun.save(p,{**raw,'finish':{'kind':'stop'}})
  self.assertTrue(run.request_usage(self.root,'draft',request,result)['complete'])
  longrun.save(p,{**raw,'usage_chunks':raw['usage_chunks']*2})
  self.assertFalse(run.request_usage(self.root,'draft',request,result)['complete'])
  longrun.save(p,{**raw,'sessionId':'wrong'})
  with self.assertRaisesRegex(ValueError,'identity changed'):run.request_usage(self.root,'draft',request,result)

if __name__=='__main__':unittest.main()
