/* N 页（今日涨停时间轴右上角「N」进入）：复刻 6688 盯盘页「涨停板数量 TOP10」到「其他板块」。
 * 不复制渲染代码：直接复用主页面里的 _tmmTodayTop10Card / _tmmZone / _tmmFilterPlates 等，
 * 仅把 _tmmRender 换成只输出这一段的版本，主页面的实时涨幅刷新 / 折叠记忆 / 过滤逻辑原样生效。 */
(function () {
    var nScrollY = 0, nTimer = null;

    window._tmmRender = function (data) {
        if (!data || data.error || !data.ok) {
            return '<div style="padding:6px;color:#e94560;font-size:0.8em;">' + _kplEsc((data && data.error) || '无数据') + '</div>';
        }
        _tmmThemeKlineOrder = {};
        _tmmThemeKlineSeq = 0;
        var plates = [];
        ['attack', 'defense', 'neutral'].forEach(function (z) {
            _tmmFilterPlates(data[z] || []).forEach(function (p) { p._z = z; plates.push(p); });
        });
        // 档位 = 板块内「今日涨停」股票的最高连板数（高板在前：4+ → 4 → 3 → 2 → 首板，今日无涨停的垫底）；
        // 档内：今日涨停只数多的在前，再按最小断板天数。名为「其他」的兜底板块固定放最后。
        plates.forEach(function (p) {
            var lb = 0, brk = 999;
            (p.themes || []).forEach(function (t) {
                (t.stocks || []).forEach(function (s) {
                    if (s.is_today) { var n = s.lianban >= 2 ? s.lianban : 1; if (n > lb) lb = n; }
                    if (typeof s.break_days === 'number' && s.break_days < brk) brk = s.break_days;
                });
            });
            p._lb = lb; p._brk = brk;
        });
        plates.sort(function (a, b) {
            return ((a.name === '其他') - (b.name === '其他')) || (b._lb - a._lb) || ((b.today_count || 0) - (a.today_count || 0)) || (a._brk - b._brk);
        });
        var top = _tmmTodayTop10Card(data).replace(/<b>(首板|(\d+)连板)<\/b>/g, function (m, t, n) {
            var k = n ? Math.min(+n, 4) : 1;
            return '<b class="n-lb n-lb' + k + '">' + t + '</b>';
        });
        var matched = 0;
        plates.forEach(function (p) { matched += p.count; });
        var h = '<div class="tmm-box">' + _tmmFilterBar(matched) + top + '<div class="tmm-zone"><div class="tmm-zone-body"><div class="tmm-cards">';
        plates.forEach(function (p) { h += _tmmCard(p, 'defense'); });
        h += '</div></div></div>';
        return h + '</div>';
    };

    // 股票卡片涨跌幅：第一行 = 今日（盘中实时 / 收盘后=收盘价涨跌幅；盘前与休市=最近交易日收盘），第二行 = 昨日。
    // 行情改用 /api/spot_quotes（新浪，与 T 页同源；6688 原页用的 levistock 在本机常取不到）。
    function bjToday() { return new Date().toLocaleDateString('sv-SE', {timeZone: 'Asia/Shanghai'}); }
    var origStock = window._tmmStock;
    window._tmmStock = function (s) {
        var live = _tmmIsSessionNow(), s2 = s;
        if (s.quote_change_pct == null && !live && s.p1 != null) s2 = Object.assign({}, s, {quote_change_pct: s.p1});
        if (!live && s.p1_date && s.p1_date < bjToday() && s.p_prev != null) {
            if (s2 === s) s2 = Object.assign({}, s);
            s2.p2 = s.p_prev;
        }
        return origStock(s2);
    };
    var quoting = false;
    function refreshQuotes() {
        if (!_tmmData || quoting) return;
        var codes = [], seen = {};
        ['attack', 'defense', 'neutral'].forEach(function (k) {
            (_tmmData[k] || []).forEach(function (p) { (p.themes || []).forEach(function (t) { (t.stocks || []).forEach(function (s) {
                if (s.code && !seen[s.code]) { seen[s.code] = 1; codes.push(s.code); }
            }); }); });
        });
        var data = _tmmData, batches = [], quotes = {}, next = 0;
        for (var i = 0; i < codes.length; i += 250) batches.push(codes.slice(i, i + 250));
        quoting = true;
        function worker() {
            if (next >= batches.length) return Promise.resolve();
            var b = batches[next++];
            return fetch('/api/spot_quotes?codes=' + b.join(',') + '&_t=' + Date.now()).then(function (r) { return r.json(); }).then(function (q) {
                Object.keys(q || {}).forEach(function (c) { if (q[c] && typeof q[c].change_pct === 'number') quotes[c] = q[c].change_pct; });
            }).catch(function () {}).then(worker);
        }
        Promise.all([worker(), worker(), worker()]).then(function () {
            quoting = false;
            if (_tmmData !== data || !Object.keys(quotes).length) return;
            ['attack', 'defense', 'neutral'].forEach(function (k) {
                (data[k] || []).forEach(function (p) { (p.themes || []).forEach(function (t) { (t.stocks || []).forEach(function (s) {
                    if (quotes[s.code] !== undefined) s.quote_change_pct = quotes[s.code];
                }); }); });
            });
            draw(data);
        }).catch(function () { quoting = false; });
    }
    window._tmmRefreshAllQuotes = function () { refreshQuotes(); };

    // ===== 过滤条：连板数 5+（原为 1~6 + 7+）；断板天数改为 1~10 / 10+ 数字按钮（≤N 天；10+ = 不限） =====
    window._tmmEnsureLbKeys = function () {
        for (var k = 1; k <= 4; k++) if (_tmmFilter.lbs[k] === undefined) _tmmFilter.lbs[k] = true;
        [5, 6, 7, 8, 9, 10].forEach(function (k) { delete _tmmFilter.lbs[k]; });
        if (typeof _tmmFilter.lbPlus7 !== 'boolean') _tmmFilter.lbPlus7 = true;      // lbPlus7 在 N 页含义 = 5+
    };
    window._tmmMatch = function (s) {
        if (!_tmmFilterInit) return true;
        if (!_tmmFilter.boards[s.board || '主']) return false;
        var lb = s.lianban >= 2 ? s.lianban : 1;
        if (lb >= 5) { if (!_tmmFilter.lbPlus7) return false; }
        else if (!_tmmFilter.lbs[lb]) return false;
        if (_tmmFilter.maxBreak !== null && s.break_days > _tmmFilter.maxBreak) return false;
        return true;
    };
    window._tmmFilterBar = function (matched) {
        var h = '<div class="tmm-filter"><span class="tmm-f-group"><b>市场</b>';
        ['主', '创', '科'].forEach(function (b) {
            h += '<span class="tmm-f-chip' + (_tmmFilter.boards[b] ? '' : ' off') + '" onclick="tmmToggleBoard(\x27' + b + '\x27)">' + b + '</span>';
        });
        h += '</span><span class="tmm-f-group"><b>连板数</b>';
        for (var i = 1; i <= 4; i++) h += '<span class="tmm-f-chip' + (_tmmFilter.lbs[i] ? '' : ' off') + '" onclick="tmmToggleLb(' + i + ')">' + i + '</span>';
        h += '<span class="tmm-f-chip' + (_tmmFilter.lbPlus7 ? '' : ' off') + '" onclick="tmmToggleLb7Plus()">5+</span></span>';
        h += '<span class="tmm-f-group"><b>断板天数</b> ≤ ';
        for (var d = 1; d <= 10; d++) h += '<span class="tmm-f-chip n-brk' + (_tmmFilter.maxBreak === d ? '' : ' off') + '" onclick="tmmSetBreak(' + d + ')">' + d + '</span>';
        h += '<span class="tmm-f-chip n-brk' + (_tmmFilter.maxBreak === null ? '' : ' off') + '" onclick="tmmSetBreak(\x27\x27)" title="不限断板天数">10+</span></span>';
        h += '<span class="tmm-f-group tmm-f-search"><b>搜索</b><input class="tmm-f-search-input" id="tmmSearchBox" type="text" value="' + _kplEsc(_tmmFilter.search || '') + '" placeholder="板块/题材/股票" autocomplete="off" oninput="tmmSearchOnInput(this)" onfocus="tmmSearchOnInput(this)" onkeydown="tmmSearchKey(this,event)">';
        if (_tmmFilter.search) h += '<span class="tmm-f-search-clear" onclick="tmmSearchClear()" title="清除搜索">×</span>';
        h += '<div class="suggestions" id="tmmSearchSuggestions"></div></span>';
        if (typeof matched === 'number') h += '<span class="tmm-f-stat">匹配 <b>' + matched + '</b> 只</span>';
        h += '<span class="tmm-f-export" onclick="tmmExportMap()" title="导出题材地图三层结构（板块-细分题材-股票名称），同时下载 JSON 与 CSV">⬇ 导出题材地图</span>';
        h += '<span class="tmm-f-clear" onclick="tmmFilterClear()">↻ 重置</span></div>';
        return h;
    };
    // 点已选中的数字再点一次 = 取消（回到不限）
    var origSetBreak = window.tmmSetBreak;
    window.tmmSetBreak = function (v) {
        var n = parseInt(v, 10);
        if (isFinite(n) && _tmmFilter.maxBreak === n) v = '';
        origSetBreak(v);
    };

    // 创 / 科涨幅 >10% 但没涨停 → 「大涨」标记（与 6688 页签规则一致：20cm 品种）
    var stockBase = window._tmmStock;
    window._tmmStock = function (s) {
        var html = stockBase(s);
        var pct = s.quote_change_pct != null ? Number(s.quote_change_pct) : null;
        if (pct == null && !_tmmIsSessionNow() && s.p1 != null) pct = Number(s.p1);
        if ((s.board === '创' || s.board === '科') && pct != null && pct > 10 && !s.is_today) {
            var badge = '<b class="tmm-lb tmm-bigup" title="创/科涨幅超过10%，未涨停">大涨</b>';
            if (/<b class="tmm-lb"[^>]*>首板<\/b>/.test(html)) html = html.replace(/<b class="tmm-lb"[^>]*>首板<\/b>/, badge);
            else if (html.indexOf('class="tmm-lb"') < 0) html = html.replace('</span></span><span class="tmm-pct">', badge + '</span></span><span class="tmm-pct">');
        }
        return html;
    };

    // S / N / T 三页顶部右侧互跳按钮
    window.watchGoBtns = function (me) {
        var d = {S: ['ss', '个股查询'], N: ['sn', '涨停板数量 TOP10 + 板块'], T: ['sa', '今日20cm强势套利'], R: ['sr', '脉冲 / 异动（手机版）']};
        return '<span class="wz-go">' + ['S', 'N', 'T', 'R'].filter(function (k) { return k !== me; }).map(function (k) {
            return '<button type="button" class="wz-tl-sq wz-tl-' + d[k][0] + '" onclick="watchGoPage(\'' + k + '\')" title="跳转到：' + d[k][1] + '">' + k + '</button>';
        }).join('') + '</span>';
    };
    window.watchGoPage = function (to) {
        ['watchSqRoot', 'watchNRoot', 'watchSaRoot', 'watchRRoot'].forEach(function (id) { var e = document.getElementById(id); if (e) e.style.display = 'none'; });
        clearInterval(nTimer);
        if (to === 'S') watchOpenStockQuery(); else if (to === 'N') watchOpenN(); else if (to === 'R') watchOpenR(); else watchOpenStrongArb();
    };

    function box() { return document.getElementById('kplThemeMapContainer'); }

    function draw(data) {
        var c = box();
        if (!c) return;
        _tmmData = data;
        _tmmBuildSearchData(data);
        if (!_tmmFilterInit) _tmmInitFilter(data);
        _tmmCaptureCollapsed(c);
        c.innerHTML = _tmmRender(data);
        _tmmRestoreCollapsed(c);
        if (nPending && Date.now() - nPending.ts < 8000) setTimeout(function () { if (nPending) nJump(nPending.name); }, 50);   // 刚打开时数据重绘会改变布局：重绘后再对一次位置
        var ts = document.getElementById('watchNTs');
        if (ts) ts.textContent = '更新 ' + new Date().toLocaleTimeString('zh-CN', {hour12: false, timeZone: 'Asia/Shanghai'});
    }

    function load(live) {
        return fetch('/api/theme_map?ndays=20' + (live ? '&no_cache=1' : '') + '&_t=' + Date.now())
            .then(function (r) { return r.json(); })
            .then(function (data) {
                draw(data);
                if (data && data.ok) setTimeout(refreshQuotes, 0);
            })
            .catch(function (e) {
                var c = box();
                if (c && !c.querySelector('.tmm-box')) c.innerHTML = '<div class="watch-err">加载失败：' + _kplEsc(e.message) + ' <button onclick="watchNReload()">重试</button></div>';
            });
    }

    window.watchNReload = function () { load(true); };

    // 跳到 N 页中的某个题材：先找细分题材行（.tmm-theme-chip 名称精确 → 包含），再找板块卡片（.tmm-plate-link）；展开被折叠的卡片并闪一下
    function nJump(name) {
        var c = box(); if (!c || !name) return false;
        var chips = [].slice.call(c.querySelectorAll('.tmm-theme-chip')), plates = [].slice.call(c.querySelectorAll('.tmm-plate-link'));
        var txt = function (el) { var n = el.firstChild; return ((n && n.nodeType === 3 ? n.textContent : el.textContent) || '').trim(); };
        var hit = null, kind = '';
        chips.some(function (e) { if (txt(e) === name) { hit = e; kind = 'row'; return true; } });
        if (!hit) plates.some(function (e) { if (txt(e) === name) { hit = e; kind = 'card'; return true; } });
        if (!hit) chips.some(function (e) { var t = txt(e); if (t && (t.indexOf(name) >= 0 || name.indexOf(t) >= 0)) { hit = e; kind = 'row'; return true; } });
        if (!hit) plates.some(function (e) { var t = txt(e); if (t && (t.indexOf(name) >= 0 || name.indexOf(t) >= 0)) { hit = e; kind = 'card'; return true; } });
        if (!hit) return false;
        var card = hit.closest('.tmm-card'); if (card) card.classList.remove('collapsed');
        var target = kind === 'row' ? (hit.closest('.tmm-theme-row') || hit) : (card || hit);
        target.scrollIntoView({behavior: 'smooth', block: 'center'});
        target.classList.remove('lt-row-flash'); void target.offsetWidth; target.classList.add('lt-row-flash');
        return true;
    }
    var nPending = null;
    window.watchNJumpTheme = function (name) {
        nPending = {name: name, ts: Date.now()};
        var tries = 0, iv = setInterval(function () {           // 等 N 页数据渲染出来（首次打开要拉 /api/theme_map）
            tries++;
            if (!nPending || nPending.name !== name) return clearInterval(iv);
            if (box() && box().querySelector('.tmm-card') && Date.now() - nPending.ts > 700) {
                clearInterval(iv);
                if (!nJump(name)) { nPending = null; if (typeof showToast === 'function') showToast('N 页中暂无题材「' + name + '」（可能被过滤条件隐藏，或今日无涨停）', 'info'); }
            } else if (tries > 40) { clearInterval(iv); nPending = null; }
        }, 200);
    };
    window.watchOpenN = function () {
        var main = document.getElementById('watchRoot'), back = document.getElementById('watchBackNav');
        var root = document.getElementById('watchNRoot');
        if (!root) {
            root = document.createElement('div');
            root.id = 'watchNRoot';
            root.innerHTML = '<div class="sq2-bar"><button class="sq2-back" onclick="watchCloseN()">← 返回实时盯盘</button><h2>N <small id="watchNTs"></small></h2>' + watchGoBtns('N') + '</div><div id="watchNLadder"></div><div id="watchNBody"></div><button type="button" class="sa-fab" onclick="window.scrollTo({top: 0, behavior: \'smooth\'})" title="回到顶部">↑ 回顶部</button>';
            document.querySelector('.container').appendChild(root);
            // 主页面的题材地图容器原本在被隐藏的页签里，挪到 N 页即可复用其全部刷新 / 过滤函数
            var c = box();
            if (c) document.getElementById('watchNBody').appendChild(c);
        }
        if (window.watchMountLadder) watchMountLadder(document.getElementById('watchNLadder'));
        if (main.style.display !== 'none') nScrollY = window.scrollY;
        main.style.display = 'none';
        if (back) back.style.display = 'none';
        if (window.watchFloatNavShow) watchFloatNavShow(false);
        root.style.display = '';
        window.scrollTo(0, 0);
        load(false);
        clearInterval(nTimer);
        nTimer = setInterval(function () {      // 盘中每 60s 与 6688 原页一致地重算 + 刷新实时涨幅
            if (root.style.display === 'none' || !_tmmIsSessionNow()) return;
            load(true);
        }, 60000);
    };

    window.watchNBeforeTheme = function () {      // 天梯里点板块 / tags：先收起 N 页，再由个股查询页展示题材复盘
        var root = document.getElementById('watchNRoot');
        if (root) root.style.display = 'none';
        clearInterval(nTimer);
    };

    window.watchCloseN = function () {
        var root = document.getElementById('watchNRoot'), main = document.getElementById('watchRoot'), back = document.getElementById('watchBackNav');
        if (root) root.style.display = 'none';
        clearInterval(nTimer);
        main.style.display = '';
        if (back) back.style.display = '';
        if (window.watchFloatNavShow) watchFloatNavShow(true);
        window.scrollTo(0, nScrollY || 0);
    };

    // 股票点击：与 T（强势套利）页一致，用 openDsStockFromRhythm 弹框（上一只 / 下一只导航 = 同卡片 / 同题材行内的股票）
    var nLast = null;
    document.addEventListener('click', function (e) {
        var root = document.getElementById('watchNRoot');
        nLast = (root && root.style.display !== 'none' && e.target.closest) ? e.target.closest('#watchNBody .tmm-t10-stock, #watchNBody .tmm-stock') : null;
    }, true);
    function nInfo(el) {
        var codeEl = el.getAttribute('data-code'), m = /showEnlargedCardDetail\(\\?'?(\d{6})/.exec(el.getAttribute('onclick') || '');
        var nm = el.getAttribute('data-name') || ((el.querySelector('.tmm-name') || {}).textContent || '');
        return {code: codeEl || (m && m[1]) || '', name: nm.trim()};
    }
    var origEnlarge = window.showEnlargedCardDetail;
    window.showEnlargedCardDetail = function (code) {
        if (!nLast) return origEnlarge && origEnlarge(code);
        var group = nLast.closest('.tmm-t10-card') || nLast.closest('.tmm-theme-row') || nLast.parentNode;
        var nav = [], idx = -1;
        [].forEach.call(group.querySelectorAll('.tmm-t10-stock, .tmm-stock'), function (el) {
            var it = nInfo(el);
            if (!it.code) return;
            if (el === nLast) idx = nav.length;
            nav.push(it);
        });
        var me = nInfo(nLast);
        openDsStockFromRhythm(me.name || code, code, '', nav, idx);
    };

    // 主页面的「点题材/板块名 → KPL涨停深挖」页签在本站被隐藏：N 页内改为跳到「个股查询 · 题材复盘」
    var origJump = window.jumpToKplSearch;
    window.jumpToKplSearch = function (term) {
        var root = document.getElementById('watchNRoot');
        if (root && root.style.display !== 'none' && window.watchOpenTheme) {
            root.style.display = 'none';
            var main = document.getElementById('watchRoot');
            nScrollY = nScrollY || 0;
            window.watchOpenTheme(term);
            return;
        }
        if (origJump) origJump(term);
    };
})();
