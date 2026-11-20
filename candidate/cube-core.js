/*
 * 五阶魔方核心：模型、记号、局面校验、求解器。
 * 纯原生 JavaScript，无依赖。浏览器中挂到 window.CubeCore，Node 中通过 module.exports 导出。
 *
 * 坐标约定：x 指向 R，y 指向 U，z 指向 F；每个块的坐标取值 -2..2。
 * 面片串：面序 URFDLB，每面 25 个字符，从外朝内看，按行从左上到右下。
 */
(function (global) {
  'use strict';

  var FACES = 'URFDLB';
  var FACE_NORMAL = [[0, 1, 0], [1, 0, 0], [0, 0, 1], [0, -1, 0], [-1, 0, 0], [0, 0, -1]];
  var POS_FACE = ['R', 'U', 'F'];   // 每个轴的正方向面
  var NEG_FACE = ['L', 'D', 'B'];   // 每个轴的负方向面
  var NST = 150;
  var SOLVED = (function () {
    var s = '';
    for (var f = 0; f < 6; f++) for (var i = 0; i < 25; i++) s += FACES[f];
    return s;
  })();

  // ---------- 几何 ----------
  function stickerPos(f, r, c) {
    switch (FACES[f]) {
      case 'U': return [c - 2, 2, r - 2];
      case 'R': return [2, 2 - r, 2 - c];
      case 'F': return [c - 2, 2 - r, 2];
      case 'D': return [c - 2, -2, 2 - r];
      case 'L': return [-2, 2 - r, c - 2];
      case 'B': return [2 - c, 2 - r, -2];
    }
  }
  function faceOfNormal(n) {
    for (var f = 0; f < 6; f++) {
      var m = FACE_NORMAL[f];
      if (m[0] === n[0] && m[1] === n[1] && m[2] === n[2]) return f;
    }
    return -1;
  }
  function posKey(p, f) { return (p[0] + 2) + 5 * (p[1] + 2) + 25 * (p[2] + 2) + 125 * f; }

  var POS = [], NRM = [], FACE_OF = [];
  var LOOKUP = new Int16Array(750).fill(-1);
  (function () {
    for (var f = 0; f < 6; f++) for (var r = 0; r < 5; r++) for (var c = 0; c < 5; c++) {
      var i = f * 25 + r * 5 + c;
      POS[i] = stickerPos(f, r, c);
      NRM[i] = FACE_NORMAL[f];
      FACE_OF[i] = f;
      LOOKUP[posKey(POS[i], f)] = i;
    }
  })();

  // 绕正轴方向看顺时针 90°（右手定则 -90°）
  function rot(v, a) {
    if (a === 0) return [v[0], v[2], -v[1]];
    if (a === 1) return [-v[2], v[1], v[0]];
    return [v[1], -v[0], v[2]];
  }
  function cross(a, b) { return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]; }
  function dot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }

  // ---------- 基本转动：axis(0..2) × layer(1..5，从正方向面数) × q(1..3) ----------
  // 状态 new[k] = old[src[k]]；dest[i] 为位置 i 的面片转到的位置。
  var MOVES = [];
  function moveId(a, k, q) { return (a * 5 + (k - 1)) * 3 + (q - 1); }
  (function () {
    for (var a = 0; a < 3; a++) for (var k = 1; k <= 5; k++) {
      var coord = 3 - k;
      for (var q = 1; q <= 3; q++) {
        var dest = new Int16Array(NST), src = new Int16Array(NST);
        for (var i = 0; i < NST; i++) {
          var p = POS[i], n = NRM[i];
          if (p[a] === coord) {
            for (var t = 0; t < q; t++) { p = rot(p, a); n = rot(n, a); }
            dest[i] = LOOKUP[posKey(p, faceOfNormal(n))];
          } else dest[i] = i;
        }
        for (var j = 0; j < NST; j++) src[dest[j]] = j;
        MOVES.push({ axis: a, layer: k, q: q, src: src, dest: dest, inv: moveId(a, k, 4 - q) });
      }
    }
  })();
  var NMOVES = MOVES.length; // 45

  function applyMove(state, m) {
    var s = MOVES[m].src, out = new Array(NST);
    for (var k = 0; k < NST; k++) out[k] = state[s[k]];
    return out;
  }
  function applyMoves(state, list) {
    var cur = state;
    for (var i = 0; i < list.length; i++) cur = applyMove(cur, list[i]);
    return cur;
  }
  function invertMoves(list) {
    var out = [];
    for (var i = list.length - 1; i >= 0; i--) out.push(MOVES[list[i]].inv);
    return out;
  }
  function identityPerm() { var p = new Int16Array(NST); for (var i = 0; i < NST; i++) p[i] = i; return p; }
  // 先执行 perm 再执行 move 的合成（src 形式）
  function composeMove(perm, m) {
    var s = MOVES[m].src, out = new Int16Array(NST);
    for (var k = 0; k < NST; k++) out[k] = perm[s[k]];
    return out;
  }
  function permOf(list) {
    var p = identityPerm();
    for (var i = 0; i < list.length; i++) p = composeMove(p, list[i]);
    return p;
  }

  // ---------- 记号 ----------
  // token: {axis, lo, hi, q}，层号从轴的正方向面数，q 为从正方向面看的顺时针四分之一圈数
  function tokenMoves(t) {
    var out = [];
    for (var k = t.lo; k <= t.hi; k++) out.push(moveId(t.axis, k, t.q));
    return out;
  }
  function suffix(q) { return q === 1 ? '' : q === 2 ? '2' : "'"; }
  function formatToken(t) {
    var a = t.axis, lo = t.lo, hi = t.hi, q = t.q;
    var P = POS_FACE[a], N = NEG_FACE[a], nq = (4 - q) % 4 || 4;
    if (q === 2) nq = 2;
    if (lo === 1 && hi === 5) return '5' + P + 'w' + suffix(q);
    if (lo === 1) return (hi === 1 ? P : hi === 2 ? P + 'w' : hi + P + 'w') + suffix(q);
    if (hi === 5) {
      var d = 6 - lo;
      return (d === 1 ? N : d === 2 ? N + 'w' : d + N + 'w') + suffix(nq);
    }
    if (lo === hi) return lo <= 3 ? lo + P + suffix(q) : (6 - lo) + N + suffix(nq);
    if (lo === 2 && hi === 3) return '2-3' + P + 'w' + suffix(q);
    if (lo === 3 && hi === 4) return '2-3' + N + 'w' + suffix(nq);
    return '2-4' + P + 'w' + suffix(q); // lo=2, hi=4
  }
  var FACE_AXIS = { R: [0, 1], L: [0, -1], U: [1, 1], D: [1, -1], F: [2, 1], B: [2, -1] };
  function parseMove(str) {
    var s = String(str).trim().replace(/[\u2019\u2032`]/g, "'");
    var m = /^([xyz])(2'|2|')?$/.exec(s);
    if (m) return { axis: 'xyz'.indexOf(m[1]), lo: 1, hi: 5, q: m[2] === "'" ? 3 : m[2] ? 2 : 1 };
    m = /^(?:([1-5])(?:-([1-5]))?)?([URFDLB])(w?)(2'|2|')?$/.exec(s);
    if (!m) throw new Error('无法识别的转动记号：' + str);
    var d1 = m[1] ? +m[1] : 0, d2 = m[2] ? +m[2] : 0, w = m[4] === 'w';
    var lo, hi;
    if (!d1) { lo = 1; hi = w ? 2 : 1; }
    else if (d2) { lo = d1; hi = d2; }
    else if (w) { lo = 1; hi = d1; }
    else { lo = hi = d1; }
    if (lo > hi) throw new Error('层区间不合法：' + str);
    var q = m[5] === "'" ? 3 : m[5] ? 2 : 1;
    var fa = FACE_AXIS[m[3]];
    if (fa[1] < 0) { var l2 = 6 - hi, h2 = 6 - lo; lo = l2; hi = h2; q = q === 2 ? 2 : 4 - q; }
    return { axis: fa[0], lo: lo, hi: hi, q: q };
  }
  function applyNotation(state, list) {
    var cur = state.split ? state.split('') : state.slice();
    for (var i = 0; i < list.length; i++) cur = applyMoves(cur, tokenMoves(parseMove(list[i])));
    return cur.join('');
  }

  // 合并同轴相邻转动并分组为（宽层/内层/整体）记号
  function simplify(list) {
    var stack = [];
    for (var i = 0; i < list.length; i++) {
      var mv = MOVES[list[i]], top = stack[stack.length - 1];
      if (!top || top.axis !== mv.axis) { top = { axis: mv.axis, net: [0, 0, 0, 0, 0, 0] }; stack.push(top); }
      top.net[mv.layer] = (top.net[mv.layer] + mv.q) % 4;
      if (top.net.every(function (x) { return x === 0; })) stack.pop();
    }
    var tokens = [];
    stack.forEach(function (g) {
      var k = 1;
      while (k <= 5) {
        if (!g.net[k]) { k++; continue; }
        var lo = k, q = g.net[k];
        while (k + 1 <= 5 && g.net[k + 1] === q) k++;
        tokens.push({ axis: g.axis, lo: lo, hi: k, q: q });
        k++;
      }
    });
    return tokens;
  }

  // ---------- 块（piece slot）----------
  // type: Z 固定中心, X 角中心, T 棱中心, C 角块, M 中棱, W 翼棱
  var SLOTS = [], STICKER_SLOT = new Int16Array(NST), STICKER_INDEX = new Int8Array(NST);
  var TYPES = ['Z', 'C', 'M', 'W', 'X', 'T'];
  (function () {
    var groups = {};
    for (var i = 0; i < NST; i++) {
      var p = POS[i], key = p.join(',');
      (groups[key] = groups[key] || []).push(i);
    }
    Object.keys(groups).forEach(function (key) {
      var st = groups[key], p = POS[st[0]];
      var outer = (Math.abs(p[0]) === 2) + (Math.abs(p[1]) === 2) + (Math.abs(p[2]) === 2);
      var type, ordered;
      if (outer === 3) {
        type = 'C';
        var ref = st.filter(function (s) { return NRM[s][1] !== 0; })[0];
        var others = st.filter(function (s) { return s !== ref; });
        if (dot(cross(NRM[ref], NRM[others[0]]), NRM[others[1]]) < 0) others.reverse();
        ordered = [ref, others[0], others[1]];
      } else if (outer === 2) {
        var inner = p[0] !== 0 && Math.abs(p[0]) !== 2 ? p[0] : (Math.abs(p[1]) !== 2 ? p[1] : p[2]);
        // inner 坐标：非 ±2 的那个分量
        var innerCoord = [0, 1, 2].filter(function (a) { return Math.abs(p[a]) !== 2; })[0];
        inner = p[innerCoord];
        if (inner === 0) {
          type = 'M';
          var r0 = st.filter(function (s) { return NRM[s][1] !== 0; })[0];
          if (r0 === undefined) r0 = st.filter(function (s) { return NRM[s][2] !== 0; })[0];
          ordered = [r0, st[0] === r0 ? st[1] : st[0]];
        } else {
          type = 'W';
          ordered = dot(cross(NRM[st[0]], NRM[st[1]]), p) > 0 ? [st[0], st[1]] : [st[1], st[0]];
        }
      } else {
        var zeros = (p[0] === 0) + (p[1] === 0) + (p[2] === 0);
        type = zeros === 2 ? 'Z' : zeros === 0 ? 'X' : 'T';
        ordered = [st[0]];
      }
      var slot = { id: SLOTS.length, type: type, pos: p, st: ordered };
      slot.home = ordered.map(function (s) { return SOLVED[s]; }).join('');
      ordered.forEach(function (s, idx) { STICKER_SLOT[s] = slot.id; STICKER_INDEX[s] = idx; });
      SLOTS.push(slot);
    });
  })();
  var SLOTS_BY_TYPE = {};
  TYPES.forEach(function (t) { SLOTS_BY_TYPE[t] = SLOTS.filter(function (s) { return s.type === t; }); });
  var TYPE_RANK = { Z: 0, C: 1, M: 2, W: 3, X: 4, T: 5 };

  function slotColors(state, slot) {
    var s = '';
    for (var i = 0; i < slot.st.length; i++) s += state[slot.st[i]];
    return s;
  }

  // ---------- 整体转向 ----------
  var ROTATIONS = (function () {
    var start = { moves: [], perm: identityPerm() }, list = [start], seen = {};
    seen[Array.prototype.join.call(start.perm, ',')] = true;
    for (var i = 0; i < list.length; i++) {
      for (var a = 0; a < 3; a++) {
        var t = { axis: a, lo: 1, hi: 5, q: 1 };
        var mv = list[i].moves.concat(tokenMoves(t));
        var perm = permOf(mv), key = Array.prototype.join.call(perm, ',');
        if (!seen[key]) { seen[key] = true; list.push({ moves: mv, perm: perm }); }
      }
    }
    return list; // 24 个朝向，按 BFS 顺序（步数最少优先）
  })();

  function parity(perm) {
    var n = perm.length, seen = new Array(n), par = 0;
    for (var i = 0; i < n; i++) {
      if (seen[i]) continue;
      var j = i, len = 0;
      while (!seen[j]) { seen[j] = true; j = perm[j]; len++; }
      par ^= (len - 1) & 1;
    }
    return par;
  }

  // ---------- 局面校验 ----------
  function fail(msg) { return { ok: false, error: msg }; }
  function validate(input) {
    var str = String(input == null ? '' : input).replace(/\s+/g, '');
    if (str.length !== NST) return fail('面片串长度应为 150，当前为 ' + str.length + '。');
    if (!/^[URFDLB]+$/.test(str)) return fail('面片串只能包含 U、R、F、D、L、B 六个大写字母。');
    var counts = {};
    for (var i = 0; i < NST; i++) counts[str[i]] = (counts[str[i]] || 0) + 1;
    for (var f = 0; f < 6; f++) if (counts[FACES[f]] !== 25) return fail('每种颜色应有 25 枚面片，' + FACES[f] + ' 有 ' + (counts[FACES[f]] || 0) + ' 枚。');

    var arr = str.split(''), rotation = null, state = null;
    for (var r = 0; r < ROTATIONS.length; r++) {
      var cand = applyMoves(arr, ROTATIONS[r].moves), good = true;
      for (var g = 0; g < 6; g++) if (cand[g * 25 + 12] !== FACES[g]) { good = false; break; }
      if (good) { rotation = ROTATIONS[r]; state = cand; break; }
    }
    if (!rotation) return fail('不可达局面：六个固定中心块的配色不构成合法的魔方配色（对面或手性错误）。');

    // 角块
    var cornerHome = {};
    SLOTS_BY_TYPE.C.forEach(function (s, idx) { cornerHome[s.home] = idx; });
    var cPerm = [], twist = 0, used = {};
    var corners = SLOTS_BY_TYPE.C;
    for (var c = 0; c < corners.length; c++) {
      var col = slotColors(state, corners[c]), found = -1, tw = 0;
      for (var k = 0; k < 3; k++) {
        var rotStr = col.slice(k) + col.slice(0, k);
        if (cornerHome[rotStr] !== undefined) { found = cornerHome[rotStr]; tw = k; break; }
      }
      if (found < 0) {
        var rev = col.split('').reverse().join('');
        for (var k2 = 0; k2 < 3; k2++) if (cornerHome[rev.slice(k2) + rev.slice(0, k2)] !== undefined)
          return fail('不可达局面：存在镜像排列的角块（' + col + '），实物魔方上不可能出现。');
        return fail('不可达局面：角块颜色组合 ' + col + ' 不存在。');
      }
      if (used['c' + found]) return fail('不可达局面：同一个角块出现了两次（' + col + '）。');
      used['c' + found] = true;
      cPerm.push(found); twist += tw;
    }
    if (twist % 3 !== 0) return fail('不可达局面：角块朝向总和不为 0（例如只扭转了一个角块）。');

    // 中棱
    var edgeHome = {};
    SLOTS_BY_TYPE.M.forEach(function (s, idx) { edgeHome[s.home] = idx; });
    var mPerm = [], flip = 0;
    var midges = SLOTS_BY_TYPE.M;
    for (var e = 0; e < midges.length; e++) {
      var ec = slotColors(state, midges[e]), er = ec[1] + ec[0], id;
      if (edgeHome[ec] !== undefined) id = edgeHome[ec];
      else if (edgeHome[er] !== undefined) { id = edgeHome[er]; flip++; }
      else return fail('不可达局面：中棱颜色组合 ' + ec + ' 不存在。');
      if (used['m' + id]) return fail('不可达局面：同一个中棱出现了两次（' + ec + '）。');
      used['m' + id] = true;
      mPerm.push(id);
    }
    if (flip % 2 !== 0) return fail('不可达局面：中棱翻转数为奇数（例如只翻转了一个中棱）。');
    if (parity(cPerm) !== parity(mPerm)) return fail('不可达局面：角块与中棱的排列奇偶性不一致（例如只交换了两个中棱）。');

    // 翼棱
    var wingHome = {};
    SLOTS_BY_TYPE.W.forEach(function (s, idx) { wingHome[s.home] = idx; });
    var wings = SLOTS_BY_TYPE.W;
    for (var w = 0; w < wings.length; w++) {
      var wc = slotColors(state, wings[w]);
      if (wingHome[wc] === undefined) {
        if (wingHome[wc[1] + wc[0]] !== undefined) return fail('不可达局面：翼棱 ' + wc + ' 方向不可能（翼棱无法在原位翻转）。');
        return fail('不可达局面：翼棱颜色组合 ' + wc + ' 不存在。');
      }
      if (used['w' + wingHome[wc]]) return fail('不可达局面：同一个翼棱出现了两次（' + wc + '）。');
      used['w' + wingHome[wc]] = true;
    }

    // 中心块数量
    var ctypes = ['X', 'T'], cname = { X: '角中心', T: '棱中心' };
    for (var ct = 0; ct < 2; ct++) {
      var cc = {};
      SLOTS_BY_TYPE[ctypes[ct]].forEach(function (s) { var x = state[s.st[0]]; cc[x] = (cc[x] || 0) + 1; });
      for (var f2 = 0; f2 < 6; f2++) if (cc[FACES[f2]] !== 4)
        return fail('不可达局面：' + cname[ctypes[ct]] + '中 ' + FACES[f2] + ' 色应有 4 枚，实际 ' + (cc[FACES[f2]] || 0) + ' 枚。');
    }
    return { ok: true, facelets: str, rotation: rotation.moves.slice(), oriented: state.join('') };
  }

  function isSolved(state) {
    for (var i = 0; i < NST; i++) if (state[i] !== SOLVED[i]) return false;
    return true;
  }

  // ---------- 自生成的三循环表 ----------
  // 每个 3-循环用一组面片 (p,s,q) 表示：p 处面片到 s，s 处到 q，q 处回到 p，同块其余面片刚性跟随。
  var TABLES = null;
  function keyOf(p, s, q) { return (p * NST + s) * NST + q; }
  function cycleKeys(p, s, q) {
    var P = SLOTS[STICKER_SLOT[p]], S = SLOTS[STICKER_SLOT[s]], Q = SLOTS[STICKER_SLOT[q]];
    var n = P.st.length, ip = STICKER_INDEX[p], is = STICKER_INDEX[s], iq = STICKER_INDEX[q], out = [];
    for (var k = 0; k < n; k++) {
      var a = P.st[(ip + k) % n], b = S.st[(is + k) % n], c = Q.st[(iq + k) % n];
      out.push(keyOf(a, b, c), keyOf(b, c, a), keyOf(c, a, b));
    }
    return out;
  }

  function makeYield() {
    if (typeof MessageChannel !== 'undefined' && typeof window !== 'undefined') {
      var ch = new MessageChannel(), queue = [];
      ch.port1.onmessage = function () { var f = queue.shift(); if (f) f(); };
      return function () { return new Promise(function (r) { queue.push(r); ch.port2.postMessage(0); }); };
    }
    return function () { return new Promise(function (r) { setTimeout(r, 0); }); };
  }
  var CANCELLED = { cancelled: true };
  function checkCancel(ctl) { if (ctl && ctl.cancelled && ctl.cancelled()) throw CANCELLED; }

  async function buildTables(ctl) {
    if (TABLES) return TABLES;
    var yieldNow = makeYield();
    var tables = {}, cycles = {};
    TYPES.forEach(function (t) { if (t !== 'Z') { tables[t] = new Map(); cycles[t] = []; } });

    function register(type, p, s, q, alg) {
      var keys = cycleKeys(p, s, q), map = tables[type];
      if (map.has(keys[0])) {
        var old = cycles[type][map.get(keys[0])];
        if (old.alg.length <= alg.length) return -1;
      }
      var idx = cycles[type].length;
      cycles[type].push({ p: p, s: s, q: q, alg: alg });
      for (var i = 0; i < keys.length; i++) map.set(keys[i], idx);
      return idx;
    }

    // 1) 交换子搜索：[A, c x c']，A、c、x 为单层转动；按类型保留纯 3-循环
    var Bs = [];
    for (var x = 0; x < NMOVES; x++) Bs.push([x]);
    for (var c = 0; c < NMOVES; c++) for (var x2 = 0; x2 < NMOVES; x2++)
      if (MOVES[c].axis !== MOVES[x2].axis) Bs.push([c, x2, MOVES[c].inv]);
    var bPerm = Bs.map(permOf);
    var bInvPerm = Bs.map(function (b) { return permOf(invertMoves(b)); });
    var counter = 0;
    for (var A = 0; A < NMOVES; A++) {
      var Ainv = MOVES[A].inv;
      for (var bi = 0; bi < Bs.length; bi++) {
        if (MOVES[A].axis === MOVES[Bs[bi][Bs[bi].length === 1 ? 0 : 1]].axis && Bs[bi].length === 1) continue;
        if ((++counter & 2047) === 0) { await yieldNow(); checkCancel(ctl); }
        // perm = A · B · A' · B'
        var p1 = MOVES[A].src, pb = bPerm[bi], pbi = bInvPerm[bi], pai = MOVES[Ainv].src;
        var perm = new Int16Array(NST), moved = 0, ok = true, minRank = 9, slotsMoved = {};
        for (var k = 0; k < NST; k++) {
          var v = p1[pb[pai[pbi[k]]]];
          perm[k] = v;
        }
        for (var k2 = 0; k2 < NST; k2++) {
          if (perm[k2] !== k2) {
            var sl = SLOTS[STICKER_SLOT[k2]], rk = TYPE_RANK[sl.type];
            if (rk < minRank) minRank = rk;
            slotsMoved[sl.id] = rk;
            moved++;
          }
        }
        if (!moved || minRank === 0) continue;
        var own = [];
        for (var sid in slotsMoved) if (slotsMoved[sid] === minRank) own.push(+sid);
        if (own.length !== 3) continue;
        // dest[i]：位置 i 的面片去向
        var dest = new Int16Array(NST);
        for (var k3 = 0; k3 < NST; k3++) dest[perm[k3]] = k3;
        var p0 = SLOTS[own[0]].st[0], s0 = dest[p0], q0 = dest[s0];
        if (dest[q0] !== p0) continue;
        var sa = STICKER_SLOT[p0], sb = STICKER_SLOT[s0], sc = STICKER_SLOT[q0];
        if (sa === sb || sb === sc || sa === sc) continue;
        // 校验刚性：同块其他面片按偏移映射
        var type = TYPES[minRank], rigid = true;
        var keys = cycleKeys(p0, s0, q0);
        for (var kk = 0; kk < keys.length && rigid; kk++) {
          var key = keys[kk], a0 = Math.floor(key / (NST * NST)), b0 = Math.floor(key / NST) % NST;
          if (dest[a0] !== b0) rigid = false;
        }
        if (!rigid) continue;
        var alg = [A].concat(Bs[bi], [Ainv], invertMoves(Bs[bi]));
        register(type, p0, s0, q0, alg);
        // 逆循环
        register(type, p0, q0, s0, invertMoves(alg));
      }
    }

    // 2) 共轭 BFS：m · C · m'，补全所有三元组
    for (var ti = 1; ti < TYPES.length; ti++) {
      var type2 = TYPES[ti], list = cycles[type2], map2 = tables[type2];
      list.sort(function (a, b) { return a.alg.length - b.alg.length; });
      map2.clear();
      var fresh = list.splice(0, list.length);
      fresh.forEach(function (cy) { register(type2, cy.p, cy.s, cy.q, cy.alg); });
      for (var head = 0; head < list.length; head++) {
        if ((head & 255) === 0) { await yieldNow(); checkCancel(ctl); }
        var cyc = list[head];
        for (var m = 0; m < NMOVES; m++) {
          var di = MOVES[MOVES[m].inv].dest;
          var np = di[cyc.p], ns = di[cyc.s], nq = di[cyc.q];
          if (map2.has(keyOf(np, ns, nq))) continue;
          register(type2, np, ns, nq, [m].concat(cyc.alg, [MOVES[m].inv]));
        }
      }
    }
    TABLES = { tables: tables, cycles: cycles };
    return TABLES;
  }

  function lookup(type, p, s, q) {
    var idx = TABLES.tables[type].get(keyOf(p, s, q));
    return idx === undefined ? null : TABLES.cycles[type][idx];
  }

  // ---------- 求解 ----------
  function permParity(state, type) {
    var slots = SLOTS_BY_TYPE[type], home = {}, perm = [];
    slots.forEach(function (s, i) {
      home[type === 'W' ? s.home : s.home.split('').sort().join('')] = i;
    });
    slots.forEach(function (s) {
      var c = slotColors(state, s);
      perm.push(home[type === 'W' ? c : c.split('').sort().join('')]);
    });
    return parity(perm);
  }

  function solveDistinct(ctx, type) {
    var slots = SLOTS_BY_TYPE[type];
    var sorted = function (s) { return s.split('').sort().join(''); };
    var same = type === 'W' ? function (a, b) { return a === b; } : function (a, b) { return sorted(a) === sorted(b); };
    var locked = {};
    function solved(slot) { return slotColors(ctx.state, slot) === slot.home; }
    function findPiece(S) {
      for (var i = 0; i < slots.length; i++) if (same(slotColors(ctx.state, slots[i]), S.home)) return slots[i];
      throw new Error('内部错误：找不到块 ' + S.home);
    }
    var progress = true;
    while (progress) {
      progress = false;
      for (var i = 0; i < slots.length; i++) {
        var S = slots[i];
        if (locked[S.id]) continue;
        if (solved(S)) { locked[S.id] = true; progress = true; continue; }
        var P = findPiece(S);
        if (P === S) continue;
        var p = P.st.filter(function (x) { return ctx.state[x] === S.home[0]; })[0];
        var best = null;
        for (var j = 0; j < slots.length; j++) {
          var Q = slots[j];
          if (Q === S || Q === P || locked[Q.id]) continue;
          for (var t = 0; t < Q.st.length; t++) {
            var cy = lookup(type, p, S.st[0], Q.st[t]);
            if (cy && (!best || cy.alg.length < best.alg.length)) best = cy;
          }
        }
        if (!best) throw new Error('内部错误：' + type + ' 缺少可用三循环');
        ctx.apply(best.alg);
        locked[S.id] = true;
        progress = true;
      }
    }
    // 原位朝向错误的块：两个三循环组合修正
    var guard = 0;
    while (true) {
      var bad = slots.filter(function (s) { return !solved(s); });
      if (!bad.length) break;
      if (bad.length < 2 || ++guard > 20) throw new Error('内部错误：' + type + ' 朝向无法修正');
      var A = bad[0], B = bad[1], done = false;
      for (var ci = 0; ci < slots.length && !done; ci++) {
        var C = slots[ci];
        if (C === A || C === B) continue;
        for (var a1 = 0; a1 < A.st.length && !done; a1++) for (var b1 = 0; b1 < B.st.length && !done; b1++)
          for (var c1 = 0; c1 < C.st.length && !done; c1++) {
            var cy1 = lookup(type, A.st[a1], B.st[b1], C.st[c1]);
            if (!cy1) continue;
            var st1 = applyMoves(ctx.state, cy1.alg);
            for (var a2 = 0; a2 < A.st.length && !done; a2++) for (var b2 = 0; b2 < B.st.length && !done; b2++)
              for (var c2 = 0; c2 < C.st.length && !done; c2++) {
                var cy2 = lookup(type, B.st[b2], A.st[a2], C.st[c2]);
                if (!cy2) continue;
                var st2 = applyMoves(st1, cy2.alg);
                if (slotColors(st2, A) !== A.home || slotColors(st2, C) !== C.home) continue;
                var regress = slots.some(function (s) { return s !== B && slotColors(ctx.state, s) === s.home && slotColors(st2, s) !== s.home; });
                if (regress) continue;
                ctx.apply(cy1.alg); ctx.apply(cy2.alg); done = true;
              }
          }
      }
      if (!done) throw new Error('内部错误：' + type + ' 朝向修正失败');
    }
  }

  function solveCenters(ctx, type) {
    var slots = SLOTS_BY_TYPE[type], locked = {};
    var req = function (s) { return SOLVED[s.st[0]]; };
    var col = function (s) { return ctx.state[s.st[0]]; };
    for (var i = 0; i < slots.length; i++) {
      var S = slots[i];
      if (col(S) === req(S)) { locked[S.id] = true; continue; }
      var best = null;
      for (var j = 0; j < slots.length; j++) {
        var P = slots[j];
        if (P === S || locked[P.id] || col(P) !== req(S)) continue;
        for (var k = 0; k < slots.length; k++) {
          var Q = slots[k];
          if (Q === S || Q === P) continue;
          if (locked[Q.id] && req(Q) !== col(S)) continue;
          var cy = lookup(type, P.st[0], S.st[0], Q.st[0]);
          if (cy && (!best || cy.alg.length < best.alg.length)) best = cy;
        }
      }
      if (!best) throw new Error('内部错误：' + type + ' 中心缺少可用三循环');
      ctx.apply(best.alg);
      locked[S.id] = true;
    }
  }

  /*
   * solve(facelets, ctl) -> Promise<string[]>（转动记号序列）
   * ctl.cancelled(): 返回 true 时中止（Promise 以 {cancelled:true} 拒绝）
   */
  async function solve(facelets, ctl) {
    var v = validate(facelets);
    if (!v.ok) throw new Error(v.error);
    var start = v.facelets.split('');
    if (isSolved(start)) return [];
    await buildTables(ctl);
    checkCancel(ctl);
    var ctx = {
      state: start, moves: [],
      apply: function (alg) { this.state = applyMoves(this.state, alg); Array.prototype.push.apply(this.moves, alg); }
    };
    var yieldNow = makeYield();
    // 0. 整体转向，使六个固定中心归位（会实际播放并记录）
    ctx.apply(v.rotation);
    // 1. 角块与中棱的排列奇偶：U 同时改变两者
    if (permParity(ctx.state, 'C')) ctx.apply([moveId(1, 1, 1)]);
    solveDistinct(ctx, 'C'); await yieldNow(); checkCancel(ctl);
    solveDistinct(ctx, 'M'); await yieldNow(); checkCancel(ctl);
    // 2. 翼棱奇偶（含最后一条棱的翼棱奇偶）：2R 单层四分之一圈改变翼棱排列奇偶，不影响角块与中棱
    if (permParity(ctx.state, 'W')) ctx.apply([moveId(0, 2, 1)]);
    solveDistinct(ctx, 'W'); await yieldNow(); checkCancel(ctl);
    // 3. 中心块（中心同色块不可区分，无奇偶限制）
    solveCenters(ctx, 'X'); await yieldNow(); checkCancel(ctl);
    solveCenters(ctx, 'T'); checkCancel(ctl);
    if (!isSolved(ctx.state)) throw new Error('内部错误：求解后未复原');
    var tokens = simplify(ctx.moves).map(formatToken);
    // 独立复核：用记号重放
    if (applyNotation(v.facelets, tokens) !== SOLVED) throw new Error('内部错误：记号重放未复原');
    return tokens;
  }

  // ---------- 打乱 ----------
  function randomScramble(n, rand) {
    rand = rand || Math.random;
    var out = [], lastAxis = -1, hasInner = false, hasOuter = false;
    for (var i = 0; i < n; i++) {
      var a;
      do { a = Math.floor(rand() * 3); } while (a === lastAxis);
      lastAxis = a;
      var kind = rand(), lo, hi;
      if (kind < 0.45) { lo = hi = rand() < 0.5 ? 1 : 5; hasOuter = true; }
      else if (kind < 0.85) { lo = hi = 2 + Math.floor(rand() * 3); hasInner = true; }
      else { if (rand() < 0.5) { lo = 1; hi = 2; } else { lo = 4; hi = 5; } hasOuter = true; hasInner = true; }
      if (i === n - 1 && !hasInner) { lo = hi = 2; }
      if (i === n - 1 && !hasOuter) { lo = hi = 1; }
      out.push(formatToken({ axis: a, lo: lo, hi: hi, q: 1 + Math.floor(rand() * 3) }));
    }
    return out;
  }

  var api = {
    FACES: FACES, SOLVED: SOLVED, POS: POS, NRM: NRM, FACE_OF: FACE_OF, SLOTS: SLOTS,
    MOVES: MOVES, moveId: moveId, applyMoves: applyMoves, invertMoves: invertMoves,
    parseMove: parseMove, formatToken: formatToken, tokenMoves: tokenMoves,
    applyNotation: applyNotation, simplify: simplify,
    validate: validate, isSolved: function (s) { return isSolved(typeof s === 'string' ? s : s.join('')); },
    buildTables: buildTables, solve: solve, randomScramble: randomScramble,
    CANCELLED: CANCELLED,
    _tables: function () { return TABLES; }
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else global.CubeCore = api;
})(typeof window !== 'undefined' ? window : this);
