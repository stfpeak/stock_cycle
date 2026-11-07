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
                (s.kind === 'zx' ? '<i class="r-k r-k-zx r-k-s">直线</i>' : s.kind === 'yz' ? '<i class="r-k r-k-yz r-k-s">一字</i>' : '') + '</span>';
        }).join('');
    }
    function curCard(w, live) {
        var wave = w.total > 1 ? '<em class="r-wave">第' + w.idx + '波</em>' : '';
        var ago = w.ago != null ? (w.ago <= 0 ? '刚刚' : w.ago + ' 分钟前') : '';
        return '<section class="r-card r-cur ' + (w.hot ? 'r-hot' : 'r-plain') + (live ? ' r-live' : '') + '">' +
            '<header><span class="r-ic">' + (w.hot ? '🔥' : '⚡') + '</span><h3 class="r-go" data-th="' + esc(w.theme) + '">' + esc(w.theme) + '<u>↓</u></h3>' + wave + '<span class="r-cnt">' + w.n + '只</span></header>' +
            '<div class="r-sub"><span>' + w.t0 + ' → ' + w.t1 + '</span>' + (live ? '<span class="r-ago"><i class="r-dot"></i>进行中' + (ago ? ' · 最近一只 ' + ago : '') + '</span>' : '') + '</div>' +
            '<div class="r-rows">' + rowsHtml(w.stocks, w.theme + w.idx) + '</div></section>';
    }
    function hisCard(h) {
        var open = !!rOpen[h.theme], multi = h.total > 1;
        var body = h.waves.map(function (w) {
            var head = '<div class="r-whead"><span class="r-wic">' + (w.hot ? '🔥' : '⚡') + '</span>' + (multi ? '<em class="r-wave">第' + w.idx + '波</em>' : '') +
                '<span class="r-wt">' + w.t0 + '~' + w.t1 + '</span><span class="r-cnt">' + w.n + '只</span></div>';
            return '<div class="r-wave-blk' + (multi ? '' : ' r-single') + '">' + head + (open ? '<div class="r-rows">' + rowsHtml(w.stocks, h.theme + w.idx) + '</div>' : '<div class="r-chips">' + chipsHtml(w.stocks) + '</div>') + '</div>';
        }).join('');
        return '<section class="r-card r-his ' + (h.hot ? 'r-hhot' : 'r-hplain') + (open ? ' r-open' : '') + '" data-th="' + esc(h.theme) + '">' +
            '<header><span class="r-ic">' + (h.hot ? '🔥' : '⚡') + '</span><h3 class="r-go" data-th="' + esc(h.theme) + '">' + esc(h.theme) + '<u>↓</u></h3><span class="r-arrow">' + (open ? '收起' : '明细') + '</span></header>' + body + '</section>';
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
        var nHot = 0, nPlain = 0;
        d.current.forEach(function (w) { if (w.hot) nHot++; else nPlain++; });
        var hisHot = d.history.filter(function (h) { return h.hot; }).length;
        var st = d.live ? '<span class="r-state r-on"><i class="r-dot"></i>盘中 ' + d.updated + '</span>' : '<span class="r-state">收盘 ' + d.date.slice(5) + '</span>';
        root.querySelector('.r-status').innerHTML = st;
        var stats = '<div class="r-stats"><div><b class="r-s1">' + (nHot + nPlain) + '</b><small>当前进行中</small></div>' +
            '<div><b class="r-s2">' + (nHot + hisHot) + '</b><small>🔥 异动题材</small></div>' +
            '<div><b class="r-s3">' + d.history.length + '</b><small>已结束题材</small></div></div>';
        var cur = '<h2 class="r-h r-h1">● 当前脉冲/异动</h2>' + (d.current.length ? d.current.map(function (w) { return curCard(w, d.live); }).join('') :
            '<div class="r-empty">' + (d.live ? '暂无进行中的脉冲' : '已收盘') + '</div>');
        var his = '<h2 class="r-h r-h2">✅ 已脉冲/异动题材</h2>' + (d.history.length ? d.history.map(hisCard).join('') : '<div class="r-empty">暂无</div>');
        body.innerHTML = stats + cur + his + promoHtml(d.promotion);
        // 记住已展示过的票，下一次刷新时新出现的闪一下
        var seen = {};
        d.current.forEach(function (w) { w.stocks.forEach(function (s) { seen[w.theme + w.idx + s.code] = 1; }); });
        d.history.forEach(function (h) { h.waves.forEach(function (w) { w.stocks.forEach(function (s) { seen[h.theme + w.idx + s.code] = 1; }); }); });
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
        rTimer = setTimeout(function () { load(); schedule(); }, rData && rData.live ? 15000 : 120000);
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
                if (e.target.closest && e.target.closest('.r-pmbtn')) { rPmAll = !rPmAll; render(); return; }
                var st = e.target.closest && e.target.closest('.r-st');
                if (st) {                                   // 点股票：与 N 页一致的个股弹框（上一只/下一只 = 同一波里的票）
                    e.stopPropagation();
                    var blk = st.closest('.r-wave-blk') || st.closest('.r-cur') || st.closest('.r-pm') || st.parentNode, nav = [], idx = -1;
                    [].forEach.call(blk.querySelectorAll('.r-st'), function (el) {
                        if (el === st) idx = nav.length;
                        nav.push({code: el.getAttribute('data-code'), name: el.getAttribute('data-name')});
                    });
                    if (window.openDsStockFromRhythm) openDsStockFromRhythm(st.getAttribute('data-name'), st.getAttribute('data-code'), '', nav, idx);
                    return;
                }
                var card = e.target.closest && e.target.closest('.r-his');
                if (!card) return;
                var th = card.getAttribute('data-th'); rOpen[th] = !rOpen[th]; render();
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
