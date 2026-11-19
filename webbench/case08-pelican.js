async page => {
  const {base, output, candidateFiles} = __BENCH_CONFIG__;
  const url=base+'/index.svg';
  const checks=[];
  const outgoing=[];
  const markers=['crank','pedal-a','pedal-b','foot-a','foot-b','wheel-front-center','wheel-rear-center','wheel-front-mark','wheel-rear-mark','seat','hip'];
  const id=n=>page.getByTestId('pelican-'+n);
  const assert=(yes,why)=>{if(!yes)throw Error(why);};
  const normalized=x=>((x%1)+1)%1;
  const nearPhase=(a,b)=>Math.abs(normalized(a-b+.5)-.5)<.015;
  const diff=(a,b)=>[a[0]-b[0],a[1]-b[1]];
  const distance=(a,b)=>Math.hypot(...diff(a,b));
  const dot=(a,b)=>a[0]*b[0]+a[1]*b[1];
  const cross=(a,b)=>a[0]*b[1]-a[1]*b[0];
  const radius=s=>distance(s.points.crank,s.points['pedal-a']);

  await page.setViewportSize({width:1200,height:800});
  page.setDefaultTimeout(3500);
  await page.context().route('**/*',route=>{
    const target=route.request().url();
    if(target===url)return route.continue();
    outgoing.push(target);
    return route.abort();
  });
  const sample=()=>page.evaluate(names=>{
    const points={};
    const origin=document.documentElement.getBoundingClientRect();
    for(const n of names){
      const circle=document.querySelector('[data-testid="pelican-'+n+'"]');
      if(!(circle instanceof SVGCircleElement))throw Error(n+' is not a circle probe');
      const matrix=circle.getScreenCTM();
      if(!matrix)throw Error(n+' has no screen transform');
      const out=new DOMPoint(circle.cx.baseVal.value,circle.cy.baseVal.value).matrixTransform(matrix);
      if(!Number.isFinite(out.x)||!Number.isFinite(out.y))throw Error(n+' has invalid coordinates');
      points[n]=[out.x-origin.x,out.y-origin.y];
    }
    return {points,...window.benchPelican.getState()};
  },markers);
  async function step(seconds){
    await page.evaluate(t=>window.benchPelican.step(t),seconds);
    return sample();
  }
  async function test(name,points,run,manual=true){
    try {
      const res=await page.goto(url,{waitUntil:'load',timeout:6000});
      assert(res?.ok(),'SVG did not return HTTP success');
      await page.waitForFunction(()=>window.benchPelican,undefined,{timeout:3500});
      if(manual) await page.evaluate(()=>{const p=window.benchPelican;p.setManualMode(true);p.reset();});
      await run();
      checks.push({name,points,pass:true});
    } catch(e){checks.push({name,points,pass:false,detail:String(e.message).slice(0,450)});}
  }
  await test('standalone SVG loads and actual playback advances',8,async()=>{
    assert(candidateFiles===null || candidateFiles.join()==='candidate/index.svg','submission contains extra candidate files');
    assert(await page.evaluate(()=>document.documentElement instanceof SVGSVGElement),'document is not standalone SVG');
    await id('play').waitFor({state:'visible'});
    await id('speed').waitFor({state:'visible'});
    const before=await sample();
    await page.waitForFunction(old=>{const s=window.benchPelican.getState();return !s.paused && s.phase!==old;},before.phase);
    const after=await sample();
    const scene=page.locator('svg').first();
    assert(distance(after.points['pedal-a'],before.points['pedal-a'])>0,'SVG geometry did not animate');
    // Ignore optional browser favicon fetch; all actual document resources must be inline.
    assert(outgoing.every(x=>x.endsWith('/favicon.ico')),'unexpected external resource');
    await scene.screenshot({path:output+'/pelican.svg.png'});
  },false);
  await test('opposed circular pedals and both foot contacts',16,async()=>{
    const a=await sample(), r=radius(a);
    assert(r>3,'pedal radius too small to assess');
    const seen=[];
    for(let i=0;i<8;i++){
      const s=i===0?a:await step(.25), p=s.points;
      const v=diff(p['pedal-a'],p.crank), w=diff(p['pedal-b'],p.crank);
      seen.push(v);
      assert(Math.abs(Math.hypot(...v)/r-1)<.12,'pedal radius varies');
      assert(Math.hypot(v[0]+w[0],v[1]+w[1])/r<.2,'pedals are not opposite');
      assert(distance(p['foot-a'],p['pedal-a'])/r<.14 && distance(p['foot-b'],p['pedal-b'])/r<.14,'a foot misses the corresponding pedal');
      assert(nearPhase(s.phase,i/8),'incorrect phase progression');
    }
    for(let i=1;i<seen.length;i++)
      assert(Math.abs(dot(seen[i-1],seen[i])/r**2-Math.SQRT1_2)<.2,'pedals skipped or repeated an angular position');
  });
  await test('fixed wheel centers and 1:1 wheel-to-crank rotation',12,async()=>{
    const initial=await sample(), r=radius(initial);
    assert(r>3,'pedal radius too small');
    let prev=initial;
    for(let i=0;i<8;i++){
      const next=await step(.25);
      const crank=cross(diff(prev.points['pedal-a'],prev.points.crank),diff(next.points['pedal-a'],next.points.crank));
      assert(Math.abs(crank)/r**2>.45,'crank did not advance');
      for(const wheel of ['front','rear']){
        const center='wheel-'+wheel+'-center', mark='wheel-'+wheel+'-mark';
        assert(distance(next.points[center],initial.points[center])/r<.10,'wheel center drifted');
        const a=diff(prev.points[mark],prev.points[center]), b=diff(next.points[mark],next.points[center]);
        const norm=Math.hypot(...a)*Math.hypot(...b);
        assert(norm>9 && Math.abs(dot(a,b)/norm-Math.SQRT1_2)<.17 && cross(a,b)*crank>0,'wheel cadence or direction disagrees with crank');
      }
      prev=next;
    }
  });
  await test('seat contact and continuous geometry across the loop',12,async()=>{
    const zero=await sample(), r=radius(zero);
    assert(r>3,'pedal radius too small');
    const poses=[zero];
    for(let i=0;i<7;i++)poses.push(await step(.25));
    const before=await step(.23), after=await step(.04);
    assert(nearPhase(before.phase,.99) && nearPhase(after.phase,.01),'time did not wrap after one cycle');
    for(const pose of [...poses,before,after]){
      assert(distance(pose.points.hip,pose.points.seat)/r<.24,'hip lost seat contact');
      for(const key of ['seat','crank'])
        assert(distance(pose.points[key],zero.points[key])/r<.09,'bike frame or seat moved');
    }
    for(const key of markers){
      const scale=key.endsWith('-mark') ? distance(zero.points[key],zero.points[key.replace('-mark','-center')]) : r;
      assert(scale>0 && distance(before.points[key],after.points[key])/scale<.34,'loop seam jumps at '+key);
    }
    await page.screenshot({path:output+'/pelican-loop.png'});
  });
  await test('real pause and speed buttons preserve phase and synchronize geometry',12,async()=>{
    const one=await step(.35), r=radius(one);
    assert(r>3 && one.rate===1 && !one.paused && nearPhase(one.phase,.175),'1x baseline incorrect');
    await id('play').click();
    const paused=await step(.4);
    assert(paused.paused && nearPhase(paused.phase,one.phase),'pause did not freeze time');
    assert(markers.every(k=>distance(one.points[k],paused.points[k])/r<.01),'geometry changed while paused');
    await id('speed').click();
    const fast=await sample();
    assert(fast.rate===2 && nearPhase(fast.phase,paused.phase),'speed changed phase or did not switch to 2x');
    await id('play').click();
    const resumed=await step(.25);
    assert(!resumed.paused && nearPhase(resumed.phase,one.phase+.25),'2x did not advance twice as fast');
    assert(distance(resumed.points['pedal-a'],paused.points['pedal-a'])/r>.8,'pedal did not move at 2x');
    for(const side of ['a','b'])
      assert(distance(resumed.points['foot-'+side],resumed.points['pedal-'+side])/r<.14,'foot lost contact after speed change');
    await id('speed').click();
    const restored=await sample();
    assert(restored.rate===1 && nearPhase(restored.phase,resumed.phase),'return to 1x reset phase');
  });
  return 'WEBBENCH_RESULT '+JSON.stringify(checks);
}
