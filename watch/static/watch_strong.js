/* 强势套利页（今日涨停时间轴右上角「强势套利」进入）：版式沿用「涨停原因标签轨迹」——题材导航 + 题材表格，题材顺序 / 最新交易日与轨迹一致；
 * 保留原有「题材」「最新交易日」两列（直接复用轨迹渲染器输出），参考列及其右侧换成「今日20cm强势套利」：每个题材上下两部分（虚线分割）
 *   上 = 今日创业板 / 科创板 涨幅>0 且 现价>开盘价（按当日涨幅从高到低；最高价突破 7% 的标突破时间，题材顶部有突破先后说明），
 *        涨停 / 强势SSS / 强势 的票默认展示日K + 分时卡片；
 *   下 = 近20个交易日创业板 / 科创板大涨过的股票（与「那些异动的涨停与20cm」的创 / 科 20cm 一致）。
 * 数据来自 /api/ladder_trajectory?surge=1 的 strong20 / yd20（随 30s 总时钟一起刷新）。 */
var _saNavs = [];
var _saShown = {};
var _saScrollY = 0;
var _SA_LV_ORD = {'涨停': 0, '强势SSS': 1, '强势': 2, '关注': 3, '': 4};
var _SA_KLINE_LV = {'涨停': 1, '强势SSS': 1, '强势': 1};

function saT(t) {
    if (t === null || t === undefined) return '';
    var s = ('000000' + t).slice(-6);
    return s.slice(0, 2) + ':' + s.slice(2, 4);
}
function saPct(v) { v = Number(v); return (v > 0 ? '+' : '') + v.toFixed(2) + '%'; }
function saCls(v) { return Number(v) >= 0 ? 'sa-up' : 'sa-down'; }      // 涨红跌绿
function saLvBadge(x) { return x.level ? '<span class="sa-badge sa-lv-' + _SA_LV_ORD[x.level] + '">' + x.level + '</span>' : ''; }

