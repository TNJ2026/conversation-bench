const {test} = require('node:test');
const assert = require('node:assert/strict');
const plugin = require('./index.cjs');

function user(seq,text,extra={}) {
  return {seq,type:'user/message',surfaceOp:'append',time:seq,
    data:{role:'user',source:{kind:'user'},content:[{type:'text',text}]},...extra};
}
function setup(events, override={}) {
  const tools = new Map(), calls=[];
  const ctx={tools:{register:t => tools.set(t.name,t)},
    agents:{turnBoundaryOf:() => ({lastStepStartSeq:100})},
    sessionQuery:{readSession:async id => {calls.push(id);return {session:{id},events};}},...override};
  plugin.apply(ctx);
  const exec={agent:{session:{id:'current-only'}},signal:new AbortController().signal};
  const run=async (name,args) => JSON.parse(await tools.get(name).execute(args,exec));
  return {tools,calls,exec,run};
}

test('search only original user events in the calling session, including shadowed originals',async () => {
  const s=setup([user(1,'ticket receipt abc'),user(2,'ticket summary',{surfaceOp:{op:'replace'},sourceEventSeqs:[1]}),
    user(3,'ticket runtime',{data:{role:'user',source:{kind:'runtime-context'},content:[{type:'text',text:'ticket'}]}}),
    user(4,'ticket assistant',{type:'assistant/message'}),user(100,'ticket future')]);
  const result=await s.run('current_history_search',{query:'ticket'});
  assert.deepEqual(result.hits.map(x => x.seq),[1]);
  assert.deepEqual(s.calls,['current-only']);
  assert.equal(result.session_id,'current-only');
  await assert.rejects(s.run('current_history_search',{query:'ticket',session_id:'other'}));
  await assert.rejects(s.run('current_history_read',{seq:1,session_id:'other'}));
});

test('read paginates exact source and rejects nonuser, current step and unknown events',async () => {
  const text='x'.repeat(13000)+' RECEIPT';
  const s=setup([user(1,text),user(2,'summary',{surfaceOp:{op:'replace'}}),user(100,'future')]);
  const first=await s.run('current_history_read',{seq:1});
  const second=await s.run('current_history_read',{seq:1,offset:first.next_offset});
  assert.equal(first.text+second.text,text);
  assert.equal(first.next_offset,12000);assert.equal(second.next_offset,null);
  for(const seq of [2,100,999]) await assert.rejects(s.run('current_history_read',{seq}));
  await assert.rejects(s.run('current_history_read',{seq:1,offset:999999}));
});

test('limits, snippets, no matches, input validation and cancellation',async () => {
  const s=setup([user(1,'a'.repeat(1000)+'needle'+'b'.repeat(1000)),user(2,'needle')]);
  const result=await s.run('current_history_search',{query:'needle',limit:1});
  assert.equal(result.has_more,true);assert.equal(result.hits[0].text.length,600);
  assert.equal(result.hits[0].truncated,true);
  assert.deepEqual((await s.run('current_history_search',{query:'absent'})).hits,[]);
  for(const args of [{query:''},{query:'x',limit:0},{query:'x',limit:11},{query:'x',path:'/etc/passwd'}])
    await assert.rejects(s.run('current_history_search',args));
  const aborted=new AbortController();aborted.abort();s.exec.signal=aborted.signal;
  await assert.rejects(s.run('current_history_search',{query:'needle'}));
});

test('fails closed for mismatched source identity, missing caller and boundary',async () => {
  const s=setup([],{sessionQuery:{readSession:async () => ({session:{id:'other'},events:[user(1,'secret')]})}});
  await assert.rejects(s.run('current_history_read',{seq:1}));
  delete s.exec.agent;
  await assert.rejects(s.run('current_history_search',{query:'secret'}));
  const missing=setup([],{agents:{turnBoundaryOf:() => ({})}});
  await assert.rejects(missing.run('current_history_search',{query:'secret'}));
});
