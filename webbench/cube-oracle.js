() => {
  // Independent sticker model using each face's outward normal, right, and down bases.
  const names='URFDLB';
  const bases=[
    [[0,1,0],[1,0,0],[0,0,1]], [[1,0,0],[0,0,-1],[0,-1,0]],
    [[0,0,1],[1,0,0],[0,-1,0]], [[0,-1,0],[1,0,0],[0,0,-1]],
    [[-1,0,0],[0,0,1],[0,-1,0]], [[0,0,-1],[-1,0,0],[0,-1,0]],
  ];
  const dot=(a,b)=>a.reduce((s,v,i)=>s+v*b[i],0);
  const cross=([x,y,z],[a,b,c])=>[y*c-z*b,z*a-x*c,x*b-y*a];
  const rotate=(v,n)=>{
    const along=dot(v,n), perp=cross(n,v);
    return n.map((x,i)=>along*x-perp[i]);
  };
  const size=5, area=size*size, edge=size-1;
  const stickers=bases.flatMap(([n,r,d])=>Array.from({length:area},(_,i)=>[
    n.map((v,k)=>edge*v+(2*(i%size)-edge)*r[k]+(2*Math.floor(i/size)-edge)*d[k]), n
  ]));
  const indices=new Map(stickers.map(([p,n],i)=>[p.join(',')+';'+n.join(','),i]));
  const permutations=new Map();
  const solved=[...names].map(x=>x.repeat(area)).join('');
  function apply(state,token) {
    if(state.length!==solved.length) throw Error('incorrect facelet count');
    if(typeof token!=='string') throw Error('invalid move type');
    const move=/^(?:([2-5])(?:-([2-5]))?)?([URFDLB])(w?)(2|')?$/.exec(token);
    if(!move) throw Error('illegal move: '+token);
    const [,start,end,face,wide,turn]=move;
    const near=(end || !wide) ? Number(start||1) : 1;
    const far=Number(end||start||(wide?2:1));
    if(far>size || far<near || (end && (!wide||far===near||far===size)) || (!wide && near===size)) throw Error('illegal layers: '+token);
    const band=face+':'+near+':'+far;
    if(!permutations.has(band)) {
      const axis=bases[names.indexOf(face)][0];
      permutations.set(band,stickers.map(([p,n],i)=>{
        const layer=(edge-dot(p,axis))/2+1;
        return layer<near || layer>far ? i : indices.get(rotate(p,axis).join(',')+';'+rotate(n,axis).join(','));
      }));
    }
    for(let n=0;n<(turn==='2'?2:turn==="'"?3:1);n++){
      const next=[];
      permutations.get(band).forEach((dest,i)=>{next[dest]=state[i];});
      state=next.join('');
    }
    return state;
  }
  return {solved,apply,replay:(s,moves)=>moves.reduce(apply,s)};
}