function watchSaChip(x, navIdx, si) {
    var nm = (x.name || '').replace(/'/g, '');
    var op = x.pre_close ? (x.open / x.pre_close - 1) * 100 : 0;      // 开盘涨幅
    return '<div class="sa-chip sa-lv-' + _SA_LV_ORD[x.level] + '" title="' + _kplEsc(nm + ' ' + x.code + ' · 开 ' + x.open.toFixed(2) + ' · 现 ' + x.price.toFixed(2) + ' · 最高涨幅 ' + saPct(x.high_pct)) +
        '" onclick="openDsStockFromRhythm(\x27' + nm + '\x27, \x27' + x.code + '\x27, \x27\x27, _saNavs[' + navIdx + '], ' + si + ')">' +
        '<div class="sa-c1"><i class="lt-board lt-board-' + watchBoardKey(x.code) + '">' + watchBoardOf(x.code) + '</i><b class="sa-nm">' + _kplEsc(nm) + '</b><code>' + x.code + '</code>' + saLvBadge(x) + '</div>' +
        '<div class="sa-c2">' +
        (x.t7 !== null && x.t7 !== undefined ? '<span class="sa-t7" title="最高价首次突破 +7% 的时间">⚡' + saT(x.t7) + '</span>' : '') + '</div>' +
        '<div class="sa-c3"><em>开盘</em><b class="' + saCls(op) + '">' + saPct(op) + '</b><i>→</i><em>当前</em><b class="' + saCls(x.pct) + '">' + saPct(x.pct) + '</b></div></div>';
}

function watchSaYdChip(st, navIdx, si) {
    var snm = (st.name || '').replace(/'/g, '');
    var tip = st.days.map(function(d) { return d.date.slice(5) + ' ' + saPct(d.pct); }).join('  ');
    var trTxt = !st.trend ? '' : (st.trend === 'yin' ? st.trend_n + '阴' : (st.trend_n === 1 ? '首阳' : st.trend_n + '阳'));
    return '<div class="wyd-card wyd-' + st.status + '" data-c="' + st.code + '" title="' + _kplEsc(snm + ' ' + st.code + '｜近20日大涨：' + tip) +
        '" onclick="openDsStockFromRhythm(\x27' + snm + '\x27, \x27' + st.code + '\x27, \x27\x27, _saNavs[' + navIdx + '], ' + si + ')">' +
        '<div class="wyd-c-top"><i class="lt-board lt-board-' + watchBoardKey(st.code) + '">' + watchBoardOf(st.code) + '</i>' +
        '<span class="wyd-c-name">' + _kplEsc(snm) + '</span><code>' + st.code + '</code><span class="wyd-badge wyd-b-' + st.status + '">' + watchYdLabel(st) + '</span></div>' +
        (st.cur_pct != null ? '<div class="wyd-c-bot"><small>最新</small><span class="' + saCls(st.cur_pct) + '">' + saPct(st.cur_pct) + '</span>' +
            (trTxt ? '<span class="wyd-tr wyd-tr-' + st.trend + (st.trend === 'yang' && st.trend_n === 1 ? ' first' : '') + '">' + trTxt + '</span>' : '') + '</div>' : '') + '</div>';
}

var _saKF = {'涨停': true, '强势SSS': true, '强势': true, '关注': true, '下跌': true};
var _saKAll = [];
var _SA_KF_KEYS = ['涨停', '强势SSS', '强势', '关注', '下跌'];
/* K线走势弹框：该题材今日候选 + 近20日创/科大涨股；可按 涨停 / 强势SSS / 强势 / 关注 / 下跌 过滤（默认全选）。
 * 分类：今日候选按 level（涨幅<=3% 的并入「关注」）；近20日大涨股里当前涨幅<0 的为「下跌」，其余并入「关注」。 */
function watchSaKline(name) {
    var e = _saShown[name] || {up: [], down: []}, seen = {};
    _saKAll = [];
    e.up.forEach(function(x) {
        if (seen[x.code]) return; seen[x.code] = 1;
        _saKAll.push({stock_name: x.name, stock_code: x.code, cat: x.level || '关注', subthemes: [(x.level || '') + (x.t7 !== null && x.t7 !== undefined ? ' · ' + saT(x.t7) + '突破7%' : '') + ' · ' + saPct(x.pct)]});
    });
    e.down.forEach(function(x) {
        if (seen[x.code]) return; seen[x.code] = 1;
        var neg = x.cur_pct !== null && x.cur_pct !== undefined && Number(x.cur_pct) < 0;
        _saKAll.push({stock_name: x.name, stock_code: x.code, cat: neg ? '下跌' : '关注', subthemes: ['近20日大涨' + (x.cur_pct != null ? ' · ' + saPct(x.cur_pct) : '')]});
    });
    _SA_KF_KEYS.forEach(function(k) { _saKF[k] = true; });
    var key = 'sa-' + name.replace(/'/g, '');
    _tmmThemeKlineOrder[key] = _saKAll.slice();
    _tmmOpenThemeKline(name.replace(/'/g, ''), key);
    var colbar = document.getElementById('tmmThemeKlineColbar');
    if (!colbar) return;
    var cnt = {};
    _saKAll.forEach(function(x) { cnt[x.cat] = (cnt[x.cat] || 0) + 1; });
    colbar.insertAdjacentHTML('afterend', '<div class="kpl-kline-colbar wyd-kl-board" id="saKlFilter"><span class="kpl-kline-colbar-label">过滤:</span>' +
        _SA_KF_KEYS.map(function(k) { return '<button type="button" class="kpl-kline-colbtn" data-k="' + k + '" onclick="watchSaKlineToggle(\'' + k + '\')">' + k + ' <i>' + (cnt[k] || 0) + '</i></button>'; }).join('') + '</div>');
    watchSaKlineApply(true);
}
function watchSaKlineToggle(k) { _saKF[k] = !_saKF[k]; watchSaKlineApply(); }
function watchSaKlineApply(first) {
    var body = document.getElementById('tmmThemeKlineBody');
    if (!body) return;
    [].forEach.call(body.querySelectorAll('#saKlFilter .kpl-kline-colbtn'), function(b) { b.classList.toggle('active', !!_saKF[b.getAttribute('data-k')]); });
    var hits = _saKAll.filter(function(x) { return _saKF[x.cat]; });
    _tmmThemeKlineHits = hits;
    var counter = document.getElementById('tmmThemeKlineCounter');
    if (counter) counter.textContent = hits.length + ' 只股票 · 日K / 分时';
    if (first && hits.length === _saKAll.length) return;
    var old = body.querySelector('.concept-kline-grid'), cols = old ? old.style.gridTemplateColumns : '';
    [].forEach.call(body.querySelectorAll('.concept-kline-grid, .wyd-kl-empty'), function(e) { e.remove(); });
    if (!hits.length) { body.insertAdjacentHTML('beforeend', '<div class="empty wyd-kl-empty" style="padding:24px;text-align:center;">没有选中的类别，请至少选择一项</div>'); return; }
    body.insertAdjacentHTML('beforeend', renderKplKlineGrid(hits));
    var g = body.querySelector('.concept-kline-grid');
    if (g && cols) g.style.gridTemplateColumns = cols;
}


/* ===== 题材强度：得分曲线图 + 强度榜 + 「强度排序」 =====
 * 得分算法在后端 _trajectory_strength（首板涨停 1.0 · N 连板 1+min(0.6, 0.35·lnN) · 大涨=首板 1.0 · 强势 0.5，广度优先，单只高连板不会拉高整个题材）。 */
var _saSortStrength = (function() { try { return localStorage.getItem('watchSaSortStrength') === '1'; } catch (e) { return false; } })();
var _SA_LINE_COLORS = ['#ff6b6b', '#ffa94d', '#ffd43b', '#69db7c', '#38d9a9', '#4dabf7', '#9775fa', '#f783ac'];
function saTrendBadge(v) {
    if (!v) return '';
    if (v.trend === 'up') return '<span class="sa-tr sa-tr-up" title="近30分钟得分 +' + v.d30 + '，近15分钟仍在上升：持续增强">▲增强</span>';
    if (v.trend === 'new') return '<span class="sa-tr sa-tr-new" title="30分钟前尚无得分，现在已有 ' + v.raw + ' 分：新启动">★新启</span>';
    if (v.trend === 'down') return '<span class="sa-tr sa-tr-down" title="得分较30分钟前下降 ' + Math.abs(v.d30) + '：走弱（有票炸板 / 回落）">▼走弱</span>';
    return '<span class="sa-tr sa-tr-flat" title="近30分钟得分变化不大">— 平稳</span>';
}
function watchSaToggleSort() {
    _saSortStrength = !_saSortStrength;
    try { localStorage.setItem('watchSaSortStrength', _saSortStrength ? '1' : '0'); } catch (e) {}
    watchSaRender();
}
function saStrengthHtml(st, order) {
    if (!st || !st.tags) return '';
    var names = Object.keys(st.tags).sort(function(a, b) { return st.tags[b].raw - st.tags[a].raw || (a < b ? -1 : 1); });
    if (!names.length) return '';
    var times = st.times || [], n = times.length;
    var W = 760, H = 270, L = 30, R = 150, T = 12, B = 22, pw = W - L - R, ph = H - T - B;
    var f = function(raw) { return 100 * (1 - Math.exp(-raw / (st.scale || 30))); };
    var top = names.slice(0, 8);
    var X = function(i) { return L + (n > 1 ? i / (n - 1) : 1) * pw; }, Y = function(v) { return T + ph - v / 100 * ph; };
    var svg = '<svg class="sa-chart" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="xMidYMid meet">';
    [0, 25, 50, 75, 100].forEach(function(g) { svg += '<line x1="' + L + '" x2="' + (L + pw) + '" y1="' + Y(g) + '" y2="' + Y(g) + '" stroke="rgba(255,255,255,0.1)"/><text x="' + (L - 4) + '" y="' + (Y(g) + 3) + '" text-anchor="end" fill="#7f8da3" font-size="9">' + g + '</text>'; });
    times.forEach(function(t, i) {
        if (t === '09:30' || t === '10:00' || t === '10:30' || t === '11:00' || t === '13:30' || t === '14:00' || t === '14:30' || t === '15:00') {
            svg += '<text x="' + X(i) + '" y="' + (H - 6) + '" text-anchor="middle" fill="#7f8da3" font-size="9">' + t + '</text>';
        }
        if (t === '11:30' && i < n - 1) svg += '<line x1="' + X(i) + '" x2="' + X(i) + '" y1="' + T + '" y2="' + (T + ph) + '" stroke="rgba(255,255,255,0.18)" stroke-dasharray="3 3"/>';
    });
    // 末端标签防重叠：按终点高度排序后至少隔 11px
    var ends = top.map(function(t, k) { var v = st.tags[t]; return {t: t, k: k, y: Y(f(v.series[n - 1] || 0)), score: v.score}; }).sort(function(a, b) { return a.y - b.y; });
    for (var q = 1; q < ends.length; q++) if (ends[q].y - ends[q - 1].y < 13) ends[q].y = ends[q - 1].y + 13;
    top.forEach(function(t, k) {
        var v = st.tags[t], col = _SA_LINE_COLORS[k % _SA_LINE_COLORS.length];
        var pts = v.series.map(function(r, i) { return X(i).toFixed(1) + ',' + Y(f(r)).toFixed(1); }).join(' ');
        svg += '<polyline fill="none" stroke="' + col + '" stroke-width="' + (k < 3 ? 2.4 : 1.6) + '" stroke-linejoin="round" points="' + pts + '"><title>' + _kplEsc(t) + ' 得分 ' + v.score + '</title></polyline>';
    });
    ends.forEach(function(e) {
        var col = _SA_LINE_COLORS[e.k % _SA_LINE_COLORS.length], v = st.tags[e.t];
        svg += '<text x="' + (L + pw + 6) + '" y="' + (e.y + 3) + '" fill="' + col + '" font-size="9" font-weight="700">' + _kplEsc(e.t.slice(0, 8)) + ' ' + v.score + (v.trend === 'up' ? ' ▲' : (v.trend === 'down' ? ' ▼' : '')) + '</text>';
    });
    svg += '</svg>';
    var maxScore = Math.max.apply(null, names.map(function(t) { return st.tags[t].score; })) || 1;
    var list = names.slice(0, 12).map(function(t, k) {
        var v = st.tags[t], p = v.parts, idx = order.indexOf(t);
        var dr = (v.rank30 && v.rank) ? v.rank30 - v.rank : 0;
        return '<div class="sa-rk" onclick="watchSaJumpName(\x27' + t.replace(/'/g, '') + '\x27)" title="' + _kplEsc(t + '：涨停 ' + p.zt + '（含连板 ' + p.lb + '）· 大涨 ' + p.surge + ' · 强势 ' + p.strong + ' ｜ 原始分 ' + v.raw + ' ｜ 近15分钟 ' + (v.d15 >= 0 ? '+' : '') + v.d15 + ' · 近30分钟 ' + (v.d30 >= 0 ? '+' : '') + v.d30) + '">' +
            '<i class="sa-rk-n">' + (k + 1) + '</i>' + (k < 8 ? '<i class="sa-rk-dot" style="background:' + _SA_LINE_COLORS[k] + '"></i>' : '<i class="sa-rk-dot sa-rk-dot-off"></i>') +
            '<span class="sa-rk-nm">' + _kplEsc(t) + '</span><span class="sa-rk-bar"><b style="width:' + (v.score / maxScore * 100).toFixed(0) + '%"></b></span>' +
            '<span class="sa-rk-sc">' + v.score + '</span>' +
            '<span class="sa-rk-p">' + saTrendBadge(v) + (dr ? '<span class="sa-rk-d ' + (dr > 0 ? 'sa-up' : 'sa-down') + '">排名' + (dr > 0 ? '↑' : '↓') + Math.abs(dr) + '</span>' : '') +
            '<span>涨停' + p.zt + ' 大涨' + p.surge + ' 强势' + p.strong + '</span></span></div>';
    }).join('');
    var w = st.weights || {};
    return '<div class="sa-str" id="saStrength"><div class="sa-str-head"><b>📊 题材强度</b><small>涨停 / 大涨 / 强势加权得分 · 曲线=开盘到现在累计得分 · 30s 实时重算</small>' +
        '<button type="button" class="sa-sortbtn' + (_saSortStrength ? ' on' : '') + '" onclick="watchSaToggleSort()" title="按当前强度得分从高到低重排下面的题材（再点恢复轨迹顺序）">⚡ 强度排序' + (_saSortStrength ? ' ✓' : '') + '</button>' +
        '<span class="sa-str-info" title="得分规则：首板涨停 ' + w.zt + ' 分；N连板 = ' + w.zt + ' + min(' + w.lb_cap + ', 0.35·lnN)（2板1.24 / 3板1.38 / 5板1.56，封顶1.6，高板只小幅加成）；大涨(创科>10%未封板)按首板 ' + w.surge + ' 分；强势(最高价破7%且现价>5%) ' + w.strong + ' 分；关注不计分。同一只票在题材内只按最高层级计一次，题材得分=各票之和（广度优先：3只首板 3.0 分 > 1只8连板 1.6 分）。展示分=100·(1-e^(-原始分/' + st.scale + '))。增强：近30分钟得分增量≥max(1,20%) 且近15分钟仍在涨。">ⓘ 规则</span></div>' +
        '<div class="sa-str-body"><div class="sa-str-chart">' + svg + '</div><div class="sa-str-list">' + list + '</div></div></div>';
}

/* ===== 今日强势20cm：今日创 / 科 涨停 + 强势SSS + 强势 的票（默认展开，可折叠），日K + 分时，点题材标签跳到下面表格对应题材 ===== */
var _saTopOpen = true;
var _saTopBlk = {'涨停': true, '强势SSS': true, '强势': false};      // 三块各自可折叠，强势默认折叠
var _saTopNavs = [];
function watchSaToggleTop() {
    _saTopOpen = !_saTopOpen;
    var b = document.getElementById('saTopBody'), a = document.getElementById('saTopArrow');
    if (b) b.style.display = _saTopOpen ? '' : 'none';
    if (a) a.textContent = _saTopOpen ? '▼' : '▶';
}
function watchSaToggleTopBlk(lv) {
    _saTopBlk[lv] = !_saTopBlk[lv];
    var k = _SA_LV_ORD[lv], g = document.getElementById('saTopGrid' + k), a = document.getElementById('saTopArr' + k);
    if (g) g.style.display = _saTopBlk[lv] ? '' : 'none';
    if (a) a.textContent = _saTopBlk[lv] ? '▼' : '▶';
}
function saTopHtml(s, order) {
    if (!s || !s.tags) return '';
    var inOrder = {};
    order.forEach(function(t) { inOrder[t] = 1; });
    var by = {};
    Object.keys(s.tags).forEach(function(t) {
        s.tags[t].forEach(function(x) {
            if (!_SA_KLINE_LV[x.level]) return;
            var e = by[x.code] || (by[x.code] = {x: x, tags: []});
            e.tags.push(inOrder[t] ? t : '未归类');
        });
    });
    var LVS = ['涨停', '强势SSS', '强势'], groups = {'涨停': [], '强势SSS': [], '强势': []};
    Object.keys(by).map(function(c) { return by[c]; }).sort(function(a, b) { return (b.x.pct - a.x.pct) || (a.x.code < b.x.code ? -1 : 1); })
        .forEach(function(e) { groups[e.x.level].push(e); });
    var flat = [];
    LVS.forEach(function(lv) { flat = flat.concat(groups[lv]); });
    _saTopNavs = [flat.map(function(e) { return {name: e.x.name, code: e.x.code}; })];
    var n = 0;
    function card(e) {
        var i = n++, x = e.x, nm = (x.name || '').replace(/'/g, ''), op = x.pre_close ? (x.open / x.pre_close - 1) * 100 : 0;
        var seen = {}, tags = e.tags.filter(function(t) { if (seen[t]) return false; seen[t] = 1; return true; });
        tags.sort(function(a, b) { return (order.indexOf(a) < 0 ? 999 : order.indexOf(a)) - (order.indexOf(b) < 0 ? 999 : order.indexOf(b)); });
        return '<div class="sat-card sa-lv-' + _SA_LV_ORD[x.level] + '" onclick="openDsStockFromRhythm(\x27' + nm + '\x27, \x27' + x.code + '\x27, \x27\x27, _saTopNavs[0], ' + i + ')">' +
            '<div class="sat-h"><i class="lt-board lt-board-' + watchBoardKey(x.code) + '">' + watchBoardOf(x.code) + '</i>' +
            '<b class="sat-nm">' + _kplEsc(nm) + '</b><code>' + x.code + '</code>' + saLvBadge(x) +
            '<span class="sat-pct ' + saCls(x.pct) + '">' + saPct(x.pct) + '</span></div>' +
            '<div class="sat-m"><span><em>开盘</em><b class="' + saCls(op) + '">' + saPct(op) + '</b> → <em>当前</em><b class="' + saCls(x.pct) + '">' + saPct(x.pct) + '</b></span>' +
            (x.t7 !== null && x.t7 !== undefined ? '<span class="sa-t7" title="最高价首次突破 +7% 的时间">⚡' + saT(x.t7) + ' 破7%</span>' : '') + '</div>' +
            '<div class="sat-tags"><span class="sat-tags-l">题材</span>' + tags.map(function(t) {
                return '<em class="sat-tag" title="跳转到下面表格的该题材" onclick="event.stopPropagation();watchSaJumpName(\x27' + t.replace(/'/g, '') + '\x27)">' + _kplEsc(t) + '</em>'; }).join('') + '</div>' +
            '<div class="emo-imgs"><img class="kline-img" loading="lazy" src="' + sinaKlineImg(x.code) + '" onerror="retryImg(this)">' +
            '<img class="kline-img min" loading="lazy" src="' + sinaMinImg(x.code) + '" onerror="retryImg(this)"></div></div>';
    }
    var blocks = LVS.map(function(lv) {
        var k = _SA_LV_ORD[lv], open = _saTopBlk[lv];
        return '<div class="sat-blk sat-blk-' + k + '"><div class="sat-blk-head" onclick="watchSaToggleTopBlk(\x27' + lv + '\x27)" title="点击展开 / 折叠"><span id="saTopArr' + k + '">' + (open ? '▼' : '▶') + '</span>' +
            '<i class="sa-badge sa-lv-' + k + '">' + lv + '</i><b>' + groups[lv].length + '</b> 只</div>' +
            '<div class="sat-grid" id="saTopGrid' + k + '"' + (open ? '' : ' style="display:none"') + '>' +
            (groups[lv].length ? groups[lv].map(card).join('') : '<div class="sa-none sa-empty">暂无</div>') + '</div></div>';
    }).join('');
    return '<div class="sa-top-sec"><div class="sa-str-head sa-top-head" onclick="watchSaToggleTop()" title="点击展开 / 折叠"><b><span id="saTopArrow">' + (_saTopOpen ? '▼' : '▶') + '</span> 🔥 今日强势20cm</b>' +
        '<small>今日创 / 科：涨停 <b class="sa-up">' + groups['涨停'].length + '</b> · 强势SSS <b class="sa-sg">' + groups['强势SSS'].length + '</b> · 强势 <b class="sa-st">' + groups['强势'].length + '</b> · 分三块各自折叠 · 点题材标签跳到下面对应题材</small></div>' +
        '<div id="saTopBody"' + (_saTopOpen ? '' : ' style="display:none"') + '>' + blocks + '</div></div>';
}

function watchSaJumpName(name) {
    var order = window._watchSortedTags || [], i = order.indexOf(name);
    var el = document.getElementById('sa-row-' + (i < 0 ? 'x' : i));
    if (el) el.scrollIntoView({behavior: 'smooth', block: 'start'});
}

function watchSaRender() {
    var root = document.getElementById('watchSaRoot'), body = document.getElementById('watchSaBody');
    if (!root || !body || root.style.display === 'none') return;
    var s = window._watchStrong20, td = window._watchTrajData, order = (window._watchSortedTags || []).slice();
    if (!s || !td) { body.innerHTML = '<div class="lt-trajectory-loading">加载中…</div>'; return; }
    var yd = window._watchYd20 || {};
    // 上半部分：题材 → 今日强势候选；下半部分：题材 → 近20日创/科大涨；不在轨迹题材行里的并入「未归类」
    var up = {}, down = {}, upSeen = {}, downSeen = {}, inOrder = {};
    order.forEach(function(t) { inOrder[t] = 1; });
    var orphanUp = {}, orphanDown = {};
    Object.keys(s.tags || {}).forEach(function(t) {
        if (inOrder[t]) { up[t] = s.tags[t]; s.tags[t].forEach(function(x) { upSeen[x.code] = 1; }); }
    });
    Object.keys(s.tags || {}).forEach(function(t) { if (!inOrder[t]) s.tags[t].forEach(function(x) { if (!upSeen[x.code]) orphanUp[x.code] = x; }); });
    Object.keys(yd).forEach(function(t) {
        var g = (yd[t] || []).filter(function(x) { return !watchYdIsMain(x); });
        if (inOrder[t] && g.length) { down[t] = g; g.forEach(function(x) { downSeen[x.code] = 1; }); }
    });
    Object.keys(yd).forEach(function(t) { if (!inOrder[t]) (yd[t] || []).forEach(function(x) { if (!watchYdIsMain(x) && !downSeen[x.code]) orphanDown[x.code] = x; }); });
    var ou = Object.keys(orphanUp).map(function(c) { return orphanUp[c]; }).sort(function(a, b) { return b.pct - a.pct; });
    var od = Object.keys(orphanDown).map(function(c) { return orphanDown[c]; }).sort(watchYdSort);
    _saShown = {};
    order.forEach(function(t) { _saShown[t] = {name: t, up: up[t] || [], down: down[t] || []}; });
    _saShown['未归类'] = {name: '未归类', up: ou, down: od};
    var date = s.date || '', live = typeof _twsRefreshGate === 'function' && _twsRefreshGate();
    var cnt = document.getElementById('watchSaCount');
    if (cnt) cnt.textContent = (date ? date.slice(5) + ' · ' : '') + '今日候选 ' + s.total + ' 只';
    // 题材导航 + 「题材」「最新交易日」两列：直接复用轨迹渲染器的输出（顺序 / 徽标 / 新题材 / 标记完全一致），丢弃参考列及右侧历史列，换成强势套利列
    var html = watchRenderTrajectory(td, 'saTrajBody').replace(/id="wt-row-/g, 'id="sa-row-').replace(/id="wtThemeNav"/, 'id="saThemeNav"')
        .replace(/watchJumpTheme\((\d+)\)/g, 'watchSaJump($1)');
    var tmp = document.createElement('div');
    tmp.innerHTML = html;
    var nav = tmp.querySelector('.lt-theme-nav'), table = tmp.querySelector('table.lt-trajectory-matrix');
    if (!table) { body.innerHTML = '<div class="lt-trajectory-loading">暂无数据</div>'; return; }
    [].forEach.call(table.querySelectorAll('tr'), function(tr) { while (tr.children.length > 2) tr.lastElementChild.remove(); });
    [].forEach.call(table.querySelectorAll('.lt-yd-btn'), function(b) { b.remove(); });      // 「异动涨停/20cm」按钮跳的是主页面底部章节，本页不用
    // 题材名下方补「涨停xx 大涨xx」；题材列里的「K线走势」改为强势套利范围（带过滤）；导航按钮补大涨数字
    var lastD = (td.dates || [])[(td.dates || []).length - 1] || '';
    var strMap = ((window._watchStrength || {}).tags) || {};
    var strV = function(tag) { return strMap[tag] || null; };
    var strongN = function(tag) { return ((_saShown[tag] || {}).up || []).filter(function(x) { return x.level === '强势' || x.level === '强势SSS'; }).length; };
    var zc = function(tag) { return (((td.stocks_by_tag || {})[tag] || {})[lastD] || []).length; };
    var sc2 = function(tag) { return (((td.surge_by_tag || {})[tag] || {})[lastD] || []).length; };
    [].forEach.call(table.querySelectorAll('tr.lt-theme-row'), function(tr) {
        var m = /^sa-row-(\d+)$/.exec(tr.id || ''), tag = m ? order[Number(m[1])] : '';
        if (!tag) return;
        var cell = tr.firstElementChild, nmEl = cell && cell.querySelector('.lt-th-name');
        if (cell) cell.insertAdjacentHTML('beforeend', '<div class="sa-sum" title="涨停 / 大涨：' + _kplEsc(lastD.slice(5)) + ' 轨迹口径；强势：今日创 / 科 强势 + 强势SSS（涨停不计）">' +
            (strV(tag) ? '<div class="sa-sum-r"><i class="sa-blk sa-blk-sc">强度</i><b class="sa-sc">' + strV(tag).score + '</b>' + saTrendBadge(strV(tag)) + '</div>' : '') +
            '<div class="sa-sum-r"><i class="sa-blk sa-blk-zt">涨停</i><b class="sa-up">' + zc(tag) + '</b> 个</div>' +
            '<div class="sa-sum-r"><i class="sa-blk sa-blk-sg">大涨</i><b class="sa-sg">' + sc2(tag) + '</b> 个</div>' +
            '<div class="sa-sum-r"><i class="sa-blk sa-blk-st">强势</i><b class="sa-st">' + strongN(tag) + '</b> 个</div></div>');
        var kb = cell && cell.querySelector('.lt-th-kline .ms-tp-kline-btn:not(.lt-yd-btn)');
        if (kb) { kb.setAttribute('onclick', 'event.stopPropagation();watchSaKline(\x27' + tag.replace(/'/g, '') + '\x27)'); kb.title = '查看该题材今日强势候选 + 近20日大涨创 / 科股票的K线走势，可按 涨停 / 强势SSS / 强势 / 关注 / 下跌 过滤'; }
    });
    if (nav) [].forEach.call(nav.querySelectorAll('.lt-theme-nav-btn'), function(b) {
        var m = /watchSaJump\((\d+)\)/.exec(b.getAttribute('onclick') || ''), tag = m ? order[Number(m[1])] : '';
        if (!tag) return;
        var z = zc(tag), g = sc2(tag);
        b.title = tag + ' · 涨停 ' + z + ' · 大涨 ' + g;
        if (g) b.insertAdjacentHTML('beforeend', '<b class="sa-nav-sg">' + g + '</b>');
        var sv = strV(tag);
        if (sv) b.insertAdjacentHTML('beforeend', '<b class="sa-nav-sc' + (sv.trend === 'up' || sv.trend === 'new' ? ' hot' : '') + '" title="强度得分 ' + sv.score + '">' + Math.round(sv.score) + (sv.trend === 'up' ? '▲' : '') + '</b>');
        b.setAttribute('data-tag', tag);
    });
    var th0 = table.querySelector('tr:first-child');
    if (th0) th0.insertAdjacentHTML('beforeend', '<th class="lt-trajectory-col-header sa-th" title="' + _kplEsc(date) + '"><div class="lt-th-top">⚡ 今日20cm强势套利</div>' +
        '<div class="lt-latest-split"><div class="lt-latest-left"><small>↑ 今日创 / 科 涨幅&gt;3% 且 现价&gt;开盘价　｜　↓ 近20日创 / 科 大涨过</small></div></div></th>');
    _saNavs = [];
    function cellHtml(r) {
        var nm = r.name.replace(/'/g, '');
        var lvCnt = {'涨停': 0, '强势SSS': 0, '强势': 0, '关注': 0};
        r.up.forEach(function(x) { if (lvCnt[x.level] !== undefined) lvCnt[x.level]++; });
        var h = '<td class="lt-trajectory-cell lt-col-latest sa-cell"><div class="sa-top"><button type="button" class="ms-tp-kline-btn" onclick="event.stopPropagation();watchSaKline(\x27' + nm + '\x27)" title="查看该题材今日强势候选 + 近20日大涨创 / 科股票的K线走势，可按 涨停 / 强势SSS / 强势 / 关注 / 下跌 过滤">📈 K线走势</button>' +
            '<span class="sa-stat"><span class="sa-lv-0">涨停 <b>' + lvCnt['涨停'] + '</b></span><span class="sa-lv-1">SSS <b>' + lvCnt['强势SSS'] + '</b></span><span class="sa-lv-2">强势 <b>' + lvCnt['强势'] + '</b></span><span class="sa-lv-3">关注 <b>' + lvCnt['关注'] + '</b></span><span>今日候选 <b>' + r.up.length + '</b></span></span></div>';
        var brk = r.up.filter(function(x) { return x.t7 !== null && x.t7 !== undefined; }).sort(function(a, b) { return a.t7 - b.t7 || b.pct - a.pct; });
        h += '<div class="sa-order"><b>⚡ 突破7%先后</b>' + (brk.length ? brk.map(function(x, j) {
            return '<span class="sa-ord-i"><i>' + (j + 1) + '</i>' + _kplEsc(x.name) + ' <em>' + saT(x.t7) + '</em> <b class="' + saCls(x.pct) + '">' + saPct(x.pct) + '</b></span>';
        }).join('') : '<span class="sa-none">今日暂无创 / 科最高价突破 7% 的股票</span>') + '</div>';
        var chips = r.up.filter(function(x) { return x.pct > 3; });      // 卡片只列当日涨幅 >3% 的票（<=3% 的仍可在「K线走势」弹框里看）
        if (chips.length) {
            var navIdx = _saNavs.length;
            _saNavs.push(chips.map(function(x) { return {name: x.name, code: x.code}; }));
            h += '<div class="sa-grid">' + chips.map(function(x, si) { return watchSaChip(x, navIdx, si); }).join('') + '</div>';
            var kl = r.up.filter(function(x) { return _SA_KLINE_LV[x.level]; });
            if (kl.length) {
                h += '<div class="sa-kline-title">📈 涨停 / 强势SSS / 强势 · 日K + 分时（' + kl.length + ' 只）</div>' + renderKplKlineGrid(kl.map(function(x) {
                    return {stock_name: x.name, stock_code: x.code, subthemes: [x.level + (x.t7 !== null && x.t7 !== undefined ? ' · ' + saT(x.t7) + '突破7%' : '') + ' · ' + saPct(x.pct)]};
                })).replace(/<img class="kline-img/g, '<img loading="lazy" class="kline-img');      // 卡片多时按需加载图片
            }
        } else {
            h += '<div class="sa-none sa-empty">今日暂无涨幅 &gt;3% 的创 / 科股票</div>';
        }
        h += '<div class="sa-split"><span>↑ 今日创 / 科 强势套利　｜　↓ 近20日创 / 科 20cm 大涨过（' + r.down.length + '）</span></div>';
        if (r.down.length) {
            var ni2 = _saNavs.length;
            _saNavs.push(r.down.map(function(x) { return {name: x.name, code: x.code}; }));
            h += '<div class="wyd-grid wyd-grid-gem">' + r.down.map(function(x, si) { return watchSaYdChip(x, ni2, si); }).join('') + '</div>';
        } else {
            h += '<div class="sa-none">—</div>';
        }
        return h + '</td>';
    }
    [].forEach.call(table.querySelectorAll('tr.lt-theme-row'), function(tr) {
        var m = /^sa-row-(\d+)$/.exec(tr.id || ''), tag = m ? order[Number(m[1])] : '';
        tr.insertAdjacentHTML('beforeend', cellHtml(_saShown[tag] || {name: tag, up: [], down: []}));
    });
    if (ou.length || od.length) {
        table.insertAdjacentHTML('beforeend', '<tr class="lt-theme-row" id="sa-row-x" style="--th-h:200"><td class="lt-trajectory-row-header lt-th-cell"><div class="lt-th-name">未归类 <span class="lt-th-total">' + ou.length + '</span></div></td>' +
            '<td class="lt-trajectory-cell-empty lt-col-latest">-</td>' + cellHtml(_saShown['未归类']) + '</tr>');
    }
    if (_saSortStrength) {      // 强度排序：题材行 / 导航按钮都按当前强度得分从高到低；没有得分的保持轨迹顺序排最后
        var scoreOf = function(tag) { var v = strMap[tag]; return v ? v.raw : -1; };
        var trs = [].slice.call(table.querySelectorAll('tr.lt-theme-row')), pos = {};
        trs.forEach(function(tr, i) { pos[tr.id] = i; });
        var tagOfTr = function(tr) { var m = /^sa-row-(\d+)$/.exec(tr.id || ''); return m ? order[Number(m[1])] : ''; };
        trs.slice().sort(function(a, b) { return (scoreOf(tagOfTr(b)) - scoreOf(tagOfTr(a))) || (pos[a.id] - pos[b.id]); }).forEach(function(tr) { tr.parentNode.appendChild(tr); });
        var xr = table.querySelector('#sa-row-x'); if (xr) xr.parentNode.appendChild(xr);
        if (nav) {
            var bs = [].slice.call(nav.querySelectorAll('.lt-theme-nav-btn')), bpos = bs.map(function(b) { return b; });
            bs.slice().sort(function(a, b) { return (scoreOf(b.getAttribute('data-tag')) - scoreOf(a.getAttribute('data-tag'))) || (bpos.indexOf(a) - bpos.indexOf(b)); }).forEach(function(b) { nav.appendChild(b); });
        }
        var tt = nav && nav.querySelector('.lt-theme-nav-title small'); if (tt) tt.textContent = '已按强度得分排序 · 数字 = 涨停数 / 大涨数 / 强度分';
    }
    var sc = window.scrollY;
    body.innerHTML = '';
    body.insertAdjacentHTML('beforeend', saStrengthHtml(window._watchStrength, order));
    body.insertAdjacentHTML('beforeend', saTopHtml(s, order));
    if (nav) body.appendChild(nav);
    var wrap = document.createElement('div');
    wrap.className = 'lt-trajectory-wrapper';
    wrap.appendChild(table);
    body.appendChild(wrap);
    window.scrollTo(0, sc);
    var ts = document.getElementById('watchSaTs');
    if (ts) ts.textContent = '更新 ' + (typeof fmtClock === 'function' ? fmtClock(typeof bjNow === 'function' ? bjNow() : new Date()) : new Date().toLocaleTimeString());
}

function watchSaJump(k) {
    var el = document.getElementById('sa-row-' + k);
    if (el) el.scrollIntoView({behavior: 'smooth', block: 'start'});
}

function watchOpenStrongArb(idx) {
    var main = document.getElementById('watchRoot'), back = document.getElementById('watchBackNav');
    var root = document.getElementById('watchSaRoot');
    if (!root) {
        root = document.createElement('div');
        root.id = 'watchSaRoot';
        root.innerHTML = '<div class="sq2-bar"><button class="sq2-back" onclick="watchCloseStrongArb()">← 返回实时盯盘</button><h2>⚡ 今日20cm强势套利 <small id="watchSaCount"></small> <small id="watchSaTs"></small></h2>' +
            '<span class="sa-legend">涨停 ≥19.5% · 强势SSS 现价&gt;10% · 强势 最高价突破7%且现价&gt;5% · 关注 现价&gt;3%</span></div><div id="watchSaBody"></div>' +
            '<button type="button" class="sa-fab" onclick="window.scrollTo({top: 0, behavior: \'smooth\'})" title="回到顶部（题材导航）">↑ 回导航</button>';
        document.querySelector('.container').appendChild(root);
    }
    if (main.style.display !== 'none') _saScrollY = window.scrollY;
    main.style.display = 'none';
    if (back) back.style.display = 'none';
    if (window.watchFloatNavShow) watchFloatNavShow(false);
    root.style.display = '';
    window.scrollTo(0, 0);
    watchSaRender();
    if (idx !== undefined && idx !== null) setTimeout(function() { watchSaJump(idx); }, 60);
    if (window.watchRefreshTrajectory) watchRefreshTrajectory();
}

function watchCloseStrongArb() {
    var root = document.getElementById('watchSaRoot'), main = document.getElementById('watchRoot'), back = document.getElementById('watchBackNav');
    if (root) root.style.display = 'none';
    main.style.display = '';
    if (back) back.style.display = '';
    if (window.watchFloatNavShow) watchFloatNavShow(true);
    window.scrollTo(0, _saScrollY || 0);
}
