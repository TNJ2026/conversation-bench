/* 五阶魔方界面：CSS 3D 渲染、视角拖动、逐层动画、按钮逻辑、window.benchCube */
(function () {
  'use strict';
  var C = window.CubeCore;
  var COLORS = { U: '#ffffff', R: '#d7263d', F: '#1f9d55', D: '#ffd500', L: '#ff7a00', B: '#1565c0' };

  var view = document.getElementById('cube-view');
  var cubeEl = document.getElementById('cube');
  var statusEl = document.getElementById('status');
  var errorEl = document.getElementById('cube-error');
  var input = document.getElementById('import-input');
  var logEl = document.getElementById('log');
  var logCount = document.getElementById('log-count');
  var speedSel = document.getElementById('speed');
  var btn = {
    scramble: document.getElementById('btn-scramble'),
    solve: document.getElementById('btn-solve'),
    reset: document.getElementById('btn-reset'),
    imp: document.getElementById('btn-import'),
    fill: document.getElementById('btn-fill')
  };

  // ---------- 逻辑状态 ----------
  var state = C.SOLVED.split('');
  var moveLog = [];
  var computing = false, playing = false;
  var job = 0;              // 每次重置/导入/新任务递增，旧的异步结果据此丢弃

  // ---------- 矩阵（逻辑坐标：x→R, y→U, z→F；CSS 坐标 y 向下，用 F=diag(1,-1,1) 共轭）----------
  function mul(a, b) {
    var o = new Array(16);
    for (var r = 0; r < 4; r++) for (var c = 0; c < 4; c++) {
      var s = 0;
      for (var k = 0; k < 4; k++) s += a[r * 4 + k] * b[k * 4 + c];
      o[r * 4 + c] = s;
    }
    return o;
  }
  function rotM(axis, deg) {
    var t = deg * Math.PI / 180, c = Math.cos(t), s = Math.sin(t);
    if (axis === 0) return [1, 0, 0, 0, 0, c, -s, 0, 0, s, c, 0, 0, 0, 0, 1];
    if (axis === 1) return [c, 0, s, 0, 0, 1, 0, 0, -s, 0, c, 0, 0, 0, 0, 1];
    return [c, -s, 0, 0, s, c, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
  }
  function transM(x, y, z) { return [1, 0, 0, x, 0, 1, 0, y, 0, 0, 1, z, 0, 0, 0, 1]; }
  function css(m) {
    var f = [1, -1, 1, 1], v = [];
    for (var c = 0; c < 4; c++) for (var r = 0; r < 4; r++) {
      var x = m[r * 4 + c] * f[r] * f[c];
      v.push(Math.abs(x) < 1e-10 ? 0 : +x.toFixed(6));
    }
    return 'matrix3d(' + v.join(',') + ')';
  }

  // ---------- 构建块 ----------
  var SIZE = 46;
  var cubies = [];         // {el, pos, faces:{}}
  var cubieAt = {};
  var stickerEl = new Array(150);
  var FACE_CSS = {
    '0,0,1': function (h) { return 'translateZ(' + h + 'px)'; },
    '0,0,-1': function (h) { return 'rotateY(180deg) translateZ(' + h + 'px)'; },
    '1,0,0': function (h) { return 'rotateY(90deg) translateZ(' + h + 'px)'; },
    '-1,0,0': function (h) { return 'rotateY(-90deg) translateZ(' + h + 'px)'; },
    '0,1,0': function (h) { return 'rotateX(90deg) translateZ(' + h + 'px)'; },
    '0,-1,0': function (h) { return 'rotateX(-90deg) translateZ(' + h + 'px)'; }
  };
  function build() {
    for (var x = -2; x <= 2; x++) for (var y = -2; y <= 2; y++) for (var z = -2; z <= 2; z++) {
      if (Math.max(Math.abs(x), Math.abs(y), Math.abs(z)) !== 2) continue;
      var el = document.createElement('div');
      el.className = 'cubie';
      var cb = { el: el, pos: [x, y, z], faces: {} };
      Object.keys(FACE_CSS).forEach(function (k) {
        var n = k.split(',').map(Number);
        // 只为朝外且在表面的方向放面片；朝内的面也画成黑色以遮挡转动缝隙
        var f = document.createElement('div');
        f.className = 'face';
        f.dataset.n = k;
        el.appendChild(f);
        cb.faces[k] = f;
      });
      cubeEl.appendChild(el);
      cubies.push(cb);
      cubieAt[[x, y, z].join(',')] = cb;
    }
    for (var i = 0; i < 150; i++) {
      var c = cubieAt[C.POS[i].join(',')], f2 = c.faces[C.NRM[i].join(',')];
      var s = document.createElement('div');
      s.className = 'sticker';
      f2.appendChild(s);
      stickerEl[i] = s;
    }
    layout();
  }
  function layout() {
    var w = view.clientWidth || 460;
    SIZE = Math.max(24, Math.floor(w / 9.2));
    var h = SIZE / 2;
    cubies.forEach(function (cb) {
      cb.el.style.width = cb.el.style.height = SIZE + 'px';
      cb.el.style.left = cb.el.style.top = (-h) + 'px';
      Object.keys(cb.faces).forEach(function (k) { cb.faces[k].style.transform = FACE_CSS[k](h - 0.01); });
      cb.base = transM(cb.pos[0] * SIZE, cb.pos[1] * SIZE, cb.pos[2] * SIZE);
      cb.el.style.transform = css(cb.base);
    });
  }
  function paint() {
    for (var i = 0; i < 150; i++) stickerEl[i].style.background = COLORS[state[i]];
  }

  // ---------- 视角 ----------
  var DEFAULT_VIEW = { yaw: -36, pitch: 28 };
  var yaw = DEFAULT_VIEW.yaw, pitch = DEFAULT_VIEW.pitch;
  function applyView() {
    cubeEl.style.transform = css(mul(rotM(0, pitch), rotM(1, yaw)));
  }
  var drag = null;
  view.addEventListener('pointerdown', function (e) {
    drag = { id: e.pointerId, x: e.clientX, y: e.clientY };
    try { view.setPointerCapture(e.pointerId); } catch (err) { /* 合成事件无活动指针时忽略 */ }
    view.classList.add('dragging');
    e.preventDefault();
  });
  view.addEventListener('pointermove', function (e) {
    if (!drag || drag.id !== e.pointerId) return;
    yaw += (e.clientX - drag.x) * 0.45;
    pitch = Math.max(-89, Math.min(89, pitch + (e.clientY - drag.y) * 0.45));
    drag.x = e.clientX; drag.y = e.clientY;
    applyView();
  });
  function endDrag(e) {
    if (drag && drag.id === e.pointerId) { drag = null; view.classList.remove('dragging'); }
  }
  view.addEventListener('pointerup', endDrag);
  view.addEventListener('pointercancel', endDrag);
  view.addEventListener('dblclick', function () { yaw = DEFAULT_VIEW.yaw; pitch = DEFAULT_VIEW.pitch; applyView(); });
  view.addEventListener('keydown', function (e) {
    var d = { ArrowLeft: [-8, 0], ArrowRight: [8, 0], ArrowUp: [0, -8], ArrowDown: [0, 8] }[e.key];
    if (!d) return;
    e.preventDefault();
    yaw += d[0]; pitch = Math.max(-89, Math.min(89, pitch + d[1]));
    applyView();
  });
  window.addEventListener('resize', function () { layout(); });

  // ---------- 动画 ----------
  function resetTransforms() { cubies.forEach(function (cb) { cb.el.style.transform = css(cb.base); }); }
  function movingCubies(tok) {
    var list = [];
    cubies.forEach(function (cb) {
      var k = 3 - cb.pos[tok.axis];
      if (k >= tok.lo && k <= tok.hi) list.push(cb);
    });
    return list;
  }
  function animateToken(tok, myJob) {
    return new Promise(function (resolve) {
      var parts = movingCubies(tok);
      var target = tok.q === 3 ? 90 : -90 * tok.q;   // 从正方向面看顺时针 = 绕正轴 -90°
      var dur = (+speedSel.value || 90) * (tok.q === 2 ? 1.5 : 1);
      var t0 = null;
      function frame(now) {
        if (job !== myJob) { resolve(false); return; }
        if (t0 === null) t0 = now;
        var u = Math.min(1, (now - t0) / dur);
        var e = u < 0.5 ? 2 * u * u : 1 - Math.pow(-2 * u + 2, 2) / 2;
        var r = rotM(tok.axis, target * e);
        for (var i = 0; i < parts.length; i++) parts[i].el.style.transform = css(mul(r, parts[i].base));
        if (u < 1) requestAnimationFrame(frame);
        else resolve(true);
      }
      requestAnimationFrame(frame);
    });
  }
  function commit(tok, notation) {
    state = C.applyMoves(state, C.tokenMoves(tok));
    moveLog.push(notation);
    resetTransforms();
    paint();
    renderLog();
  }
  async function play(notations, myJob, label) {
    playing = true; refresh();
    var t0 = performance.now();
    for (var i = 0; i < notations.length; i++) {
      if (job !== myJob) return false;
      var tok = C.parseMove(notations[i]);
      setStatus(label + '：' + (i + 1) + ' / ' + notations.length + '  ' + notations[i]);
      var done = await animateToken(tok, myJob);
      if (!done || job !== myJob) return false;   // 被取消：不提交这一步
      commit(tok, notations[i]);
    }
    playing = false; refresh();
    return performance.now() - t0;
  }

  // ---------- 界面状态 ----------
  function busy() { return computing || playing; }
  function refresh() {
    btn.solve.disabled = busy();
    btn.scramble.disabled = busy();
  }
  function setStatus(msg, bad) {
    statusEl.textContent = msg;
    statusEl.classList.toggle('bad', !!bad);
  }
  function renderLog() {
    logCount.textContent = moveLog.length + ' 步';
    logEl.textContent = moveLog.length ? moveLog.join(' ') : '（无）';
    logEl.scrollTop = logEl.scrollHeight;
  }
  function hideError() { errorEl.hidden = true; errorEl.textContent = ''; }
  function cancelAll() {
    job++;
    computing = false; playing = false;
    resetTransforms();
  }
  function fmtMs(ms) { return ms < 1000 ? Math.round(ms) + ' ms' : (ms / 1000).toFixed(1) + ' s'; }

  // ---------- 操作 ----------
  async function doScramble() {
    if (busy()) return;
    hideError();
    var myJob = ++job;
    var seq = C.randomScramble(36);
    var t = await play(seq, myJob, '打乱');
    if (t !== false && job === myJob) setStatus('打乱完成：' + seq.length + ' 步（含外层与内层转动），用时 ' + fmtMs(t));
  }

  async function doSolve() {
    if (busy()) return;
    hideError();
    var myJob = ++job;
    computing = true; refresh();
    setStatus('正在计算解法…');
    var t0 = performance.now(), sol;
    try {
      sol = await C.solve(state.join(''), { cancelled: function () { return job !== myJob; } });
    } catch (e) {
      if (job !== myJob || e === C.CANCELLED) return;   // 已取消：结果丢弃
      computing = false; refresh();
      setStatus('求解失败：' + (e && e.message ? e.message : e), true);
      return;
    }
    if (job !== myJob) return;
    var tCalc = performance.now() - t0;
    computing = false;
    if (!sol.length) { refresh(); setStatus('已经是复原状态'); return; }
    var tPlay = await play(sol, myJob, '求解播放');
    if (tPlay !== false && job === myJob) {
      setStatus('已复原：' + sol.length + ' 步；计算 ' + fmtMs(tCalc) + '，播放 ' + fmtMs(tPlay) +
        (C.isSolved(state) ? '' : '（异常：未复原）'), !C.isSolved(state));
    }
  }

  function doReset() {
    cancelAll();
    state = C.SOLVED.split('');
    moveLog = [];
    hideError();
    paint(); renderLog(); refresh();
    setStatus('已重置为复原状态');
  }

  function doImport() {
    var v = C.validate(input.value);
    if (!v.ok) {
      errorEl.textContent = '导入失败：' + v.error + ' 当前状态与转动记录保持不变。';
      errorEl.hidden = false;
      return;
    }
    cancelAll();
    state = v.facelets.split('');
    moveLog = [];
    hideError();
    paint(); renderLog(); refresh();
    setStatus(C.isSolved(state) ? '已导入（复原状态）' : '已导入局面，可点击“求解”');
  }

  btn.scramble.addEventListener('click', doScramble);
  btn.solve.addEventListener('click', doSolve);
  btn.reset.addEventListener('click', doReset);
  btn.imp.addEventListener('click', doImport);
  btn.fill.addEventListener('click', function () { input.value = state.join(''); });

  window.benchCube = {
    getState: function () {
      return { facelets: state.join(''), animating: busy(), moveLog: moveLog.slice() };
    }
  };

  build();
  applyView();
  paint();
  renderLog();
  refresh();
})();
