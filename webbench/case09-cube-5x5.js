async page => {
  const {base, origins, output, seed, solveTimeout} = __BENCH_CONFIG__;
  const oracle = (__CUBE_ORACLE__)();
  const checks = [], outsideRequests = [];
  const id = name => page.getByTestId('cube-'+name);
  const assert = (condition, detail) => { if (!condition) throw Error(detail); };
  const state = () => page.evaluate(() => window.benchCube.getState());
  const swapped = pairs => {
    const stickers = [...oracle.solved];
    for (const [a,b] of pairs) [stickers[a],stickers[b]] = [stickers[b],stickers[a]];
    return stickers.join('');
  };

  const faces = 'URFDLB';
  let rng = (seed ?? 34021) >>> 0;
  const choose = values => {
    rng = (Math.imul(rng,1664525)+1013904223) >>> 0;
    return values[(rng >>> 8) % values.length];
  };
  const turns = [];
  let previous = '';
  for (let i=0; i<55; i++) {
    const face = choose([...faces].filter(value=>value!==previous));
    const width = i===0?'3':i===1?'1':choose(['1','2','3']);
    const prefix = width==='3'?'3':'';
    turns.push(prefix+face+(width==='1'?'':'w')+choose(['','2',"'"]));
    previous = face;
  }
  const mixed = oracle.replay(oracle.solved,turns);
  // Swap the two UF wings with each other, keeping the middle edge fixed.
  const wingParity = swapped([[21,51],[23,53]]);
  const illegal = [
    oracle.solved.slice(1),
    'R'+oracle.solved.slice(1),
    swapped([[22,52]]),   // one middle edge flipped
    swapped([[52,127]]),  // two middle edges transposed
    swapped([[12,37]]),   // fixed centers cannot swap in isolation
  ];
  const twisted = [...oracle.solved];
  [twisted[24],twisted[25],twisted[54]] = [twisted[25],twisted[54],twisted[24]];
  illegal.push(twisted.join(''));

  page.setDefaultTimeout(4000);
  await page.setViewportSize({width:1365,height:900});
  await page.context().route('**/*', route => {
    const url = route.request().url();
    if (origins.some(origin=>url.startsWith(origin+'/'))) return route.continue();
    outsideRequests.push(url);
    return route.abort();
  });
  await page.context().routeWebSocket('**/*', socket => {
    outsideRequests.push(socket.url());
    return socket.close();
  });

  async function test(name, points, run) {
    try {
      outsideRequests.length = 0;
      const response = await page.goto(base+'/',{waitUntil:'domcontentloaded',timeout:6000});
      assert(response?.ok(),'HTTP load failed');
      await page.waitForFunction(()=>window.benchCube?.getState,undefined,{timeout:4000});
      const measurements = await run();
      assert(outsideRequests.length===0,'external request: '+outsideRequests[0]);
      checks.push({name,points,pass:true,...measurements});
    } catch(error) {
      checks.push({name,points,pass:false,detail:String(error.message).slice(0,450)});
    }
  }
  async function load(facelets) {
    await id('import-input').fill(facelets);
    await id('import').click();
    await page.waitForFunction(value=>window.benchCube.getState().facelets===value,facelets);
    const loaded = await state();
    assert(loaded.moveLog.length===0&&!loaded.animating,'import retained prior activity');
    assert(!await id('error').isVisible(),'valid import shows an error');
  }
  async function solveFrom(facelets, requireIntermediate) {
    await load(facelets);
    await page.evaluate(()=>{
      window.__cubeProgress = false;
      const initial = window.benchCube.getState().facelets;
      window.__cubeTick = setInterval(()=>{
        const snapshot = window.benchCube.getState();
        if (snapshot.animating && snapshot.moveLog.length>0 && snapshot.facelets!==initial) {
          window.__cubeProgress = true;
        }
      },25);
    });
    const started = Date.now();
    try {
      await id('solve').click();
      await page.waitForFunction(solved=>{
        const current = window.benchCube.getState();
        return current.animating || current.facelets===solved;
      },oracle.solved);
      const timeout = solveTimeout ? Math.max(1,solveTimeout-(Date.now()-started)) : 0;
      await page.waitForFunction(()=>!window.benchCube.getState().animating,undefined,{timeout});
      const elapsedMs = Date.now()-started;
      const result = await state();
      assert(result.facelets===oracle.solved,'solver stopped before restoring the cube');
      assert(Array.isArray(result.moveLog)&&result.moveLog.length>0,'no committed rotations');
      assert(oracle.replay(facelets,result.moveLog)===oracle.solved,'independent replay did not solve the cube');
      if (requireIntermediate) {
        assert(await page.evaluate(()=>window.__cubeProgress),'no intermediate rotation committed');
      }
      return {elapsed_ms:elapsedMs,move_count:result.moveLog.length};
    } finally {
      await page.evaluate(()=>clearInterval(window.__cubeTick));
    }
  }
  async function scramble() {
    await id('scramble').click();
    await page.waitForFunction(solved=>{
      const current = window.benchCube.getState();
      return current.facelets!==solved&&!current.animating;
    },oracle.solved,{timeout:12000});
    return state();
  }
  const resetState = () => page.waitForFunction(solved=>{
    const current = window.benchCube.getState();
    return current.facelets===solved&&!current.animating&&current.moveLog.length===0;
  },oracle.solved,{timeout:1000});

  await test('visible 5x5 cube and usable inner-layer scramble offline',10,async()=>{
    await id('view').waitFor({state:'visible'});
    assert((await state()).facelets===oracle.solved,'incorrect initial facelets');
    await id('view').screenshot({path:output+'/cube-desktop.png'});
    const result = await scramble();
    assert(result.moveLog.some(move=>/^[URFDLB][2']?$/.test(move)),'scramble lacked outer turns');
    assert(result.moveLog.some(move=>!/^[URFDLB][2']?$/.test(move)),'scramble lacked inner turns');
    assert(oracle.replay(oracle.solved,result.moveLog)===result.facelets,'scramble log did not match its state');
  });
  const deadline = solveTimeout ? ' within 90 seconds' : '';
  await test('external mixed scramble solved and independently replayed'+deadline,20,
    ()=>solveFrom(mixed,true));
  await test('legal wing parity solved and independently replayed'+deadline,20,
    ()=>solveFrom(wingParity,false));
  await test('illegal imports preserve facelets and committed moves',15,async()=>{
    const before = await scramble();
    for (const facelets of illegal) {
      await id('import-input').fill(facelets);
      await id('import').click();
      await id('error').waitFor({state:'visible'});
      const after = await state();
      assert(after.facelets===before.facelets && after.animating===before.animating &&
        JSON.stringify(after.moveLog)===JSON.stringify(before.moveLog),'invalid import modified live state');
    }
  });
  await test('duplicate solving cannot race reset during computation or playback',15,async()=>{
    await load(mixed);
    await id('solve').click();
    await page.waitForFunction(()=>window.benchCube.getState().animating);
    await id('solve').evaluate(button=>button.click());
    await id('reset').click();
    await resetState();
    await page.waitForTimeout(1500);
    await resetState();

    await load(wingParity);
    await id('solve').click();
    await page.waitForFunction(()=>window.benchCube.getState().animating);
    await page.waitForFunction(()=>{
      const current=window.benchCube.getState();
      return !current.animating || current.moveLog.length>0;
    },undefined,{timeout:solveTimeout ? 30000 : 0});
    assert((await state()).animating,'playback ended before reset could be tested');
    await id('reset').click();
    await resetState();
    await page.waitForTimeout(1200);
    await resetState();
  });
  return 'WEBBENCH_RESULT '+JSON.stringify(checks);
}
