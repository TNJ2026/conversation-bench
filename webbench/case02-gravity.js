async page => {
  const {base, origins, output} = __BENCH_CONFIG__;
  const checks = [];
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.setDefaultTimeout(3000);
  await page.context().route('**/*', route => origins.some(origin => route.request().url().startsWith(origin + '/')) ? route.continue() : route.abort());
  await page.addInitScript(() => {
    const get = HTMLCanvasElement.prototype.getContext;
    const used = new WeakSet();
    HTMLCanvasElement.prototype.getContext = function (kind, ...options) {
      const result = get.call(this, kind, ...options);
      if (result && ['webgl', 'webgl2', 'experimental-webgl'].includes(kind)) used.add(this);
      return result;
    };
    window.__benchUsesWebGL = canvas => used.has(canvas);
  });
  const id = name => page.getByTestId('gravity-' + name);
  const assert = (condition, error) => { if (!condition) throw new Error(error); };
  async function open() {
    const res = await page.goto(base + '/', {waitUntil:'domcontentloaded', timeout:6000});
    assert(res && res.ok(), 'HTTP load failed');
    await page.waitForFunction(() => window.benchGravity, {timeout:3000});
  }
  async function test(name, points, fn) {
    try { await open(); await fn(); checks.push({name, points, pass:true}); }
    catch (error) { checks.push({name, points, pass:false, detail:String(error.message).slice(0,450)}); }
  }
  const state = () => page.evaluate(() => window.benchGravity.getState());
  await page.setViewportSize({width:1365,height:900});
  await test('visible WebGL scene and actual camera orbit', 10, async () => {
    const canvas = id('canvas');
    await canvas.waitFor({state:'visible'});
    assert(await canvas.evaluate(node => window.__benchUsesWebGL(node)), 'canvas has no WebGL context');
    const start = await state();
    const before = await canvas.screenshot();
    await page.evaluate(() => window.benchGravity.orbit(.55,.25));
    const after = await canvas.screenshot({path:output + '/gravity-desktop.png'});
    assert(JSON.stringify((await state()).camera.position) !== JSON.stringify(start.camera.position), 'camera position did not move');
    assert(!before.equals(after), 'visible scene did not change');
  });
  await test('add and remove distinct 3D bodies', 10, async () => {
    const s = await page.evaluate(() => {
      const g=window.benchGravity;
      g.clear();
      const a=g.addBody({mass:2,radius:.1,position:[2,3,4],velocity:[.1,.2,.3]});
      const b=g.addBody({mass:3,radius:.1,position:[4,5,7],velocity:[0,0,0]});
      const before=g.getState().bodies;
      g.removeBody(a);
      return {a,b,before,after:g.getState().bodies};
    });
    assert(typeof s.a==='string' && s.a && s.a!==s.b && s.before.length===2 && s.after.length===1 && s.after[0].id===s.b, 'add/remove or IDs incorrect');
    const a=s.before.find(x=>x.id===s.a);
    assert(a && a.mass===2 && a.position.join()==='2,3,4' && a.velocity.join()==='0.1,0.2,0.3', '3D input lost');
  });
  await test('inverse-square gravity and equal/opposite momentum', 10, async () => {
    const v = await page.evaluate(() => {
      const g=window.benchGravity;
      return [5,10].map(d=>{
        g.clear(); g.setGravity(1);
        for (const [mass,x] of [[2,0],[3,d]]) g.addBody({mass,radius:.01,position:[x,0,0],velocity:[0,0,0]});
        g.step(.01);
        return g.getState().bodies.map(b=>b.velocity[0]);
      });
    });
    const [[a,b],[c]]=v;
    assert(a > 0 && b < 0 && c > 0 && a/c > 3.5 && a/c < 4.5, 'wrong gravity direction or distance relation');
    assert(Math.abs(2*a+3*b) < .0001, 'pair momentum did not balance');
  });
  await test('overlap merges with mass and momentum conservation', 10, async () => {
    const b = await page.evaluate(() => {
      const g=window.benchGravity; g.clear(); g.setGravity(0);
      g.addBody({mass:2,radius:1,position:[0,0,0],velocity:[3,1,0]});
      g.addBody({mass:3,radius:1,position:[1,0,0],velocity:[-2,1,0]});
      g.step(.02);
      return g.getState().bodies;
    });
    assert(b.length===1 && Math.abs(b[0].mass-5)<1e-8, 'overlap did not merge into total mass');
    assert(b[0].velocity.every((x,i)=>Math.abs(x-[0,1,0][i])<.02), 'merged momentum incorrect');
  });
  await test('actual UI play, pause and reset', 10, async () => {
    const initial=await state();
    assert(initial.paused && initial.bodies.length>0,'initial scene not paused or empty');
    await id('play').click();
    await page.waitForFunction(t=>window.benchGravity.getState().time>t, initial.time, {timeout:3000});
    await id('play').click();
    const stopped=await state();
    await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    assert(stopped.paused && (await state()).time===stopped.time,'pause did not stop simulation');
    await id('reset').click();
    const reset=await state();
    assert(reset.paused && reset.time===initial.time && reset.bodies.map(b=>[b.mass,...b.position]).flat().join()===initial.bodies.map(b=>[b.mass,...b.position]).flat().join(), 'reset did not restore default state');
  });
  await test('actual trails and curvature controls toggle state', 5, async () => {
    const before=(await state()).overlays;
    await id('trails').click();
    await id('curvature').click();
    const after=(await state()).overlays;
    assert(typeof before.trails==='boolean' && typeof before.curvature==='boolean' && before.trails!==after.trails && before.curvature!==after.curvature, 'overlay controls did not toggle');
  });
  await test('close encounter stays finite through 1500 steps', 13, async () => {
    const valid=await page.evaluate(()=>{
      const g=window.benchGravity; g.clear(); g.setGravity(1);
      const bodies=[[100,0,0,0,0,0],[.1,4,0,0,5,0],[.2,4.08,0,.02,4.99,.01],[1,-8,0,0,-3,0]];
      for (const [mass,x,y,z,vy,vz] of bodies) g.addBody({mass,radius:.01,position:[x,y,z],velocity:[0,vy,vz]});
      for(let i=0;i<1500;i++) {
        g.step(1/120);
        if(i%50===0 && g.getState().bodies.some(b=>!b.position.concat(b.velocity).every(Number.isFinite))) return false;
      }
      const s=g.getState();
      return s.time>12 && s.bodies.length>0 && s.bodies.every(b=>b.position.concat(b.velocity).every(Number.isFinite));
    });
    assert(valid,'non-finite state or step did not advance');
  });
  await test('20-body fixed workload and UI responsiveness', 12, async () => {
    const outcome=await page.evaluate(()=>{
      const g=window.benchGravity; g.clear(); g.setGravity(.5);
      for(let i=0;i<20;i++){
        const angle=i*Math.PI/10;
        g.addBody({mass:1+i/20,radius:.015,position:[Math.cos(angle)*9,i*.04,Math.sin(angle)*9],velocity:[-.1*Math.sin(angle),0,.1*Math.cos(angle)]});
      }
      const start=performance.now();
      for(let i=0;i<360;i++) g.step(1/120);
      const elapsed=performance.now()-start;
      const state=g.getState();
      return {elapsed,time:state.time,bodies:state.bodies.length};
    });
    assert(outcome.time>2.9 && outcome.bodies===20 && outcome.elapsed<4000, '20-body turn exceeds threshold or incorrect: '+JSON.stringify(outcome));
    await id('reset').click();
    assert(errors.length===0, errors.join('; '));
  });
  return 'WEBBENCH_RESULT ' + JSON.stringify(checks);
}
