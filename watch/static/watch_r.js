/* R 页：手机专用「脉冲 / 异动」盯盘页（iPhone 竖屏优先，不考虑电脑）。
 * 数据：/api/pulse_live（与飞书推送同一套脉冲计算）。盘中 15s 刷新，收盘后显示最终结果。
 * 版面：顶部固定条（状态 + S/N/T 互跳）→ 统计条 → 「当前脉冲/异动」大卡（逐只明细）→ 「已脉冲/异动题材」紧凑卡（点开看明细）。
 * 约定：🔥 异动（一波 ≥3 只）、⚡ 脉冲（2 只）；几板 2蓝 3紫 4橙 5+红；直线板彩虹字、一字红、换手灰；只有一波不写波次。 */
(function () {
    var rPmAll = false, rTimer = null, rData = null, rSeen = null, rOpen = {}, rWake = null, rBusy = false, rY = 0;

    function esc(x) { return String(x == null ? '' : x).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;'); }
    function kindHtml(k) {
        if (k === 'zx') return '<i class="r-k r-k-zx">直线</i>';
        if (k === 'yz') return '<i class="r-k r-k-yz">一字</i>';
        if (k === 'hs') return '<i class="r-k r-k-hs">换手</i>';
        return '';
    }
    function lbHtml(n) {
        if (n > 1) return '<b class="r-lb r-lb' + Math.min(n, 5) + '">' + n + '板</b>';
        return '<span class="r-lb0">首板</span>';
    }
    function rowsHtml(stocks, tag) {
        return stocks.map(function (s) {
            var fresh = rSeen && !rSeen[tag + s.code] ? ' r-new' : '';
            return '<div class="r-row r-st' + fresh + '" data-code="' + s.code + '" data-name="' + esc(s.name) + '"><span class="r-t">' + s.t + '</span><span class="r-n">' + esc(s.name) + '</span>' +
                '<span class="r-bd">' + s.board + '</span>' + lbHtml(s.lb) + '<span class="r-kc">' + kindHtml(s.kind) + '</span></div>';
        }).join('');
    }
    function chipsHtml(stocks) {
        return stocks.map(function (s) {
            return '<span class="r-chip r-st" data-code="' + s.code + '" data-name="' + esc(s.name) + '">' + esc(s.name) + (s.lb > 1 ? '<b class="r-lb r-lb' + Math.min(s.lb, 5) + '">' + s.lb + '</b>' : '') +
                (s.kind === 'zx' ? '<i class="r-k r-k-zx r-k-s">直线</i>' : s.kind === 'yz' ? '<i class="r-k r-k-yz r-k-s">一字</i>' : '') + (s.zb ? '<i class="r-zb r-zb-b">炸</i>' : s.zbn ? '<i class="r-zb">炸' + s.zbn + '</i>' : '') + '</span>';
        }).join('');
    }

    /* 时间轴图（与首页「属性脉冲」同形：色条=脉冲持续时长，圆点=每只涨停时刻，名称顺着点往下排成阶梯；手机版按本题材时间段放大，自带刻度） */
    function pts(sec) { return sec >= 46800 ? sec - 5400 : (sec > 41400 ? 41400 : sec); }
    function clockOf(ts) {
        var s = ts > 41400 ? ts + 5400 : ts, h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60;
        return (h < 10 ? '0' : '') + h + ':' + (m < 10 ? '0' : '') + m;
    }
    function zbHtml(s) {
        if (s.zb) return '<i class="r-zb r-zb-b">炸板</i>';
        if (s.zbn) return '<i class="r-zb" title="炸板后回封">炸' + s.zbn + '</i>';
        return '';
    }
    function chartHtml(waves, color, full, tag) {
        var all = [];
        waves.forEach(function (w) { w.stocks.forEach(function (s) { all.push({s: s, ts: pts(s.sec), w: w}); }); });
        if (!all.length) return '';
        all.sort(function (a, b) { return a.ts - b.ts || (a.s.code < b.s.code ? -1 : 1); });
        var lo = Math.max(33900, all[0].ts - 300), hi = Math.min(48600, all[all.length - 1].ts + 300);
        if (hi - lo < 2400) { hi = Math.min(48600, lo + 2400); lo = Math.max(33900, hi - 2400); }
        var span = hi - lo, X = function (ts) { return ((ts - lo) / span * 100).toFixed(2); };
        var step = [600, 900, 1800, 3600].filter(function (st) { return span / st <= 6; })[0] || 3600;
        var ticks = '';
        for (var t = Math.ceil(lo / step) * step; t <= hi; t += step) {
            if (t > 41400 && t < 41400 + 1) continue;
            ticks += '<span style="left:' + X(t) + '%">' + clockOf(t) + '</span>';
        }
        var bars = '', dots = '', rows = '', lds = '';
        waves.forEach(function (w) {
            if (!w.stocks.length) return;
            var a = pts(w.stocks[0].sec), b = pts(w.stocks[w.stocks.length - 1].sec);
            var dur = Math.round((b - a) / 60);
            var lx = Number(X(a));
            bars += '<i class="r-tl-bar" style="left:' + X(a) + '%;width:calc(' + (X(b) - X(a)) + '% + 6px)"></i>' +
                '<em class="r-tl-lb" style="left:min(' + lx + '%, calc(100% - 118px))">' + (w.hot ? '🔥' : '⚡') + (waves.length > 1 ? '第' + w.idx + '波 ' : '') + w.n + '只' + (dur >= 1 && waves.length === 1 ? '·' + dur + '分' : '') + '</em>';
        });
        all.forEach(function (o, i) {
            var s = o.s, x = X(o.ts), top = 40 + i * 26;
            dots += '<i class="r-tl-dot' + (s.zb ? ' r-tl-dz' : '') + '" style="left:' + x + '%"></i>';
            if (!full) return;
            var fresh = rSeen && !rSeen[tag + s.code] ? ' r-new' : '';
            lds += '<i class="r-tl-ld" style="left:' + x + '%;top:34px;height:' + (top - 34 + 13) + 'px"></i>';
            rows += '<div class="r-tl-c r-st' + (s.zb ? ' r-c-zb' : '') + fresh + '" data-code="' + s.code + '" data-name="' + esc(s.name) + '" style="top:' + top +
                'px;left:min(' + x + '%, calc(100% - 212px))"><span class="r-t">' + s.t + '</span><span class="r-n">' + esc(s.name) + '</span>' + (s.board === '主' ? '' : '<span class="r-bd">' + s.board + '</span>') +
                lbHtml(s.lb) + '<span class="r-kc">' + kindHtml(s.kind) + zbHtml(s) + '</span></div>';
        });
        var h = full ? 40 + all.length * 26 + 2 : 44;
        return '<div class="r-tl' + (full ? ' r-tl-full' : '') + '" style="height:' + h + 'px;--c:' + color + '"><div class="r-tl-ax">' + ticks + '</div>' + bars + lds + dots + rows + '</div>';
    }
    function curCard(g, live) {
        var ws = g.waves, multi = ws.length > 1, tag = g.theme;
        var liveW = ws.filter(function (w) { return w.live; })[0] || ws[ws.length - 1];
        var ago = liveW.ago != null ? (liveW.ago <= 0 ? '刚刚' : liveW.ago + ' 分钟前') : '';
        var n = ws.reduce(function (a, w) { return a + w.n; }, 0);
        var wave = multi ? '<em class="r-wave">第' + liveW.idx + '波进行中</em>' : '';
        return '<section class="r-card r-cur ' + (g.hot ? 'r-hot' : 'r-plain') + (live ? ' r-live' : '') + '">' +
            '<header><span class="r-ic">' + (g.hot ? '🔥' : '⚡') + '</span><h3 class="r-go" data-th="' + esc(g.theme) + '">' + esc(g.theme) + '<u>↓</u></h3>' + wave + '<span class="r-cnt">' + n + '只</span></header>' +
            '<div class="r-sub"><span>' + ws[0].t0 + ' → ' + ws[ws.length - 1].t1 + '</span>' + (live ? '<span class="r-ago"><i class="r-dot"></i>进行中' + (ago ? ' · 最近一只 ' + ago : '') + '</span>' : '') + '</div>' +
            chartHtml(ws, g.hot ? '#ffa726' : '#7aa2e8', true, tag) + '</section>';
    }
    // 当前进行中的波 + 同题材已结束的波 → 一个题材一张卡（多波放同一张），并从下面「已脉冲」里去掉
    function groupCurrent(d) {
        var hb = {}; d.history.forEach(function (h) { hb[h.theme] = h; });
        var order = [], by = {};
        d.current.forEach(function (w) { if (!by[w.theme]) { by[w.theme] = []; order.push(w.theme); } by[w.theme].push(Object.assign({live: true}, w)); });
        var groups = order.map(function (th) {
            var ws = by[th].concat(hb[th] ? hb[th].waves.map(function (w) { return Object.assign({live: false}, w); }) : []);
            ws.sort(function (a, b) { return a.idx - b.idx; });
            var liveW = by[th].slice().sort(function (a, b) { return (a.ago || 0) - (b.ago || 0); })[0];
            return {theme: th, waves: ws, hot: by[th].some(function (w) { return w.hot; }), ago: liveW.ago};
        });
        return {groups: groups, rest: d.history.filter(function (h) { return !by[h.theme]; })};
    }
    function hisCard(h, i) {
        var open = rOpen[h.theme] !== false, multi = h.total > 1;
        var body;
        if (open) {
            body = chartHtml(h.waves, '#4fc3b0', true, h.theme);
        } else {
            body = chartHtml(h.waves, '#4fc3b0', false, h.theme) + h.waves.map(function (w) {
                var head = '<div class="r-whead"><span class="r-wic">' + (w.hot ? '🔥' : '⚡') + '</span>' + (multi ? '<em class="r-wave">第' + w.idx + '波</em>' : '') +
                    '<span class="r-wt">' + w.t0 + '~' + w.t1 + '</span><span class="r-cnt">' + w.n + '只</span></div>';
                return '<div class="r-wave-blk' + (multi ? '' : ' r-single') + '">' + head + '<div class="r-chips">' + chipsHtml(w.stocks) + '</div></div>';
            }).join('');
        }
        return '<section class="r-card r-his ' + (h.hot ? 'r-hhot' : 'r-hplain') + (open ? ' r-open' : '') + '" id="rh-' + i + '" data-th="' + esc(h.theme) + '">' +
            '<header><span class="r-ic">' + (h.hot ? '🔥' : '⚡') + '</span><h3 class="r-go" data-th="' + esc(h.theme) + '">' + esc(h.theme) + '<u>↓</u></h3><span class="r-arrow">' + (open ? '收起' : '时间轴') + '</span></header>' + body + '</section>';
    }
    function pctHtml(p) {
        if (p == null || isNaN(p)) return '';
        p = Number(p); return '<i class="r-pc ' + (p >= 0 ? 'r-up' : 'r-dn') + '">' + (p >= 0 ? '+' : '') + p.toFixed(1) + '%</i>';
    }
    function pmCard(th) {
        var chips = th.stocks.map(function (s) {
            return '<span class="r-chip r-st" data-code="' + s.code + '" data-name="' + esc(s.name) + '">' + esc(s.name) +
                (s.lb > 1 ? '<b class="r-lb r-lb' + Math.min(s.lb, 5) + '">' + s.lb + '</b>' : '') + (s.t ? '<small>' + s.t + '</small>' : '') + '</span>';
        }).join('');
        var fail = '', gem = '';
        if (th.fail.length) {
            var f6 = th.fail.slice(0, 8).map(function (f) {
                return '<span class="r-chip r-chip-f r-st" data-code="' + f.code + '" data-name="' + esc(f.name) + '">' + esc(f.name) + '<small>昨' + f.lb + '板</small>' + pctHtml(f.pct) + '</span>';
            }).join('');
            fail = '<div class="r-pl"><em class="r-tag r-tag-f">晋级失败 ' + th.fail.length + '</em><div class="r-chips">' + f6 + (th.fail.length > 8 ? '<span class="r-more">+' + (th.fail.length - 8) + '</span>' : '') + '</div></div>';
        }
        if (th.gem.length) {
            gem = '<div class="r-pl"><em class="r-tag r-tag-g">创/科大涨</em><div class="r-chips">' + th.gem.map(function (g) {
                return '<span class="r-chip r-st" data-code="' + g.code + '" data-name="' + esc(g.name) + '">' + esc(g.name) + '<small>' + esc(g.board) + '</small>' + pctHtml(g.pct) + '</span>';
            }).join('') + '</div></div>';
        }
        return '<section class="r-card r-pm" data-pth="' + esc(th.theme) + '"><header><h3>' + esc(th.theme) + '</h3>' + (th.is_new ? '<em class="r-new">NEW</em>' : '') +
            (th.promo >= 2 ? '<b class="r-lb r-lb' + Math.min(th.promo, 5) + '">' + th.promo + '板</b>' : '') + '<span class="r-cnt">涨停 ' + th.cnt + '</span></header>' +
            '<div class="r-chips">' + chips + '</div>' + fail + gem + '</section>';
    }
    function promoHtml(pm) {
        var list = (pm && pm.themes) || [];
        if (!list.length) return '';
        var show = rPmAll ? list : list.slice(0, 10);
        return '<h2 class="r-h r-h3">📈 细分题材晋级 · ' + esc((pm.date || '').slice(5)) + ' <small>' + list.length + ' 个题材</small></h2>' + show.map(pmCard).join('') +
            (list.length > 10 ? '<button type="button" class="r-pmbtn" data-pm="1">' + (rPmAll ? '收起' : '展开全部 ' + list.length + ' 个题材') + '</button>' : '');
    }
    function goPromo(name) {                          // 点上面的题材名 → 滚到下面「细分题材晋级」里同名题材并闪一下
        var list = (rData && rData.promotion && rData.promotion.themes) || [];
        var idx = -1;
        list.some(function (t, i) { if (t.theme === name) { idx = i; return true; } });
        if (idx < 0) list.some(function (t, i) { if (t.theme.indexOf(name) >= 0 || name.indexOf(t.theme) >= 0) { idx = i; return true; } });
        if (idx < 0) { toast('细分题材晋级中暂无「' + name + '」'); return; }
        if (idx >= 10 && !rPmAll) { rPmAll = true; render(); }
        var card = document.querySelector('#watchRRoot .r-pm[data-pth="' + list[idx].theme.replace(/"/g, '\\"') + '"]');
        if (!card) return;
        var topH = (document.querySelector('#watchRRoot .r-top') || {}).offsetHeight || 50;
        window.scrollTo({top: card.getBoundingClientRect().top + window.scrollY - topH - 8, behavior: 'smooth'});
        card.classList.remove('r-flash'); void card.offsetWidth; card.classList.add('r-flash');
    }
    function toast(msg) {
        var t = document.getElementById('rToast');
        if (!t) { t = document.createElement('div'); t.id = 'rToast'; t.className = 'r-toast'; document.body.appendChild(t); }
        t.textContent = msg; t.classList.add('on');
        clearTimeout(t._t); t._t = setTimeout(function () { t.classList.remove('on'); }, 2200);
    }
    function render() {
        var root = document.getElementById('watchRRoot'), d = rData;
        if (!root || !d) return;
        var body = root.querySelector('.r-body');
        var gp = groupCurrent(d), rest = gp.rest;
        var nHot = gp.groups.filter(function (g) { return g.hot; }).length, nPlain = gp.groups.length - nHot;
        var hisHot = rest.filter(function (h) { return h.hot; }).length;
        var st = d.live ? '<span class="r-state r-on"><i class="r-dot"></i>盘中 ' + d.updated + '</span>' : '<span class="r-state">收盘 ' + d.date.slice(5) + '</span>';
        root.querySelector('.r-status').innerHTML = st;
        var stats = '<div class="r-stats"><div><b class="r-s1">' + (nHot + nPlain) + '</b><small>当前进行中</small></div>' +
            '<div><b class="r-s2">' + (nHot + hisHot) + '</b><small>🔥 异动题材</small></div>' +
            '<div><b class="r-s3">' + rest.length + '</b><small>已结束题材</small></div></div>';
        var cur = '<h2 class="r-h r-h1">● 当前脉冲/异动</h2>' + (gp.groups.length ? gp.groups.map(function (g) { return curCard(g, d.live); }).join('') :
            '<div class="r-empty">' + (d.live ? '暂无进行中的脉冲' : '已收盘') + '</div>');
        var jump = rest.length > 1 ? '<div class="r-jump">' + rest.map(function (h, i) {
            return '<button type="button" class="r-jmp' + (h.hot ? ' r-jhot' : '') + '" data-hi="' + i + '">' + (h.hot ? '🔥' : '⚡') + esc(h.theme) + '</button>';
        }).join('') + '</div>' : '';
        var his = '<h2 class="r-h r-h2">✅ 已脉冲/异动题材</h2>' + jump + (rest.length ? rest.map(function (h, i) { return hisCard(h, i); }).join('') : '<div class="r-empty">暂无</div>');
        body.innerHTML = stats + cur + his + promoHtml(d.promotion);
        // 记住已展示过的票，下一次刷新时新出现的闪一下
        var seen = {};
        gp.groups.forEach(function (g) { g.waves.forEach(function (w) { w.stocks.forEach(function (s) { seen[g.theme + s.code] = 1; }); }); });
        rest.forEach(function (h) { h.waves.forEach(function (w) { w.stocks.forEach(function (s) { seen[h.theme + s.code] = 1; }); }); });
        rSeen = seen;
    }
    function load() {
        if (rBusy) return;
        rBusy = true;
        fetch('/api/pulse_live?_t=' + Date.now()).then(function (r) { return r.json(); }).then(function (d) {
            rBusy = false;
            if (!d || d.error) return;
            rData = d; render();
        }).catch(function () { rBusy = false; });
    }
    function schedule() {
        clearTimeout(rTimer);
        var root = document.getElementById('watchRRoot');
        if (!root || root.style.display === 'none') return;
        if (rData && rData.active === false) {               // 收盘 1 小时后停止刷新，睡到下一个交易日竞价（9:15）再继续；每段最多睡 1 小时
            rTimer = setTimeout(function () { load(); schedule(); }, Math.min(3600, Math.max(30, rData.resume_in || 3600)) * 1000 + 2000);
            return;
        }
        rTimer = setTimeout(function () { load(); schedule(); }, rData && rData.live ? 15000 : 30000);
    }
    function wake() {
        try { if (navigator.wakeLock && !rWake) navigator.wakeLock.request('screen').then(function (l) { rWake = l; l.addEventListener('release', function () { rWake = null; }); }).catch(function () {}); } catch (e) {}
    }
    document.addEventListener('visibilitychange', function () {
        var root = document.getElementById('watchRRoot');
        if (document.visibilityState === 'visible' && root && root.style.display !== 'none') { wake(); load(); schedule(); }
    });
    window.watchOpenR = function () {
        var main = document.getElementById('watchRoot'), back = document.getElementById('watchBackNav');
        var root = document.getElementById('watchRRoot');
        if (!root) {
            root = document.createElement('div');
            root.id = 'watchRRoot';
            root.innerHTML = '<div class="r-top"><button type="button" class="r-back" onclick="watchCloseR()">‹ 盯盘</button><b class="r-title">R 脉冲·异动</b>' +
                '<span class="r-status"></span></div>' +
                '<div class="r-body"><div class="r-empty">加载中…</div></div>';
            root.addEventListener('click', function (e) {
                var gt = e.target.closest && e.target.closest('.r-go');
                if (gt) { e.stopPropagation(); goPromo(gt.getAttribute('data-th')); return; }
                var jb = e.target.closest && e.target.closest('.r-jmp');
                if (jb) {                                   // 导航栏：跳到对应的已异动题材卡并闪一下
                    e.stopPropagation();
                    var tc = document.getElementById('rh-' + jb.getAttribute('data-hi'));
                    if (tc) {
                        var th0 = (document.querySelector('#watchRRoot .r-top') || {}).offsetHeight || 50;
                        window.scrollTo({top: tc.getBoundingClientRect().top + window.scrollY - th0 - 8, behavior: 'smooth'});
                        tc.classList.remove('r-flash'); void tc.offsetWidth; tc.classList.add('r-flash');
                    }
                    return;
                }
                if (e.target.closest && e.target.closest('.r-pmbtn')) { rPmAll = !rPmAll; render(); return; }
                var st = e.target.closest && e.target.closest('.r-st');
                if (st) {                                   // 点股票：与 N 页一致的个股弹框（上一只/下一只 = 同一波里的票）
                    e.stopPropagation();
                    var blk = st.closest('.r-wave-blk') || st.closest('.r-tl') || st.closest('.r-cur') || st.closest('.r-pm') || st.parentNode, nav = [], idx = -1;
                    [].forEach.call(blk.querySelectorAll('.r-st'), function (el) {
                        if (el === st) idx = nav.length;
                        nav.push({code: el.getAttribute('data-code'), name: el.getAttribute('data-name')});
                    });
                    if (window.openDsStockFromRhythm) openDsStockFromRhythm(st.getAttribute('data-name'), st.getAttribute('data-code'), '', nav, idx);
                    return;
                }
                var card = e.target.closest && e.target.closest('.r-his');
                if (!card) return;
                var th = card.getAttribute('data-th'); rOpen[th] = rOpen[th] === false; render();
            });
            document.querySelector('.container').appendChild(root);
        }
        if (main && main.style.display !== 'none') rY = window.scrollY;
        if (main) main.style.display = 'none';
        if (back) back.style.display = 'none';
        if (window.watchFloatNavShow) watchFloatNavShow(false);
        root.style.display = '';
        window.scrollTo(0, 0);
        wake(); load(); schedule();
    };
    window.watchRGo = function (k) {                 // 独立链接 /r 下，N/T/S 是另一个页面：整页跳到 /?go=X
        if (window.__watchROnly) location.href = '/?go=' + k; else watchGoPage(k);
    };
    window.watchCloseR = function () {
        if (window.__watchROnly) { location.href = '/'; return; }
        var root = document.getElementById('watchRRoot'), main = document.getElementById('watchRoot'), back = document.getElementById('watchBackNav');
        if (root) root.style.display = 'none';
        clearTimeout(rTimer);
        if (main) main.style.display = '';
        if (back) back.style.display = '';
        if (window.watchFloatNavShow) watchFloatNavShow(true);
        window.scrollTo(0, rY || 0);
    };
})();
