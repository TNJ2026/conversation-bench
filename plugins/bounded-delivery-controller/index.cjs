'use strict';
// Operator-side experiment controller, not a retrieval-plugin optimization.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const READY = 'BENCH_BOUNDED_CONTROLLER_READY 1';
const TOOLS = ['current_history_read', 'current_history_search'];
const text = m => (m.content || []).filter(c => c.type === 'text').map(c => c.text).join('\n');
function apply(ctx) {
  const home = process.env.DSH_HOME;
  const input = JSON.parse(fs.readFileSync(path.join(home, 'bd-current-input.json'), 'utf8'));
  const allowed = [];
  const phase = input.phase;
  if (!['bootstrap','draft','repair','compress'].includes(phase)) throw new Error('Invalid audit phase');
  let sessionId, requests = 0;
  const save = (name, value) => fs.writeFileSync(path.join(home, name), JSON.stringify(value, null, 2)+'\n');
  ctx.on('agent/request', async (_position, next) => ({...await next(), maxTokens: input.maxTokens}));
  ctx.on('agent/created', ({agent}) => {
    if (sessionId) throw new Error('BOUNDED permits one fresh agent only');
    sessionId = agent.session.id;
    agent.ctx.tools.restrict({allow: allowed});
    agent.ctx.systemPrompt.suppressRuntimeContext();
    agent.ctx.systemPrompt.context({name:'working-directory:current',order:100,text:''});
    agent.ctx.on('agent/pre-step', async (_position, next) => {
      const decision = await next();
      if (decision.kind !== 'enter') return decision;
      return {...decision, messages: decision.messages.filter(m =>
        !['runtime-context', 'time-context'].includes(m.source?.kind))};
    }, {prepend: true});
    if (!input.initial) {
      const proof = JSON.parse(fs.readFileSync(path.join(home,'bd-bootstrap-proof.json'),'utf8'));
      if (proof.sessionId !== sessionId) throw new Error('Audit resume changed session identity');
      return;
    }
    if (fs.existsSync(path.join(home,'bd-bootstrap-proof.json'))) throw new Error('Audit bootstrap cannot run twice');
    let admitted = false;
    ctx.on('session/event', (session,event) => {
      if (session.id !== sessionId) return;
      if (!admitted && event.type === 'system/message') {
        admitted = true;
        queueMicrotask(() => {
        const originals = input.originals.map((turn,i) => {
          const e=session.append('user/message',{id:`bd-original-${i}`,role:'user',source:{kind:'user'},
            content:[{type:'text',text:turn.text}]},{surfaceOp:'append'});
          return {id:turn.id,seq:e.seq,text:turn.text};
        });
        if (!originals.length) throw new Error('BOUNDED needs original history');
        session.append('user/message',{id:crypto.randomUUID(),role:'user',source:{kind:'controlled-summary'},
          content:[{type:'text',text:input.summary}]},
          {surfaceOp:{op:'replace',startSeq:originals[0].seq,endSeq:originals.at(-1).seq},sourceEventSeqs:originals.map(e=>e.seq)});
        save('bd-bootstrap-proof.json',{sessionId,originals,summary:input.summary,method:'synthetic-surface-replacement',registeredAllowed:allowed});
        });
      }
      if (event.type === 'turn/end' && event.data.reason?.kind === 'completed') {
        queueMicrotask(() => {
        const nodes=session.surface.nodes.filter(seq=>session.eventAt(seq).type!=='system/message');
        if (!admitted || !nodes.length) throw new Error('Bootstrap did not admit original history');
        session.append('user/message',{id:crypto.randomUUID(),role:'user',source:{kind:'controlled-summary'},
          content:[{type:'text',text:input.summary}]},
          {surfaceOp:{op:'replace',startSeq:nodes[0],endSeq:nodes.at(-1)},sourceEventSeqs:nodes});
        save('bd-bootstrap-completed.json',{sessionId,provider_calls:0,bootstrap_only:true});
        });
      }
    });
  });
  ctx.on('llm/stream', (options, next) => {
    if (!sessionId || options.sessionId !== sessionId) throw new Error('BOUNDED forbids background/non-target LLM calls');
    if (options.messages.some(m => m.source?.kind === 'dsh-session-title-llm')) {
      // Titles can include original transcript text. Suppress their provider calls in every arm.
      save('bd-title-suppressed.json', {suppressed: true});
      return (async function* () { yield {type:'finish',reason:{kind:'completed'}}; })();
    }
    if (options.provider !== input.provider || options.model !== input.model || options.reasoningEffort !== input.effort)
      throw new Error('BOUNDED model selection mismatch');
    if (options.maxTokens !== input.maxTokens) throw new Error('BOUNDED output limit mismatch');
    const names = (options.tools || []).map(t => t.name).sort();
    if (JSON.stringify(names) !== JSON.stringify(allowed)) throw new Error('BOUNDED tool allowlist mismatch: '+names.join(','));
    if (phase === 'bootstrap') return (async function* () {
      yield {type:'text-delta',index:0,text:'BOUNDED_BOOTSTRAP_ONLY_NO_PROVIDER_CALL'};
      yield {type:'finish',reason:{kind:'completed'}};
    })();
    const messages = options.messages;
    save(`bd-${phase}-last-observed-input.json`, {messages, tools: options.tools || []});
    if (requests === 0 && ['draft'].includes(phase)) {
      const visibleUsers = messages.filter(m => m.role === 'user' && m.source?.kind !== 'runtime-context');
      if (visibleUsers.length !== 2 || text(visibleUsers[0]) !== input.summary || text(visibleUsers[1]) !== input.prompt)
        throw new Error('BOUNDED initial visible messages are not exactly summary + prompt');
      if (options.toolHistory && JSON.stringify(options.toolHistory).includes('bd-original-'))
        throw new Error('BOUNDED old history leaked through tool history');
    }
    if (requests >= 1) throw new Error('Bounded phase permits one model request only');
    requests++;
    save(`bd-${phase}-request-${requests}.json`, {
      sessionId, provider: options.provider, model: options.model,
      reasoningEffort: options.reasoningEffort, maxTokens: options.maxTokens,
      messages, tools: options.tools || [], toolHistory: options.toolHistory || null,
      phase, mock: !!input.smoke
    });
    const captureUsage = async function* (source) {
      const record = {sessionId, phase, request: requests, mock: !!input.smoke,
        usage_chunks: [], finish: null, stream_completed: false};
      const persist = () => save(`bd-${phase}-usage-${requests}.json`, record);
      persist();
      try {
        for await (const chunk of source) {
          if (chunk.type === 'usage') { record.usage_chunks.push(chunk.usage); persist(); }
          if (chunk.type === 'finish') { record.finish = chunk.reason; persist(); }
          yield chunk;
        }
        record.stream_completed = true;
      } finally { persist(); }
    };
    if (!input.smoke) return captureUsage(next());
    // One deterministic fixture; never calls the provider adapter.
    return captureUsage((async function* () {
      yield {type:'usage',usage:{inputTokens:100,outputTokens:20,totalTokens:120}};
      if (phase==='repair' && input.smoke_scenario==='repair-max') {
        yield {type:'text-delta',index:0,text:'{"replacement":'};
        yield {type:'finish',reason:{kind:'max-tokens'}};return;
      }
      const response=phase==='compress'?'核验能否提前未知；建议未批准。':phase==='draft'?'F-1：cafe（摘要）\n\n交接结论：不能确认按期。':
        input.smoke_scenario==='repair-invalid'?'not-json':JSON.stringify({replacement:'交接结论：核验能否提前未知，建议未批准。',source_ids:input.evidence.packet.items.map(i=>i.id),unresolved:[]});
      yield {type:'text-delta',index:0,text:response};yield {type:'finish',reason:{kind:'completed'}};
    })());
  });
  console.info(READY);
}
module.exports = {name:'bench-bd-controller',inject:['tools','agents'],apply,READY};
