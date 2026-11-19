async page => {
  const {base,origins,output}=__BENCH_CONFIG__;
  const checks=[];
  const id=n=>page.getByTestId('maze-'+n);
  const assert=(ok,msg)=>{if(!ok)throw Error(msg);};
  const state=()=>page.evaluate(()=>window.benchMaze.getState());
  const maze=['#########','#S..#..G#','#...#...#','#.......#','#########'];
  const openSpace=['#########','#.......#','#.S.....#','#.......#','#......G#','#########'];
  await page.setViewportSize({width:1365,height:900});
  page.setDefaultTimeout(4000);
  await page.context().route('**/*',r=>origins.some(o=>r.request().url().startsWith(o+'/'))?r.continue():r.abort());
  async function load(rows){
    await page.evaluate(map=>{
      const m=window.benchMaze;m.setManualMode(true);m.loadMap(map);m.setManualMode(true);
    },rows);
  }
  async function drive(input,n,dt){
    return page.evaluate(({input,n,dt})=>{
      const m=window.benchMaze;
      m.setInput({forward:0,strafe:0,turn:0,...input});
      for(let i=0;i<n;i++)m.step(dt);
      return m.getState();
    },{input,n,dt});
  }
  async function test(name,points,run){
    try {
      const r=await page.goto(base+'/',{waitUntil:'domcontentloaded',timeout:6000});
      assert(r?.ok(),'HTTP load failed');
      await page.waitForFunction(()=>window.benchMaze,undefined,{timeout:4000});
      await run();checks.push({name,points,pass:true});
    } catch(e){checks.push({name,points,pass:false,detail:String(e.message).slice(0,450)});}
  }
  await test('visible view reacts to actual state and turn input',10,async()=>{
    await load(maze); await id('view').waitFor({state:'visible'});
    const before=await id('view').screenshot();
    const r=await drive({turn:1},4,.20);
    const after=await id('view').screenshot({path:output+'/maze-desktop.png'});
    assert(Math.abs(r.yaw-1.2)<.09,'yaw did not respond at stipulated speed');
    assert(!before.equals(after),'turn did not update visible view');
  });
  await test('W input moves in the interactive runtime',10,async()=>{
    await load(openSpace);
    await id('view').click({position:{x:10,y:10}});
    await page.evaluate(()=>window.benchMaze.setManualMode(false));
    const before=await state();
    await page.keyboard.down('w');
    try{
      await page.waitForFunction(x=>window.benchMaze.getState().x>x+.12,before.x,{timeout:2500});
    } finally {await page.keyboard.up('w');}
    const after=await state();
    assert(Math.abs(after.y-before.y)<.15,'W moved sideways');
  });
  await test('head-on wall blocks sustained input and large substeps',15,async()=>{
    await load(maze);
    const r=await drive({forward:1},10,.25);
    assert(r.x>3.55 && r.x<=3.815 && Math.abs(r.y-1.5)<.05,'wall stopped at wrong position or tunneled: '+JSON.stringify(r));
  });
  await test('diagonal player radius respects a wall corner',15,async()=>{
    const map=['#########','#S#....G#','#.#.....#','#.......#','#########'];
    await load(map);
    const samples=await page.evaluate(()=>{
      const m=window.benchMaze;
      m.setInput({forward:1,strafe:1,turn:0});
      const samples=[];
      for(let i=0;i<27;i++){m.step(.05);samples.push(m.getState());}
      return samples;
    });
    for(const s of samples){
      assert(Number.isFinite(s.x)&&Number.isFinite(s.y)&&s.x>.18&&s.y>.18,'invalid position');
      for(let row=0;row<map.length;row++)for(let col=0;col<map[row].length;col++){
        if(map[row][col]!=='#')continue;
        const dx=s.x-Math.max(col,Math.min(s.x,col+1));
        const dy=s.y-Math.max(row,Math.min(s.y,row+1));
        assert(Math.hypot(dx,dy)>=.182,'player radius penetrated wall: '+JSON.stringify(s));
      }
    }
    const end=samples.at(-1);
    assert(end.y>3.15 && end.x>2.04,'did not slide through the valid corner');
  });
  await test('timestep equivalence and normalized diagonal speed',15,async()=>{
    await load(openSpace); const a=await drive({forward:1},5,.1);
    await load(openSpace); const b=await drive({forward:1},20,.025);
    await load(openSpace); const d=await drive({forward:1,strafe:1},10,.05);
    assert(Math.abs(a.x-4)<.07 && Math.abs(a.x-b.x)<.04 && Math.abs(a.y-b.y)<.04,'frame subdivision changed movement');
    assert(Math.abs(Math.hypot(d.x-2.5,d.y-2.5)-1.5)<.07,'diagonal speed was not normalized');
  });
  await test('navigate around barrier, reach goal, reset and clear stale input',15,async()=>{
    await load(maze);
    const path=[[{strafe:1},20],[{forward:1},60],[{strafe:-1},20]];
    for(let i=0;i<path.length;i++){
      const [input,n]=path[i];
      const r=await drive(input,n,1/30);
      if(i<path.length-1) assert(!r.won,'won before reaching goal');
    }
    assert((await state()).won,'goal did not register after valid route');
    await id('win').waitFor({state:'visible'});
    await id('reset').click();
    await id('win').waitFor({state:'hidden'});
    const start=await state();
    assert(Math.abs(start.x-1.5)<.05 && Math.abs(start.y-1.5)<.05 && !start.won,'reset did not return to start');
    await page.evaluate(()=>{const m=window.benchMaze;m.setManualMode(true);m.step(.20);});
    const after=await state();
    assert(Math.hypot(after.x-start.x,after.y-start.y)<.04,'stale movement survived reset');
  });
  return 'WEBBENCH_RESULT '+JSON.stringify(checks);
}
