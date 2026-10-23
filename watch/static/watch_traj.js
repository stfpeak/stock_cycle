/* 实时盯盘页专用：涨停原因标签轨迹渲染器。
 * 派生自主页面 renderLadderLianbanTagTrajectory（一次性分叉，此后独立演进，不影响主页面）。
 * 与原版差异：① 同格内「涨停」在上、「大涨」（创/科/北 涨幅>10% 未涨停）在下，以虚线分隔；
 *            ② 股票前标注 主/创/科/北；③ 最新列/参考列加 lt-col-latest / lt-col-ref 类，便于加宽与分隔。
 * 数据：/api/ladder_trajectory?surge=1 （surge_by_tag / reference_surge_by_tag）。 */
/* 实时盯盘页专用：今日涨停时间轴渲染器。派生自主页面 _twsRenderTimeline（一次性分叉，此后独立演进）。
 * 与原版差异：午休 11:30~13:00 由 90 分钟压缩为 15 分钟（轴整体变短，其余布局算法不变）。 */
function watchRenderTimeline(twsData, boxId, searchMode) {
    boxId = boxId || 'twTimelineBox';
    var mapSearch = boxId === 'tmmTimelineBox' || searchMode === 'cls';
    var isMain = boxId === 'twTimelineBox' && !searchMode;     // 盯盘主页的时间轴：下方带日期切换
    var histDay = isMain && _watchTl.dsel && _watchTl.dayData && _watchTl.dayData.date === _watchTl.dsel ? _watchTl.dayData : null;
    if (histDay) twsData = histDay;
    var AXIS_START = 25;   // 轴起点 = 距9:00分钟数（9:25）：A股9:25集合竞价后才产生涨停，9:00~9:25无数据，轴从9:25开始
    var LUNCH_CUT = 75;   // 午休 11:30~13:00 共 90 分钟，压缩成 15 分钟（少 75 分钟空白）
    var AXIS_LEN = 360 - AXIS_START - LUNCH_CUT;   // 轴总长 = 9:25~15:00 去掉压缩掉的午休 = 260 分钟（minute 基准距 9:00，150=11:30，240=13:00）
    function eff(m) { return m <= 150 ? m : (m >= 240 ? m - LUNCH_CUT : 150 + (m - 150) / 6); }
    var tl = (twsData && twsData.timeline) || [];
    if (!tl.length) {
        if (!isMain || !_watchTl.dsel) return '';
        // 选了历史日期但还在加载 / 当天无数据：保留日期条，方便切换
        return '<div id="' + boxId + '" class="tws-tl-box"><div class="tws-summary-sec-head">⏱ 涨停时间轴 · ' + _watchTl.dsel +
            '</div><div class="lt-trajectory-loading">' + (_watchTl.err || '加载中...') + '</div>' + watchTlDatesHtml() + '</div>';
    }
    // 最小宽度随涨停股数自适应：股越多时间轴越宽（横向滚动），减少纵向 lane 数避免叠太高
    var MIN_W = Math.round(Math.max(1500, tl.length * 46) * AXIS_LEN / 335);   // 轴变短后同比缩窄，每分钟像素不变，不会多出泳道
    // 按分钟分组（同分钟多股 → 同列垂直堆叠）
    var groups = {};
    var gkeys = [];
    for (var i = 0; i < tl.length; i++) {
        var it = tl[i];
        var m = it.minute;
        var key = (m == null || m >= 9999) ? 'misc' : ('m' + m);
        if (!groups[key]) { groups[key] = { minute: m, items: [] }; gkeys.push(key); }
        groups[key].items.push(it);
    }
    gkeys.sort(function(a, b) {
        var ma = a === 'misc' ? 9999 : parseInt(a.slice(1), 10);
        var mb = b === 'misc' ? 9999 : parseInt(b.slice(1), 10);
        return ma - mb;
    });
    // 每列估算横向宽度（px）：按最长 chip 文本（名称 + MAB 标签）
    function colW(g) {
        var w = 0;
        for (var j = 0; j < g.items.length; j++) {
            var it = g.items[j];
            var mc = 0;
            if (it.mab && it.mab.length) {
                for (var mi2 = 0; mi2 < it.mab.length; mi2++) mc += ((it.mab[mi2].t || '').length * 9 + 14);
            } else {
                mc = (it.theme || '').length * 10;
            }
            var tw = (it.name || '').length * 13 + mc + 52;
            if (tw > w) w = tw;
        }
        return w;
    }
    // 贪心 lane：每 lane 内 chip 横向不重叠（间隔 8px），放不下换新 lane；
    // laneStack[l] = 该 lane 内最大同分钟堆叠数 → lane 高度动态 = maxStack*ROW_H（防同列多股越界覆盖下一 lane）
    var lanes = [];
    var laneRight = [];
    var laneStack = [];
    for (var gi = 0; gi < gkeys.length; gi++) {
        var g = groups[gkeys[gi]];
        var left = g.minute >= 9999 ? 0.985 : ((eff(Math.max(g.minute, AXIS_START)) - AXIS_START) / AXIS_LEN);
        var w = colW(g) / MIN_W;
        var placed = false;
        for (var l = 0; l < lanes.length; l++) {
            if (left >= laneRight[l] + 0.008) {
                lanes[l].push(g); laneRight[l] = left + w + 0.008;
                if (g.items.length > laneStack[l]) laneStack[l] = g.items.length;
                placed = true; break;
            }
        }
        if (!placed) { lanes.push([g]); laneRight.push(left + w + 0.008); laneStack.push(g.items.length); }
    }
    var marks = ['9:25', '9:30', '10:00', '10:30', '11:00', '11:30', '13:00', '13:30', '14:00', '14:30', '15:00'];
    var mpos = [0, 5, 35, 65, 95, 125, 140, 170, 200, 230, 260];   // 13:00 起整体前移 75 分钟
    var axis = '';
    for (var mi = 0; mi < marks.length; mi++) {
        axis += '<span class="tws-tl-tick" style="left:' + (mpos[mi] / AXIS_LEN * 100).toFixed(2) + '%">' + marks[mi] + '</span>';
    }
    axis += '<span class="tws-tl-lunch" style="left:' + (125 / AXIS_LEN * 100).toFixed(2) + '%;width:' + (15 / AXIS_LEN * 100).toFixed(2) + '%">午休</span>';
    var h = '<div id="' + boxId + '" class="tws-tl-box"><div class="tws-summary-sec-head">' + (histDay ? '⏱ 涨停时间轴 · ' + histDay.date + '（历史）' : '⏱ 今日涨停时间轴（9:25~15:00）') + '<button class="wz-tl-sq" onclick="watchOpenStockQuery()" title="个股查询">🔍 个股查询</button></div>';
    h += '<div class="tws-tl-scroll"><div class="tws-timeline" style="min-width:' + MIN_W + 'px">';
    h += '<div class="tws-tl-axis">' + axis + '</div>';
    for (var li = 0; li < lanes.length; li++) {
        h += '<div class="tws-tl-lane" style="height:' + (laneStack[li] * ROW_H) + 'px">';
        for (var k = 0; k < lanes[li].length; k++) {
            var g = lanes[li][k];
            var leftPct = g.minute >= 9999 ? 98.5 : ((eff(Math.max(g.minute, AXIS_START)) - AXIS_START) / AXIS_LEN * 100);
            g.items.sort(function(a, b2) { return (b2.lianban || 0) - (a.lianban || 0) || a.name.localeCompare(b2.name); });
            for (var q = 0; q < g.items.length; q++) {
                h += watchTlChip(g.items[q], leftPct, q, mapSearch, searchMode);
            }
        }
        h += '</div>';
    }
    h += '</div>';
    // 标签筛选条（时间轴下方）：当天涨停股在图上出现过的全部标签，全选 / 全取消 / 单选；未选中标签的股票变暗
    var cnt = {};
    tl.forEach(function (it) { watchTlTags(it).forEach(function (t) { cnt[t] = (cnt[t] || 0) + 1; }); });
    _watchTl.tags = Object.keys(cnt).sort(function (a2, b2) { return cnt[b2] - cnt[a2] || (a2 < b2 ? -1 : 1); }).map(function (t) { return {t: t, n: cnt[t]}; });
    h += '</div>' + (isMain ? watchTlDatesHtml() : '') + '<div class="wtl-bar" id="watchTlBar">' + watchTlBarInner() + '</div></div>';
    setTimeout(watchTlApply, 0);
    return h;
}

/* ===== 今日涨停时间轴 · 标签筛选 =====
 * 状态：all=true 表示全选（正常显示，且今后新出现的标签也算选中）；否则 sel 里的标签为选中，
 * 股票只要带任一选中标签就亮（高亮描边），其余变暗——全取消时全部变暗，再勾几个板块，新涨停落在其中就能一眼看出是补涨。 */
var _watchTl = {all: true, sel: {}, tags: [], dates: [], dsel: '', dayData: null, err: ''};
/* 日期切换（时间轴下方）：近 15 个交易日；dsel=''=最新交易日（实时 / 收盘时间轴，随 30s 刷新）；
 * 选历史日期时读 /api/zt_timeline_day，存入 dayData，30s 刷新重绘时仍显示所选日期。 */
function watchTlDatesHtml() {
    var T = _watchTl, ds = T.dates || [];
    if (!ds.length) return '';
    var latest = ds[ds.length - 1], cur = T.dsel || latest;
    return '<div class="wtl-dates"><b>📅 日期</b>' + ds.slice().reverse().map(function (d) {
        return '<span class="wtl-date' + (d === cur ? ' on' : '') + '" onclick="watchTlPickDate(\'' + d + '\')">' + d.slice(5) + (d === latest ? '<i>最新</i>' : '') + '</span>';
    }).join('') + '</div>';
}
function watchTlRerender() {
    var box = document.getElementById('twTimelineBox');
    if (!box) return;
    var sc = box.querySelector('.tws-tl-scroll'), left = sc ? sc.scrollLeft : 0;
    var live = (typeof _themeWindStrengthData !== 'undefined') ? _themeWindStrengthData : null;
    var html = watchRenderTimeline(live, 'twTimelineBox');
    var tmp = document.createElement('div');
    tmp.innerHTML = html;
    if (tmp.firstChild) box.replaceWith(tmp.firstChild); else box.remove();
    var sc2 = document.querySelector('#twTimelineBox .tws-tl-scroll');
    if (sc2) sc2.scrollLeft = left;
}
function watchTlPickDate(d) {
    var T = _watchTl, latest = T.dates[T.dates.length - 1];
    T.all = true; T.sel = {};
    T.err = '';
    if (!d || d === latest) { T.dsel = ''; T.dayData = null; return watchTlRerender(); }
    T.dsel = d; T.dayData = null;
    watchTlRerender();                       // 先显示"加载中"并高亮所选日期
    fetch('/api/zt_timeline_day?date=' + encodeURIComponent(d)).then(function (r) { return r.json(); }).then(function (x) {
        if (T.dsel !== d) return;
        if (x && x.timeline && x.timeline.length) T.dayData = x; else T.err = '该日无涨停数据';
        watchTlRerender();
    }).catch(function () { if (T.dsel === d) { T.err = '加载失败，请重试'; watchTlRerender(); } });
}
function watchTlLoadDates() {
    return fetch('/api/ladder_dates?n=15&_t=' + Date.now()).then(function (r) { return r.json(); }).then(function (a) {
        if (a && a.length) { _watchTl.dates = a; if (_watchTl.dsel && a.indexOf(_watchTl.dsel) < 0) _watchTl.dsel = ''; }
    }).catch(function () {});
}
function watchTlTags(it) {
    var out = [];
    ((it && it.mab) || []).forEach(function (m) { var t = ((m || {}).t || '').trim(); if (t && out.indexOf(t) < 0) out.push(t); });
    if (!out.length && it && it.theme) out.push(String(it.theme).trim());
    return out;
}
function watchTlChip(it, leftPct, q, mapSearch, searchMode) {
    var html = _twsTlChip(it, leftPct, q, mapSearch, searchMode);
    var tags = watchTlTags(it).join('|').replace(/&/g, '&amp;').replace(/"/g, '&quot;');
    return html.replace('<span class="tws-tl-chip', '<span data-wtags="' + tags + '" class="tws-tl-chip');
}
function watchTlBarInner() {
    var T = _watchTl, all = T.all, nSel = T.tags.filter(function (x) { return all || T.sel[x.t]; }).length;
    var h = '<div class="wtl-head"><b>🏷 标签筛选</b><span class="wtl-hint">当天涨停股出现过的标签 ' + T.tags.length + ' 个 · 已选 ' + nSel +
        (all ? '（全选：正常显示）' : '：只高亮带选中标签的股票，其余变暗') + '</span>' +
        '<button class="wtl-btn' + (all ? ' on' : '') + '" onclick="watchTlAll(true)">全选</button><button class="wtl-btn' + (!all && !nSel ? ' on' : '') + '" onclick="watchTlAll(false)">全取消</button></div><div class="wtl-tags">';
    T.tags.forEach(function (x) {
        var on = all || T.sel[x.t];
        var hue = 0; for (var ci = 0; ci < x.t.length; ci++) hue = (hue * 31 + x.t.charCodeAt(ci)) % 360;
        var sty = on ? ' style="background:hsl(' + hue + ',55%,40%);border-color:hsl(' + hue + ',55%,52%);color:#fff;"' : '';
        h += '<span class="wtl-tag' + (on ? ' on' : '') + '"' + sty + ' data-t="' + x.t.replace(/&/g, '&amp;').replace(/"/g, '&quot;') + '" onclick="watchTlToggle(this.getAttribute(\'data-t\'))">' + x.t.replace(/&/g, '&amp;').replace(/</g, '&lt;') + ' <i>' + x.n + '</i></span>';
    });
    return h + '</div>';
}
function watchTlAll(v) {
    _watchTl.all = !!v; _watchTl.sel = {};
    watchTlRefresh();
}
function watchTlToggle(t) {
    var T = _watchTl;
    if (T.all) {                                  // 全选态下点一个 = 取消它，其余保持选中
        T.all = false; T.sel = {};
        T.tags.forEach(function (x) { if (x.t !== t) T.sel[x.t] = true; });
    } else {
        T.sel[t] = !T.sel[t];
        if (T.tags.length && T.tags.every(function (x) { return T.sel[x.t]; })) { T.all = true; T.sel = {}; }
    }
    watchTlRefresh();
}
function watchTlRefresh() {
    var bar = document.getElementById('watchTlBar');
    if (bar) bar.innerHTML = watchTlBarInner();
    watchTlApply();
}
function watchTlApply() {
    var T = _watchTl;
    [].forEach.call(document.querySelectorAll('.tws-tl-chip[data-wtags]'), function (c) {
        if (T.all) { c.classList.remove('wtl-dim', 'wtl-lit'); return; }
        var tags = (c.getAttribute('data-wtags') || '').split('|').filter(Boolean);
        var hit = tags.some(function (t) { return T.sel[t]; });
        c.classList.toggle('wtl-lit', hit);
        c.classList.toggle('wtl-dim', !hit);
    });
}

function watchBoardOf(code) {
    code = String(code || '');
    if (code.slice(0, 2) === '30') return '创';
    if (code.slice(0, 2) === '68') return '科';
    if (code.slice(0, 3) === '920' || code.charAt(0) === '8' || code.charAt(0) === '4') return '北';
    return '主';
}
/* 「跌幅」卡片：最新日全市场跌幅超过 5% 的股票，按 KPL 题材归类并全部列出（形式同盯盘「涨停板数量 TOP10」的卡片网格）。
 * 题材按累计跌幅从大到小排；前 20 个直接展开，其余折叠在「更多题材」里；无 KPL 题材的归入末尾「未归类」。
 * 数据：data.decline（服务端计算，盘中用全市场实时涨幅，随 30s 刷新更新）。 */
var _watchDeclNavs = [];
function watchJumpThemeByName(name) {
    var links = document.querySelectorAll('tr.lt-theme-row .lt-th-name .lt-tag-link');
    var hit = null, i;
    for (i = 0; i < links.length && !hit; i++) if (links[i].textContent.trim() === name) hit = links[i];
    for (i = 0; i < links.length && !hit; i++) {            // 兜底：A+B 复合题材 / 简称，取名称互相包含的第一行
        var t = links[i].textContent.trim();
        if (t && (name.indexOf(t) >= 0 || t.indexOf(name) >= 0)) hit = links[i];
    }
    if (!hit) return false;
    watchJumpTheme(Number(hit.closest('tr').id.replace('wt-row-', '')));
    return true;
}
function watchRenderDecline(data) {
    var d = data && data.decline;
    if (!d || !d.themes || !d.themes.length) return '<div class="lt-trajectory-loading">暂无跌幅超过 5% 的股票</div>';
    _watchDeclNavs = [];
    function fmt(v) { v = Number(v); return (v > 0 ? '+' : '') + v.toFixed(2) + '%'; }
    function card(item, index) {
        var nm0 = (item.name || '').replace(/'/g, '');
        var click = item.name === '未归类' ? '' : ' onclick="watchJumpThemeByName(\x27' + nm0 + '\x27)" title="跳转到表格中的该题材"';
        var navIdx = _watchDeclNavs.length;
        _watchDeclNavs.push(item.stocks.map(function(x) { return {name: x.name, code: x.code}; }));
        var h = '<div class="tmm-t10-card lt-decl-card"><div class="tmm-t10-title"><b>#' + (index + 1) + '</b><span' + click + '>' + _kplEsc(item.name) + '</span>' +
            '<em class="lt-change-down">' + fmt(item.avg_pct) + '</em></div>' +
            '<div class="lt-decl-sub">' + item.count + ' 只 · 累计 ' + fmt(item.sum_pct) + '</div><div class="lt-decl-list">';
        item.stocks.forEach(function(st, si) {
            var nm = (st.name || '').replace(/'/g, '');
            h += '<div class="tmm-t10-stock" onclick="event.stopPropagation();openDsStockFromRhythm(\x27' + nm + '\x27, \x27' + st.code + '\x27, \x27\x27, _watchDeclNavs[' + navIdx + '], ' + si + ')">' +
                '<i class="lt-board lt-board-' + watchBoardKey(st.code) + '">' + watchBoardOf(st.code) + '</i>' +
                '<span class="tmm-t10-name" title="' + _kplEsc(nm) + '">' + _kplEsc(nm) + '</span><code>' + _kplEsc(st.code) + '</code>' +
                (st.prev_limit ? '<i class="lt-decl-prev">昨涨停</i>' : '') + '<b class="lt-change-down">' + fmt(st.pct) + '</b></div>';
        });
        return h + '</div></div>';
    }
    var SHOW = 20;
    var h = '<section class="tmm-today-top10 lt-decl"><div class="tmm-today-top10-head">🔻 跌幅超过 5% · ' + _kplEsc((d.date || '').slice(5)) +
        ' <span>共 ' + d.total + ' 只 · ' + d.themes.length + ' 个题材 · KPL题材分类 · 按累计跌幅排序' + (d.live ? ' · 盘中实时' : '') + '</span></div>' +
        '<div class="tmm-today-top10-grid">';
    d.themes.slice(0, SHOW).forEach(function(item, i) { h += card(item, i); });
    h += '</div>';
    if (d.themes.length > SHOW) {
        var restStocks = 0;
        d.themes.slice(SHOW).forEach(function(t) { restStocks += t.count; });
        h += '<details class="lt-decl-rest"><summary>更多题材（' + (d.themes.length - SHOW) + ' 个 · ' + restStocks + ' 只，按累计跌幅继续排序）</summary><div class="tmm-today-top10-grid">';
        d.themes.slice(SHOW).forEach(function(item, i) { h += card(item, SHOW + i); });
        h += '</div></details>';
    }
    return h + '</section>';
}

/* 题材名下方的「K线」按钮：与连板联动题材卡片的 K线 按钮同款（复用 _tmmOpenThemeKline 与 #tmmThemeKlineModal）。
 * 股票 = 最新日该题材的 涨停 → 大涨 → 涨幅>2%（未涨停）。 */
function watchThemeKlineBtn(tag, c) {
    var seen = {}, hits = [];
    function add(list) {
        (list || []).forEach(function(x) {
            if (x && x.code && !seen[x.code]) { seen[x.code] = 1; hits.push({stock_name: x.name || '', stock_code: x.code}); }
        });
    }
    add((c.stocksByTag[tag] && c.stocksByTag[tag][c.latest]) || []);
    add((c.surgeByTag[tag] && c.surgeByTag[tag][c.latest]) || []);
    add(c.riseByTag[tag] || []);
    var yd = (c.yd20ByTag && c.yd20ByTag[tag]) || [];
    if (!hits.length && !yd.length) return '';
    var safe = tag.replace(/'/g, '');
    var key = 'wt-' + safe;
    var h = '<div class="lt-th-kline">';
    if (hits.length) {
        _tmmThemeKlineOrder[key] = hits;
        h += '<button type="button" class="ms-tp-kline-btn" onclick="event.stopPropagation();_tmmOpenThemeKline(\x27' + safe + '\x27,\x27' + key +
            '\x27)" title="查看 ' + _kplEsc(c.latest.slice(5)) + ' 涨停 / 大涨 / 涨幅>2% 股票的K线走势（' + hits.length + ' 只）">📈 K线走势</button>';
    }
    if (yd.length) {
        h += '<button type="button" class="ms-tp-kline-btn lt-yd-btn" onclick="event.stopPropagation();watchJumpYd20(' + c.idx[tag] +
            ')" title="跳到页面底部「那些异动的20cm」：该题材近20个交易日大涨过的创业板 / 科创板股票（' + yd.length + ' 只）">🔥 异动20cm</button>';
    }
    return h + '</div>';
}

/* 题材操作思考标记：龙头 / 补涨 / 切换 / 套利。默认都不亮，点击点亮（可多选、可全不选），用来逼自己对每个题材想清楚怎么做。
 * 状态按「最新交易日」存在浏览器 localStorage：当天内刷新页面、每 30s 重绘都不丢；换到下一个交易日自动清空重新思考。 */
var _WATCH_MARK_KEY = 'watch_theme_marks_v1';
var _WATCH_MARK_DEFS = [['leader', '龙头'], ['follow', '补涨'], ['switch', '切换'], ['arb', '套利']];
var _watchMarks = {date: '', marks: {}};
function watchMarksLoad(date) {
    var marks = {};
    try {
        var o = JSON.parse(localStorage.getItem(_WATCH_MARK_KEY) || 'null');
        if (o && o.date === date && o.marks) marks = o.marks;
    } catch (e) {}
    _watchMarks = {date: date, marks: marks};
    return marks;
}
function watchThemeMarks(tag) {
    var cur = _watchMarks.marks[tag] || [];
    var h = '<div class="lt-th-marks" title="龙头 / 补涨 / 切换 / 套利：点击点亮，可多选或都不选 —— 先想清楚这个题材怎么做">';
    _WATCH_MARK_DEFS.forEach(function(d) {
        h += '<button type="button" class="lt-mk lt-mk-' + d[0] + (cur.indexOf(d[0]) >= 0 ? ' on' : '') + '" data-theme="' + _kplEsc(tag) + '" data-k="' + d[0] + '" onclick="event.stopPropagation();watchToggleMark(this)">' + d[1] + '</button>';
    });
    return h + '</div>';
}
function watchToggleMark(btn) {
    var theme = btn.getAttribute('data-theme'), k = btn.getAttribute('data-k');
    var list = _watchMarks.marks[theme] || [];
    var i = list.indexOf(k);
    if (i >= 0) list.splice(i, 1); else list.push(k);
    if (list.length) _watchMarks.marks[theme] = list; else delete _watchMarks.marks[theme];
    btn.classList.toggle('on', i < 0);
    try { localStorage.setItem(_WATCH_MARK_KEY, JSON.stringify(_watchMarks)); } catch (e) {}
}

/* 参考列实时分栏：拿到实时涨幅后，卡片立刻在「晋级/阳线（左，涨幅高→低）」与「阴线（右，跌幅大→小）」之间换位，
 * 不必等下一次 30s 整体重绘；每栏内昨日涨停与昨日大涨仍上下分开、中间空一行。口径与渲染器里的分栏完全一致。 */
function watchRebalanceRef() {
    var live = window._watchLiveQuotes || {}, limit = window._watchTodayLimit || {};
    document.querySelectorAll('td.lt-col-ref').forEach(function(td) {
        var left = td.querySelector('.lt-latest-left'), right = td.querySelector('.lt-latest-right');
        if (!left || !right) return;
        var chips = [].slice.call(td.querySelectorAll('.lt-cell-stock'));
        if (!chips.length) return;
        var val = function(c) {
            var code = c.getAttribute('data-code');
            if (live[code] !== undefined) return live[code];
            var v = parseFloat(c.getAttribute('data-pct'));
            return isFinite(v) ? v : null;
        };
        var promoted = function(c) { return !!limit[c.getAttribute('data-code')]; };
        var keyL = function(c) { return promoted(c) ? 1000 + (val(c) || 0) : (val(c) === null ? -1000 : val(c)); };
        var L1 = [], L2 = [], R1 = [], R2 = [];       // 左涨停/左大涨/右涨停/右大涨
        chips.forEach(function(c) {
            var v = val(c), toLeft = promoted(c) || v === null || v >= 0, sur = c.getAttribute('data-surge') === '1';
            (toLeft ? (sur ? L2 : L1) : (sur ? R2 : R1)).push(c);
        });
        var byGain = function(a, b) { return keyL(b) - keyL(a); }, byDrop = function(a, b) { return val(a) - val(b); };
        L1.sort(byGain); L2.sort(byGain); R1.sort(byDrop); R2.sort(byDrop);
        var sig = [L1, L2, R1, R2].map(function(g) { return g.map(function(c) { return c.getAttribute('data-code'); }).join(','); }).join('|');
        if (td._refSig === sig) return;               // 顺序没变，不动 DOM
        td._refSig = sig;
        var box = function(panel) {
            var b = panel.querySelector('.lt-cell-stocks');
            if (!b) {
                var empty = panel.querySelector('.lt-rise-empty'); if (empty) empty.remove();
                b = document.createElement('div'); b.className = 'lt-cell-stocks'; panel.appendChild(b);
            }
            b.textContent = '';
            return b;
        };
        var fill = function(panel, g1, g2) {
            var n = g1.length + g2.length;
            if (!n) {
                var old = panel.querySelector('.lt-cell-stocks'); if (old) old.remove();
                if (!panel.querySelector('.lt-rise-empty')) { var e = document.createElement('div'); e.className = 'lt-rise-empty'; e.textContent = '—'; panel.appendChild(e); }
                return 0;
            }
            var b = box(panel);
            g1.forEach(function(c) { b.appendChild(c); });
            if (g1.length && g2.length) { var sp = document.createElement('div'); sp.className = 'lt-ref-spacer'; b.appendChild(sp); }
            g2.forEach(function(c) { b.appendChild(c); });
            return n;
        };
        var nl = fill(left, L1, L2), nr = fill(right, R1, R2);
        var lt = left.querySelector('.lt-sub-title'), rt = right.querySelector('.lt-sub-title');
        if (lt) lt.textContent = '晋级 / 阳线 · ' + nl;
        if (rt) rt.textContent = '阴线 · ' + nr;
    });
}

/* 实时涨幅轮询（分叉自主页面 _ltTrajectoryPollLivePct）：逻辑不变，额外把拿到的实时涨幅记下并触发参考列重新分栏。 */
function watchPollLivePct() {
    if (_ltTrajectoryLivePctBusy) return;
    var cells = document.querySelectorAll('.lt-trajectory-live-close[data-code][data-date], .lt-trajectory-live-open[data-code][data-date]');
    if (!cells.length) return;
    var date = cells[0].getAttribute('data-date') || '';
    var codes = [];
    for (var i = 0; i < cells.length; i++) {
        if (cells[i].getAttribute('data-date') !== date) continue;
        var code = cells[i].getAttribute('data-code') || '';
        if (code && codes.indexOf(code) < 0) codes.push(code);
    }
    if (!date || !codes.length) return;
    _ltTrajectoryLivePctBusy = true;
    fetch('/api/trajectory_live_pct?date=' + encodeURIComponent(date) + '&codes=' + encodeURIComponent(codes.join(',')) + '&_t=' + Date.now())
        .then(function(r) { return r.json(); })
        .then(function(result) {
            var quotes = (result && result.quotes) || {};
            window._watchLiveQuotes = window._watchLiveQuotes || {};
            for (var i = 0; i < cells.length; i++) {
                var el = cells[i];
                if (el.getAttribute('data-date') !== date) continue;
                var q = quotes[el.getAttribute('data-code') || ''];
                if (!q) continue;
                window._watchQuoteCache = window._watchQuoteCache || {};
                window._watchQuoteCache[el.getAttribute('data-code')] = {open_pct: q.open_pct, change_pct: q.change_pct};
                if (el.classList.contains('lt-trajectory-live-open') && q.open_pct !== null && q.open_pct !== undefined && isFinite(Number(q.open_pct))) {
                    var openPct = Number(q.open_pct);
                    el.textContent = (openPct > 0 ? '+' : '') + openPct.toFixed(2) + '%';
                    el.className = openPct > 0 ? 'lt-change-up' : (openPct < 0 ? 'lt-change-down' : 'lt-change-flat');
                    el.removeAttribute('data-code');
                    el.removeAttribute('data-date');
                } else if (el.classList.contains('lt-trajectory-live-close') && q.change_pct !== null && q.change_pct !== undefined && isFinite(Number(q.change_pct))) {
                    var pct = Number(q.change_pct);
                    window._watchLiveQuotes[el.getAttribute('data-code')] = pct;
                    el.textContent = (pct > 0 ? '+' : '') + pct.toFixed(2) + '%';
                    el.className = pct > 0 ? 'lt-change-up' : (pct < 0 ? 'lt-change-down' : 'lt-change-flat');
                    var referenceCard = el.closest('.lt-reference-stock');
                    if (referenceCard) referenceCard.classList.toggle('lt-reference-down', pct < 0);
                    if (result.trading) {
                        el.classList.add('lt-trajectory-live-close');
                    } else {
                        el.removeAttribute('data-code');
                        el.removeAttribute('data-date');
                    }
                }
            }
            watchRebalanceRef();
        })
        .catch(function() {})
        .then(function() { _ltTrajectoryLivePctBusy = false; });
}

function watchJumpTheme(i) {
    var el = document.getElementById('wt-row-' + i);
    if (!el) return;
    el.scrollIntoView({behavior: 'smooth', block: 'start'});
    el.classList.remove('lt-row-flash'); void el.offsetWidth; el.classList.add('lt-row-flash');
}
function watchGoNav() {
    var n = document.getElementById('wtThemeNav');
    if (n) n.scrollIntoView({behavior: 'smooth', block: 'start'});
}
function watchBoardKey(code) { return {'主': 'main', '创': 'gem', '科': 'star', '北': 'bj'}[watchBoardOf(code)]; }

/* 首列「题材」下方的表现总结：基准=参考日(昨日)的票 → 最新日表现；再列最新日新增（新首板/其他连板/大涨）。
 * 基准按 连板(高→低) → 首板 → 大涨 分行；结果：最新日涨停=晋级(N板)/涨停，否则=最新日涨跌幅（红涨绿跌，盘中随 30s 轮询刷新）。 */
function watchThemeSummary(tag, c, bodyId) {
    var latest = c.latest;
    var base = (c.referenceByTag[tag] || []).concat(c.refSurgeByTag[tag] || []);
    var today = (c.stocksByTag[tag] && c.stocksByTag[tag][latest]) || [];
    var tSurge = (c.surgeByTag[tag] && c.surgeByTag[tag][latest]) || [];
    if (!base.length && !today.length && !tSurge.length) return '';
    var navs = _ltTrajectoryStockNavs;
    var navRef = bodyId ? ('_ltTrajNavById[\x27' + bodyId + '\x27]') : '_ltTrajectoryStockNavs';
    function fmt(v) { var n = Number(v); return (v === null || v === undefined || v === '' || !isFinite(n)) ? '--' : (n > 0 ? '+' : '') + n.toFixed(2) + '%'; }
    function pcls(v) { var n = Number(v); return (v === null || v === undefined || v === '' || !isFinite(n)) ? 'lt-change-flat' : (n > 0 ? 'lt-change-up' : (n < 0 ? 'lt-change-down' : 'lt-change-flat')); }
    function stk(s, resultHtml) {
        var name = (s.name || '').replace(/'/g, ''), code = s.code || '';
        navs.push([{name: name, code: code}]);
        return '<span class="lt-th-stk" title="' + _kplEsc(name + ' ' + code) + '" onclick="event.stopPropagation();openDsStockFromRhythm(\x27' + name + '\x27, \x27' + code + '\x27, \x27\x27, ' + navRef + '[' + (navs.length - 1) + '], 0)">' +
            _kplEsc(name) + (resultHtml ? ' ' + resultHtml : '') + '</span>';
    }
    function liveAttrs(code) { return ' lt-trajectory-live-close" data-code="' + _kplEsc(code) + '" data-date="' + _kplEsc(latest); }
    // 基准的结果：最新日涨停 → 晋级；否则最新日涨跌幅
    // 今日涨停股的「涨停时间 + 涨幅」（盘中涨幅随 30s 轮询更新，收盘后取日线）
    function limitInfo(code) {
        var tl = c.todayLimit[code];
        if (!tl) return '';
        var tm = (tl.first_time && tl.first_time < 999999) ? '<i class="lt-th-time">' + _kplLevelFormatTime(tl.first_time) + '</i>' : '';
        var pct = tl.close_pending ? '<b class="lt-change-pending' + liveAttrs(code) + '">待收盘</b>'
            : (tl.close_pct === null || tl.close_pct === undefined ? '' : '<b class="' + pcls(tl.close_pct) + '">' + fmt(tl.close_pct) + '</b>');
        return tm + pct;
    }
    function baseResult(s) {
        var tl = c.todayLimit[s.code];
        if (tl) return limitInfo(s.code) + '<em class="lt-th-up">' + (s.is_surge ? '涨停' : '晋级' + (tl.lianban >= 2 ? tl.lianban + '板' : '')) + '</em>';
        if (s.close_pending) return '<b class="lt-change-pending' + liveAttrs(s.code) + '">待收盘</b>';
        return '<b class="' + pcls(s.close_pct) + '">' + fmt(s.close_pct) + '</b>';
    }
    var html = '';
    if (base.length) {
        var groups = {}, baseCodes = {};
        base.forEach(function(s) {
            var lv = s.is_surge ? 0 : Math.max(1, s.lianban || 1);
            (groups[lv] = groups[lv] || []).push(s);
            baseCodes[s.code] = true;
        });
        var lvs = Object.keys(groups).map(Number).sort(function(a, b) {
            return (a === 0 ? -1 : a) < (b === 0 ? -1 : b) ? 1 : -1;      // 连板高→低、首板、大涨最后
        });
        html += '<div class="lt-th-sec"><div class="lt-th-sec-title">' + _kplEsc((c.refDate || '').slice(5)) + ' 的票 → ' + _kplEsc(latest.slice(5)) + ' 表现</div>';
        lvs.forEach(function(lv) {
            var lab = lv === 0 ? '大涨' : (lv === 1 ? '首板' : lv + '板');
            html += '<div class="lt-th-row"><span class="lt-th-lv lt-th-lv-' + (lv === 0 ? 'surge' : (lv >= 2 ? 'lb' : 'first')) + '">' + lab + '</span>';
            groups[lv].forEach(function(s) { html += stk(s, baseResult(s)); });
            html += '</div>';
        });
        html += '</div>';
        c._baseCodes = baseCodes;
    } else {
        c._baseCodes = {};
    }
    var bc = c._baseCodes;
    var newFirst = today.filter(function(s) { return !bc[s.code] && (s.lianban || 1) <= 1; });
    var newLb = today.filter(function(s) { return !bc[s.code] && (s.lianban || 1) >= 2; });
    var newSurge = tSurge.filter(function(s) { return !bc[s.code]; });
    if (newFirst.length || newLb.length || newSurge.length) {
        html += '<div class="lt-th-sec"><div class="lt-th-sec-title">' + _kplEsc(latest.slice(5)) + ' 新增</div>';
        if (newLb.length) {
            html += '<div class="lt-th-row"><span class="lt-th-lv lt-th-lv-lb">连板</span>';
            newLb.forEach(function(s) { html += stk(s, limitInfo(s.code) + '<em class="lt-th-up">' + (c.refLimit[s.code] ? '晋级' : '') + s.lianban + '板</em>'); });
            html += '</div>';
        }
        if (newFirst.length) {
            html += '<div class="lt-th-row"><span class="lt-th-lv lt-th-lv-first">新首板</span>';
            newFirst.forEach(function(s) {
                html += stk(s, limitInfo(s.code) + (s.is_restart ? '<i class="lt-th-restart">重启</i>' : ''));
            });
            html += '</div>';
        }
        if (newSurge.length) {
            html += '<div class="lt-th-row"><span class="lt-th-lv lt-th-lv-surge">大涨</span>';
            newSurge.forEach(function(s) {
                html += stk(s, '<b class="' + pcls(s.change_pct) + (s.close_pending ? liveAttrs(s.code) : '') + '">' + fmt(s.change_pct) + '</b>');
            });
            html += '</div>';
        }
        html += '</div>';
    }
    return html;
}

function watchRenderTrajectory(data, bodyId) {
    if (!data || !data.dates || data.dates.length === 0 || !data.freq_by_tag) {
        return '<div class="empty" style="padding:15px;color:#666;font-size:0.82em;">暂无轨迹数据</div>';
    }
    _ltTrajectoryStockNavs = [];   // 每次渲染重置，随自动刷新重渲染避免数组无限增长
    var EXCLUDE_TAGS = ['ST', '并购重组', 'ST摘帽', '实控人变更', '业绩预亏', '风险提示', '中报增长', '国有企业', '英伟达概念', '借壳上市', '资产注入', '定增', '增发', '年报增长', '业绩预增', '高送转'];
    function shouldExclude(tag) {
        for (var ei = 0; ei < EXCLUDE_TAGS.length; ei++) {
            if (tag.indexOf(EXCLUDE_TAGS[ei]) >= 0) return true;
        }
        return false;
    }

    var dates = data.dates.slice();
    dates.reverse();
    var freqByTag = data.freq_by_tag || {};
    var tagTotals = data.tag_totals || {};
    var stocksByTag = data.stocks_by_tag || {};
    var referenceDate = data.reference_enabled ? (data.reference_date || '') : '';
    var referenceByTag = data.reference_stocks_by_tag || {};
    var surgeByTag = data.surge_by_tag || {};                      // 大涨股：创/科/北 涨幅>10% 且未涨停
    var refSurgeByTag = data.reference_surge_by_tag || {};
    var riseByTag = data.rise_by_tag || {};                        // 最新日右栏：未涨停但涨幅>2%（题材匹配含 KPL/开盘红/同花顺）
    var displayCols = dates.map(function(d, i) { return {date: d, isReference: false, latest: i === 0}; });
    if (referenceDate && dates.length) displayCols.splice(1, 0, {date: referenceDate, isReference: true, latest: false});
    var sortedTags = Array.from(new Set(Object.keys(tagTotals).concat(Object.keys(referenceByTag)))).filter(function(t) {
        return !shouldExclude(t);
    });
    // 需求3：标签按「最近活跃优先」排序——(最近有连板的日期↓, 当天最高连板↓, 总数↓)
    var tagRank = {};
    for (var ti = 0; ti < sortedTags.length; ti++) {
        var t = sortedTags[ti];
        var dateCounts = freqByTag[t] || {};
        var lastDate = '';
        for (var di in dateCounts) {
            if (dateCounts[di] > 0 && di > lastDate) lastDate = di;   // YYYY-MM-DD 可直接字典序比较
        }
        var hOnLast = 0;
        var dayStocks = (stocksByTag[t] && stocksByTag[t][lastDate]) || [];
        for (var si = 0; si < dayStocks.length; si++) {
            if ((dayStocks[si].lianban || 0) > hOnLast) hOnLast = dayStocks[si].lianban;
        }
        tagRank[t] = {lastDate: lastDate, hOnLast: hOnLast, total: tagTotals[t] || 0};
    }
    sortedTags.sort(function(a, b) {
        var ra = tagRank[a], rb = tagRank[b];
        if (ra.lastDate !== rb.lastDate) return (ra.lastDate > rb.lastDate) ? -1 : 1;   // 最近活跃在前
        if (ra.hOnLast !== rb.hOnLast) return rb.hOnLast - ra.hOnLast;                    // 当天最高板降序
        return rb.total - ra.total;                                                      // 总数降序
    });
    if (sortedTags.length > 60) sortedTags = sortedTags.slice(0, 60);

    watchMarksLoad(dates[0]);
    window._watchLiveQuotes = {};      // 本轮渲染以服务端当前涨幅为准，之后由实时轮询覆盖
    var sumCtx = {latest: dates[0], refDate: referenceDate, referenceByTag: referenceByTag, refSurgeByTag: refSurgeByTag,
                  stocksByTag: stocksByTag, surgeByTag: surgeByTag, riseByTag: riseByTag, todayLimit: {}, refLimit: {}, refAll: {},
                  yd20ByTag: data.yd20 || {}, idx: {}};
    sortedTags.forEach(function(t, i) { sumCtx.idx[t] = i; });
    window._watchSortedTags = sortedTags.slice();
    window._watchYd20 = data.yd20 || {};
    Object.keys(referenceByTag).forEach(function(t) { (referenceByTag[t] || []).forEach(function(x) { sumCtx.refLimit[x.code] = 1; sumCtx.refAll[x.code] = 1; }); });
    Object.keys(refSurgeByTag).forEach(function(t) { (refSurgeByTag[t] || []).forEach(function(x) { sumCtx.refAll[x.code] = 1; }); });
    window._watchTodayLimit = sumCtx.todayLimit;
    Object.keys(stocksByTag).forEach(function(t) {
        ((stocksByTag[t] && stocksByTag[t][dates[0]]) || []).forEach(function(x) { sumCtx.todayLimit[x.code] = {lianban: x.lianban || 1, first_time: x.first_time, close_pct: x.close_pct, close_pending: x.close_pending}; });
    });
    var HUES = [212, 350, 38, 138, 270, 18, 178, 320];     // 莫兰迪色相循环（雾蓝/豆沙/沙驼/灰绿/藕紫/陶土/灰青/紫灰），低饱和由 CSS 控制；导航按钮与行标题同色
    // 最新日涨停数 TOP5 → R1~R5（同数量时保持表格顺序）
    var limitCnt = function(tag) { return ((stocksByTag[tag] && stocksByTag[tag][dates[0]]) || []).length; };
    var rankOf = {};
    sortedTags.map(function(t, i) { return {t: t, i: i, n: limitCnt(t)}; })
        .filter(function(x) { return x.n > 0; })
        .sort(function(a, b) { return b.n - a.n || a.i - b.i; })
        .slice(0, 5).forEach(function(x, r) { rankOf[x.t] = r + 1; });
    // 新题材：前一交易日该题材没有出现（无涨停、无大涨），最新日出现（有涨停或大涨）
    var prevDay = dates[1] || '';
    var appeared = function(tag, d) {
        return !!d && (((freqByTag[tag] || {})[d] || 0) > 0 || (((surgeByTag[tag] || {})[d] || []).length > 0));
    };
    var isNewTheme = {};
    sortedTags.forEach(function(t) { if (prevDay && appeared(t, dates[0]) && !appeared(t, prevDay)) isNewTheme[t] = 1; });
    var newTitle = '新题材：' + prevDay.slice(5) + ' 没有出现，' + dates[0].slice(5) + ' 新出现';
    var newBadge = function(tag) { return isNewTheme[tag] ? '<span class="lt-new-badge" title="' + newTitle + '">NEW</span>' : ''; };
    var newMini = function(tag) { return isNewTheme[tag] ? '<span class="lt-new-mini" title="' + newTitle + '"></span>' : ''; };
    var rBadge = function(tag) { return rankOf[tag] ? '<span class="lt-r-badge lt-r-' + rankOf[tag] + '" title="最新日涨停数第 ' + rankOf[tag] + '（' + limitCnt(tag) + ' 只）">R' + rankOf[tag] + '</span>' : ''; };
    var html = '<div class="lt-theme-nav" id="wtThemeNav"><span class="lt-theme-nav-title">题材导航<small>R1~R5 = 涨停数 TOP5 · 红点 = 新题材</small></span>';
    sortedTags.forEach(function(tag, i) {
        var n = limitCnt(tag);
        html += '<button class="lt-theme-nav-btn' + (rankOf[tag] ? ' lt-nav-top' : '') + '" style="--th-h:' + HUES[i % HUES.length] + '" onclick="watchJumpTheme(' + i + ')" title="跳转到 ' + _kplEsc(tag) + '">' +
            rBadge(tag) + newMini(tag) + _kplEsc(tag) + (n ? ' <i>' + n + '</i>' : '') + '</button>';
    });
    html += '</div>';
    html += '<div class="lt-trajectory-wrapper"><table class="lt-trajectory-matrix">';
    html += '<tr><th class="lt-trajectory-col-header lt-col-theme">题材</th>';
    displayCols.forEach(function(col) {
        if (col.isReference) {
            html += '<th class="lt-trajectory-col-header lt-reference-header lt-col-ref" title="' + _kplEsc(col.date) + ' 的票，价格为最新交易日表现"><div class="lt-th-top">参考列 · ' + _kplEsc(col.date.slice(5)) + '</div><div class="lt-latest-split"><div class="lt-latest-left"><small>晋级 / 阳线 · 涨幅↓</small></div><div class="lt-latest-right lt-ref-right"><small>阴线 · 跌幅↓</small></div></div></th><th class="lt-col-gap"></th>';
        } else {
            var dateLabel = col.date.slice(5) + (col.latest ? (_twsRefreshGate() ? ' · 盘中' : ' · 最新') : '');
            if (col.latest) {
                html += '<th class="lt-trajectory-col-header lt-col-latest" title="' + col.date + '"><div class="lt-th-top">' + dateLabel + '</div><div class="lt-latest-split"><div class="lt-latest-left"><small>涨停 / 大涨</small></div><div class="lt-latest-right"><small>涨幅&gt;2% 未涨停</small></div></div></th>';
            } else {
                html += '<th class="lt-trajectory-col-header" title="' + col.date + '">' + dateLabel + '</th>';
            }
        }
    });
    html += '</tr>';

    sortedTags.forEach(function(tag, tagIdx) {
        var total = tagTotals[tag] || 0;
        var dateCounts = freqByTag[tag] || {};
        html += '<tr class="lt-theme-row" id="wt-row-' + tagIdx + '" style="--th-h:' + HUES[tagIdx % HUES.length] + '">';
        html += '<td class="lt-trajectory-row-header lt-th-cell" title="' + _kplEsc(tag) + ' (共' + total + '次)"><div class="lt-th-name">' + newBadge(tag) + rBadge(tag) + '<span class="lt-tag-link" title="点击查看该题材的涨停节奏（题材复盘）" onclick="event.stopPropagation();watchOpenTheme(\x27' + (tag||'').replace(/'/g,'') + '\x27)">' + _kplEsc(tag) + '</span> <span class="lt-th-total">' + total + '</span></div>' + watchThemeKlineBtn(tag, sumCtx) + watchThemeSummary(tag, sumCtx, bodyId) + watchThemeMarks(tag) + '</td>';
        // 连板序号逻辑: 从最右（最旧）到最左（最新），连续出现则递增，断板则重置为1
        var counter = 0;
        var seqMap = {};  // date → counter value
        for (var di = dates.length - 1; di >= 0; di--) {
            var d = dates[di];
            if (dateCounts[d]) {
                counter++;
                seqMap[d] = counter;
            } else {
                counter = 0;
                seqMap[d] = 0;
            }
        }
        displayCols.forEach(function(col) {
            var d = col.date;
            var cellStocks = col.isReference ? ((referenceByTag[tag] || []).slice()) : ((stocksByTag[tag] && stocksByTag[tag][d]) || []);
            var cnt = col.isReference ? cellStocks.length : (dateCounts[d] || 0);
            var surgeStocks = col.isReference ? (refSurgeByTag[tag] || []).slice() : ((surgeByTag[tag] && surgeByTag[tag][d]) || []);
            var riseStocks = (col.latest && !col.isReference) ? (riseByTag[tag] || []) : [];
            if (cnt > 0 || surgeStocks.length > 0 || riseStocks.length > 0) {
                var seq = col.isReference ? (seqMap[d] || 1) : (seqMap[d] || 0);
                var cls = '';
                var marker = '';
                if (cnt === 0) { cls = 'lt-surge-only'; marker = ''; }
                else if (seq === 1) { cls = 'lt-first'; marker = '①'; }
                else if (seq === 2) { cls = 'lt-second'; marker = '②'; }
                else if (seq === 3) { cls = 'lt-third'; marker = '③'; }
                else if (seq === 4) { cls = 'lt-fourth'; marker = '④'; }
                else { cls = 'lt-fifth'; marker = seq; }
                html += '<td class="lt-trajectory-cell ' + cls + (col.isReference ? ' lt-reference-cell lt-col-ref' : '') + (col.latest ? ' lt-col-latest' : '') + '">';
                var isSplit = (col.latest && !col.isReference) || col.isReference;
                var tagLabel = cnt > 1 ? tag.slice(0, 4) + '(+' + cnt + ')' : tag.slice(0, 4);
                // 格子内列出该题材当日的股票（涨停在前、大涨在后）
                var allStocks = cellStocks.concat(surgeStocks);
                var refSplitAt = -1, refRightCount = 0, refSpacer1 = -1, refSpacer2 = -1, leftCount = allStocks.length;
                if (col.isReference) {
                    // 参考列：晋级/阳线在左（涨幅高→低），阴线在右（跌幅大→小）；每栏内「昨日涨停」与「昨日大涨」上下分开，中间空一行
                    var val = function(x) { var v = Number(x.cur_pct !== undefined && x.cur_pct !== null ? x.cur_pct : x.close_pct); return (x.cur_pct === null && x.close_pct === null) || !isFinite(v) ? null : v; };
                    var promoted = function(x) { return !!sumCtx.todayLimit[x.code]; };
                    var keyL = function(x) { return promoted(x) ? 1000 + (val(x) || 0) : (val(x) === null ? -1000 : val(x)); };
                    var leftLim = [], leftSur = [], rightLim = [], rightSur = [];
                    allStocks.forEach(function(x) {
                        var v = val(x), toLeft = promoted(x) || v === null || v >= 0;
                        (toLeft ? (x.is_surge ? leftSur : leftLim) : (x.is_surge ? rightSur : rightLim)).push(x);
                    });
                    var byGain = function(a, b) { return keyL(b) - keyL(a); }, byDrop = function(a, b) { return val(a) - val(b); };
                    leftLim.sort(byGain); leftSur.sort(byGain); rightLim.sort(byDrop); rightSur.sort(byDrop);
                    allStocks = leftLim.concat(leftSur, rightLim, rightSur);
                    leftCount = leftLim.length + leftSur.length;
                    refRightCount = rightLim.length + rightSur.length;
                    refSplitAt = leftCount;
                    if (leftLim.length && leftSur.length) refSpacer1 = leftLim.length;
                    if (rightLim.length && rightSur.length) refSpacer2 = leftCount + rightLim.length;
                }
                if (isSplit) {
                    // 层次：题材标题条（跨左右两栏）→ 两栏各自小标题 → 股票
                    html += '<div class="lt-cell-title"><span class="lt-marker">' + marker + '</span>' + _kplEsc(tagLabel) + '</div>';
                    html += '<div class="lt-latest-split"><div class="lt-latest-left"><div class="lt-sub-title">' + (col.isReference ? '晋级 / 阳线' : '涨停 / 大涨') + ' · ' + leftCount + '</div>';
                } else {
                    html += '<span class="lt-marker">' + marker + '</span>' + _kplEsc(tagLabel);
                }
                if (allStocks.length > 0) {
                    var navIdx = _ltTrajectoryStockNavs.length;
                    var navList = [];
                    for (var si = 0; si < allStocks.length; si++) {
                        navList.push({name: allStocks[si].name || '', code: allStocks[si].code || ''});
                    }
                    _ltTrajectoryStockNavs.push(navList);
                    html += '<div class="lt-cell-stocks">';
                    var surgeSepDone = false;
                    for (var si = 0; si < allStocks.length; si++) {
                        var s = allStocks[si];
                        if (col.isReference && si === refSplitAt && refRightCount) html += '</div></div><div class="lt-latest-right lt-ref-right"><div class="lt-sub-title">阴线 · ' + refRightCount + '</div><div class="lt-cell-stocks">';
                        if (col.isReference && (si === refSpacer1 || si === refSpacer2)) html += '<div class="lt-ref-spacer"></div>';
                        var sName = (s.name || '').replace(/'/g, '');
                        var sCode = s.code || '';
                        if (!sName || !sCode) continue;
                        var latestCol = !col.isReference && (d === dates[0]);   // dates 已 reverse，[0] 即最新交易日
                        var refPctNow = (s.cur_pct !== undefined && s.cur_pct !== null) ? s.cur_pct : s.close_pct;
                        var referenceDown = col.isReference && refPctNow !== null && refPctNow !== undefined && Number(refPctNow) < 0;
                        if (col.isReference) { /* 参考列按涨跌分栏，不再按涨停/大涨分隔 */ }
                        else if (s.is_surge && !surgeSepDone && si > 0) { html += '<div class="lt-surge-sep"><span>大涨 &gt;10%</span></div>'; surgeSepDone = true; }
                        else if (s.is_surge && !surgeSepDone) { html += '<div class="lt-surge-sep lt-surge-sep-top"><span>大涨 &gt;10%</span></div>'; surgeSepDone = true; }
                        var boardMark = '<i class="lt-board lt-board-' + watchBoardKey(sCode) + '">' + watchBoardOf(sCode) + '</i>';
                        var lbCls = s.is_surge ? 'lt-cell-stock-surge' : s.is_restart ? 'lt-cell-stock-restart'
                                 : (s.lianban >= 5 ? 'lt-lb-high'
                                 : 'lt-lb-' + (s.lianban >= 2 ? s.lianban : 1));
                        var chipCls = 'lt-cell-stock ' + lbCls + (latestCol ? ' lt-latest' : '') + (col.isReference ? ' lt-reference-stock' : '') + (referenceDown ? ' lt-reference-down' : '');
                        // 晋级：昨日(参考列)的涨停/大涨票，今日涨停 → 最新列与参考列同一只票都打「晋级」；
                        // NEW：最新列中昨日不在参考列的新首板（含重启）/新增大涨
                        var flagHtml = '';
                        var flagUp = '<i class="lt-flag lt-flag-up" title="晋级：昨日涨停/大涨，今日涨停">晋级</i>';
                        if (col.isReference) {
                            if (sumCtx.todayLimit[sCode]) flagHtml = flagUp;
                        } else if (latestCol) {
                            if (!s.is_surge && sumCtx.refAll[sCode]) flagHtml = flagUp;
                            else if (!sumCtx.refAll[sCode] && (s.is_surge || (s.lianban || 1) <= 1)) flagHtml = '<i class="lt-flag lt-flag-new" title="' + (s.is_surge ? '新增大涨' : '新首板') + '">NEW</i>';
                        }
                        var restartMark = s.is_restart ? ' <i class="lt-restart-mark">重启</i>' : '';
                        var miniTags = '';
                        if (s.tags && s.tags.length) {
                            for (var ti = 0; ti < s.tags.length; ti++) {
                                miniTags += '<i class="lt-tag-mini">' + _kplEsc(s.tags[ti]) + '</i>';
                            }
                        }
                        var navRef = bodyId ? ('_ltTrajNavById[\x27' + bodyId + '\x27]') : '_ltTrajectoryStockNavs';
                        var cellTm = (s.first_time && s.first_time < 999999) ? '<span class="lt-cell-time">' + _kplLevelFormatTime(s.first_time) + '</span>' : '';
                        var fmtPct = function(value) {
                            if (value === null || value === undefined || value === '') return '--';
                            var n = Number(value);
                            return isFinite(n) ? (n > 0 ? '+' : '') + n.toFixed(2) + '%' : '--';
                        };
                        var pctClass = function(value) {
                            if (value === null || value === undefined || value === '') return 'lt-change-flat';
                            var n = Number(value);
                            return n > 0 ? 'lt-change-up' : (n < 0 ? 'lt-change-down' : 'lt-change-flat');
                        };
                        // 盘中：服务端带的实时涨幅(cur_pct) → 本页上一轮轮询缓存，都没有才显示「待收盘」；新数据到达即替换，不出现空档
                        var qc = (window._watchQuoteCache || {})[sCode] || {};
                        var hasNum = function(v) { return v !== null && v !== undefined && v !== '' && isFinite(Number(v)); };
                        var openVal = hasNum(s.open_pct) ? s.open_pct : (s.close_pending && hasNum(qc.open_pct) ? qc.open_pct : null);
                        var liveVal = !s.close_pending ? s.close_pct : (hasNum(s.cur_pct) ? s.cur_pct : (hasNum(qc.change_pct) ? qc.change_pct : null));
                        var openText = fmtPct(openVal);
                        var closeText = (s.close_pending && !hasNum(liveVal)) ? '待收盘' : fmtPct(liveVal);
                        var closeClass = (s.close_pending && !hasNum(liveVal)) ? 'lt-change-pending' : pctClass(liveVal);
                        var priceDate = col.isReference ? dates[0] : d;
                        var openPending = s.close_pending && !hasNum(s.open_pct);
                        var liveOpenAttrs = openPending ? ' lt-trajectory-live-open" data-code="' + _kplEsc(sCode) + '" data-date="' + _kplEsc(priceDate) : '';
                        var liveCloseAttrs = s.close_pending ? ' lt-trajectory-live-close" data-code="' + _kplEsc(sCode) + '" data-date="' + _kplEsc(priceDate) : '';
                        var priceLine = '<span class="lt-cell-stock-ohlc" title="' + _kplEsc(priceDate) + ' 开盘涨跌幅 / 收盘涨跌幅">' +
                            '<em>开</em><b class="' + pctClass(openVal) + liveOpenAttrs + '">' + openText + '</b><i class="lt-ohlc-divider">·</i><em>收</em><b class="' + closeClass + liveCloseAttrs + '">' + closeText + '</b></span>';
                        html += '<span class="' + chipCls + '" data-code="' + _kplEsc(sCode) + '" data-surge="' + (s.is_surge ? 1 : 0) + '" data-pct="' + (refPctNow === null || refPctNow === undefined ? '' : refPctNow) + '" title="' + _kplEsc(sName + ' · 开 ' + openText + ' · 收 ' + closeText) + '" onclick="event.stopPropagation();openDsStockFromRhythm(\x27' + sName + '\x27, \x27' + sCode + '\x27, \x27\x27, ' + navRef + '[' + navIdx + '], ' + si + ')">' +
                            '<span class="lt-cell-stock-main">' + boardMark + _kplEsc(sName) + cellTm + (s.is_surge ? ' <b class="lt-surge-b">大涨</b>' : ' <b>' + s.lianban + '板</b>') + miniTags + restartMark + '</span>' + priceLine + flagHtml + '</span>';
                    }
                    html += '</div>';
                }
                if (col.latest && !col.isReference) {
                    html += '</div><div class="lt-latest-right"><div class="lt-sub-title">未涨停 &gt;2% · ' + riseStocks.length + '<span class="lt-sub-cap">开盘 / 现价</span></div>';
                    if (riseStocks.length) {
                        var riseNavIdx = _ltTrajectoryStockNavs.length;
                        _ltTrajectoryStockNavs.push(riseStocks.map(function(x) { return {name: x.name || '', code: x.code || ''}; }));
                        var riseNavRef = bodyId ? ('_ltTrajNavById[\x27' + bodyId + '\x27]') : '_ltTrajectoryStockNavs';
                        riseStocks.forEach(function(x, xi) {
                            var rn = (x.name || '').replace(/'/g, '');
                            var xq = (window._watchQuoteCache || {})[x.code] || {};
                            var rv = Number(x.change_pct);
                            var ov = (x.open_pct === null || x.open_pct === undefined) ? (xq.open_pct === undefined || xq.open_pct === null ? null : Number(xq.open_pct)) : Number(x.open_pct);
                            var pc = function(v) { return v > 0 ? 'lt-change-up' : (v < 0 ? 'lt-change-down' : 'lt-change-flat'); };
                            var fp = function(v) { return (v === null || !isFinite(v)) ? '--' : (v > 0 ? '+' : '') + v.toFixed(2) + '%'; };
                            var attr = function(kind) { return ' lt-trajectory-live-' + kind + '" data-code="' + _kplEsc(x.code) + '" data-date="' + _kplEsc(dates[0]); };
                            var liveCur = x.close_pending ? attr('close') : '';
                            var liveOpen = (x.close_pending && ov === null) ? attr('open') : '';
                            // 近15个交易日内最近一次涨停/大涨：M(+N)，M=当时连板数（大涨记 1），N=断板天数；名称后空一格
                            var hist = (x.prev_m !== undefined && x.prev_m !== null)
                                ? '<i class="lt-rise-hist' + (x.prev_m >= 3 ? ' hot' : '') + '" title="' + _kplEsc(x.prev_date.slice(5)) + ' ' + (x.prev_m >= 2 ? x.prev_m + '连板' : '首板/大涨') + '，已断板 ' + x.prev_n + ' 天">' + x.prev_m + '(+' + x.prev_n + ')</i>'
                                : '<i class="lt-rise-hist"></i>';
                            var px = (x.open_px ? '开盘价 ' + Number(x.open_px).toFixed(2) : '') + (x.price ? ' · 现价 ' + Number(x.price).toFixed(2) : '');
                            html += '<div class="lt-rise-stk" title="' + _kplEsc(rn + ' ' + x.code + (px ? ' · ' + px : '')) + '" onclick="event.stopPropagation();openDsStockFromRhythm(\x27' + rn + '\x27, \x27' + x.code + '\x27, \x27\x27, ' + riseNavRef + '[' + riseNavIdx + '], ' + xi + ')">' +
                                '<i class="lt-board lt-board-' + watchBoardKey(x.code) + '">' + watchBoardOf(x.code) + '</i><span class="lt-rise-name">' + _kplEsc(rn) + '</span>' + hist +
                                '<b class="' + (ov === null ? 'lt-change-flat' : pc(ov)) + liveOpen + '">' + fp(ov) + '</b><b class="' + pc(rv) + liveCur + '">' + fp(rv) + '</b></div>';
                        });
                    } else {
                        html += '<div class="lt-rise-empty">—</div>';
                    }
                    html += '</div></div>';
                } else if (col.isReference) {
                    html += refRightCount ? '</div></div>' : '</div><div class="lt-latest-right lt-ref-right"><div class="lt-sub-title">阴线 · 0</div><div class="lt-rise-empty">—</div></div></div>';
                }
                html += '</td>';
            } else {
                html += '<td class="lt-trajectory-cell-empty' + (col.isReference ? ' lt-reference-cell lt-col-ref' : '') + (col.latest ? ' lt-col-latest' : '') + '">-</td>';
            }
            if (col.isReference) html += '<td class="lt-col-gap"></td>';
        });
        html += '</tr>';
    });
    html += '</table></div>';
    html += _ltRenderTrajectorySummary(data.summary);
    // 每个独立窗口（实时/题材风向）各自保存导航数组，供 chip 弹框左右导航
    if (bodyId) {
        _ltTrajNavById[bodyId] = _ltTrajectoryStockNavs;
    }
    if (!_ltTrajectoryLivePctTimer) _ltTrajectoryLivePctTimer = setInterval(_ltTrajectoryPollLivePct, 30000);
    setTimeout(_ltTrajectoryPollLivePct, 0);
    return html;
}



/* ===== 那些异动的20cm：近20个交易日大涨（>10%）过的创业板/科创板股票，按 KPL 题材归类，题材顺序与「涨停原因标签轨迹」一致 ===== */
function watchJumpYd20(i) {
    var el = document.getElementById('wyd-row-' + i) || document.getElementById('watchYd20Section');
    if (!el) return;
    el.scrollIntoView({behavior: 'smooth', block: 'start'});
    el.classList.remove('lt-row-flash'); void el.offsetWidth; el.classList.add('lt-row-flash');
}
var _watchYdNavs = [];
function watchYd20Kline(name) {
    var list = (window._watchYdShown || window._watchYd20 || {})[name] || [];
    var key = 'wyd-' + name.replace(/'/g, '');
    _tmmThemeKlineOrder[key] = list.map(function(x) { return {stock_name: x.name, stock_code: x.code}; });
    _tmmOpenThemeKline(name.replace(/'/g, ''), key);
}
var _WYD_ORDER = {lb: 0, first: 1, surge: 2, broken: 3};
function watchYdSort(a, b) {
    return (_WYD_ORDER[a.status] - _WYD_ORDER[b.status]) ||
        (a.status === 'lb' ? b.streak - a.streak : (a.status === 'broken' ? a.gap - b.gap : 0)) || (b.last_pct - a.last_pct);
}
function watchYdLabel(st) { return st.status === 'lb' ? st.streak + '板' : (st.status === 'first' ? '首板' : (st.status === 'surge' ? '大涨' : '断' + st.gap + '日')); }
function watchRenderYd20() {
    var body = document.getElementById('watchYd20Body');
    if (!body) return;
    var raw = window._watchYd20 || {}, order = (window._watchSortedTags || []).slice();
    // 只保留轨迹里实际展示的题材行；只属于未展示题材（被排除/超出60行）的股票并入「未归类」
    var yd = {}, shown = {}, orphan = {};
    order.forEach(function(t) { if (raw[t] && raw[t].length) { yd[t] = raw[t]; raw[t].forEach(function(x) { shown[x.code] = 1; }); } });
    Object.keys(raw).forEach(function(t) {
        if (yd[t]) return;
        raw[t].forEach(function(x) { if (!shown[x.code]) orphan[x.code] = x; });
    });
    // 排序：盘中按当日涨幅（高→低）；收盘后沿用后端的 连板 > 首板 > 大涨 > 断N日
    var live = typeof _twsRefreshGate === 'function' && _twsRefreshGate();
    var orphanList = Object.keys(orphan).map(function(c) { return orphan[c]; }).sort(watchYdSort);
    if (orphanList.length) yd['未归类'] = orphanList;
    if (live) {
        Object.keys(yd).forEach(function(t) {
            yd[t] = yd[t].slice().sort(function(a, b) { return (b.cur_pct == null ? -999 : b.cur_pct) - (a.cur_pct == null ? -999 : a.cur_pct); });
        });
    }
    window._watchYdShown = yd;
    var note = document.getElementById('watchYdSortNote');
    if (note) note.textContent = live ? '盘中按当日涨幅排序' : '按 连板 > 首板 > 大涨 > 断板 排序';
    var rows = [];
    order.forEach(function(t, i) { if (yd[t]) rows.push({name: t, i: i}); });
    if (yd['未归类']) rows.push({name: '未归类', i: -1});
    window._watchYdIndex = [];
    if (!rows.length) { body.innerHTML = '<div class="lt-trajectory-loading">近20个交易日暂无大涨的创业板 / 科创板股票</div>'; return; }
    _watchYdNavs = [];
    var HUES = [212, 350, 38, 138, 270, 18, 178, 320];
    var uniq = {}, firstCard = {};
    rows.forEach(function(r) { yd[r.name].forEach(function(x) { uniq[x.code] = 1; }); });
    var cnt = document.getElementById('watchYd20Count');
    if (cnt) cnt.textContent = Object.keys(uniq).length + ' 只 · ' + rows.length + ' 个题材';
    function fmt(v) { v = Number(v); return (v > 0 ? '+' : '') + v.toFixed(2) + '%'; }
    function cls(v) { return Number(v) >= 0 ? 'lt-change-up' : 'lt-change-down'; }
    var h = '';
    rows.forEach(function(r, k) {
        var list = yd[r.name];
        var hue = HUES[(r.i >= 0 ? r.i : k) % HUES.length];
        var nm = r.name.replace(/'/g, '');
        var blockId = 'wyd-row-' + (r.i >= 0 ? r.i : 'x' + k);
        window._watchYdIndex.push({type: 'theme', name: r.name, id: blockId, n: list.length});
        var navIdx = _watchYdNavs.length;
        _watchYdNavs.push(list.map(function(x) { return {name: x.name, code: x.code}; }));
        var c = {lb: 0, first: 0, surge: 0, broken: 0};
        list.forEach(function(x) { c[x.status]++; });
        h += '<div class="wyd-block" id="' + blockId + '" data-t="' + _kplEsc(r.name.toLowerCase()) + '" style="--th-h:' + hue + '">' +
            '<div class="wyd-side"><div class="lt-th-name wyd-name">' +
            (r.name === '未归类' ? _kplEsc(r.name) : '<span class="lt-tag-link" title="点击查看该题材的涨停节奏（题材复盘）" onclick="watchOpenTheme(\x27' + nm + '\x27)">' + _kplEsc(r.name) + '</span>') +
            ' <span class="lt-th-total">' + list.length + '</span></div>' +
            '<div class="wyd-stat"><span class="wyd-s-lb">连板 <b>' + c.lb + '</b></span><span class="wyd-s-first">首板 <b>' + c.first + '</b></span><span class="wyd-s-surge">大涨 <b>' + c.surge + '</b></span><span class="wyd-s-broken">断 <b>' + c.broken + '</b></span></div>' +
            '<div class="wyd-btns"><button type="button" class="ms-tp-kline-btn" onclick="watchYd20Kline(\x27' + nm + '\x27)" title="查看该题材近20个交易日大涨过的创业板 / 科创板股票K线走势（' + list.length + ' 只）">📈 异动走势</button>' +
            (r.i >= 0 ? '<button type="button" class="ms-tp-kline-btn wyd-up" onclick="watchJumpTheme(' + r.i + ')" title="回到轨迹中的该题材">↑ 轨迹</button>' : '') + '</div></div>' +
            '<div class="wyd-grid">';
        list.forEach(function(st, si) {
            var snm = (st.name || '').replace(/'/g, '');
            var cardId = '';
            if (!firstCard[st.code]) {
                firstCard[st.code] = cardId = 'wyd-c-' + st.code;
                window._watchYdIndex.push({type: 'stock', name: st.name, code: st.code, id: cardId, theme: r.name});
            }
            var tip = st.days.map(function(d) { return d.date.slice(5) + ' ' + fmt(d.pct); }).join('  ');
            var trKey = st.trend ? (st.trend === 'yin' ? 'n' : 'y') + Math.min(st.trend_n, 4) : '';
            var trTxt = !st.trend ? '' : (st.trend === 'yin' ? st.trend_n + '阴' : (st.trend_n === 1 ? '首阳' : st.trend_n + '阳'));
            var trTip = !st.trend ? '' : (st.trend === 'yin' ? '连续第 ' + st.trend_n + ' 个阴线' : '阴线之后第 ' + st.trend_n + ' 个阳线' + (st.trend_n === 1 ? '（阴线回调后的首阳）' : ''));
            h += '<div class="wyd-card wyd-' + st.status + '" data-n="' + _kplEsc((st.name + ' ' + st.code).toLowerCase()) + '" data-b="' + watchBoardOf(st.code) + '" data-tr="' + trKey + '" data-gap="' + st.gap + '"' +
                (cardId ? ' id="' + cardId + '"' : '') + ' title="' + _kplEsc(snm + ' ' + st.code + '｜' + trTip + '｜近20日大涨：' + tip) + '" onclick="openDsStockFromRhythm(\x27' + snm + '\x27, \x27' + st.code + '\x27, \x27\x27, _watchYdNavs[' + navIdx + '], ' + si + ')">' +
                '<div class="wyd-c-top"><i class="lt-board lt-board-' + watchBoardKey(st.code) + '">' + watchBoardOf(st.code) + '</i>' +
                '<span class="wyd-c-name">' + _kplEsc(snm) + '</span><code>' + st.code + '</code><span class="wyd-badge wyd-b-' + st.status + '">' + watchYdLabel(st) + '</span></div>' +
                (st.cur_pct != null ? '<div class="wyd-c-bot"><small>最新</small><span class="' + cls(st.cur_pct) + '">' + fmt(st.cur_pct) + '</span>' +
                    (trTxt ? '<span class="wyd-tr wyd-tr-' + st.trend + (st.trend === 'yang' && st.trend_n === 1 ? ' first' : '') + '" title="' + trTip + '">' + trTxt + '</span>' : '') + '</div>' : '') + '</div>';
        });
        h += '</div></div>';
    });
    body.innerHTML = h;
    watchYdFilter();
}

/* 搜索框：题材 / 股票名称 / 代码 自动补全，范围 = 本章节下面所有的题材和股票 */
function watchYdSuggest() {
    var inp = document.getElementById('watchYdSearch'), box = document.getElementById('watchYdSug');
    if (!inp || !box) return;
    var q = inp.value.trim().toLowerCase();
    if (!q) { box.classList.remove('on'); box.innerHTML = ''; return; }
    var idx = window._watchYdIndex || [];
    var hit = idx.filter(function(x) { return x.name.toLowerCase().indexOf(q) >= 0 || (x.code && x.code.indexOf(q) >= 0); });
    hit.sort(function(a, b) {
        var pa = a.name.toLowerCase().indexOf(q) === 0 ? 0 : 1, pb = b.name.toLowerCase().indexOf(q) === 0 ? 0 : 1;
        return pa - pb || (a.type === b.type ? 0 : (a.type === 'theme' ? -1 : 1));
    });
    hit = hit.slice(0, 12);
    box.innerHTML = hit.length ? hit.map(function(x, i) {
        return '<div class="wyd-sug-i" data-i="' + idx.indexOf(x) + '"><em>' + (x.type === 'theme' ? '题材' : '个股') + '</em><span>' + _kplEsc(x.name) + '</span>' +
            '<small>' + (x.type === 'theme' ? x.n + ' 只' : x.code + ' · ' + _kplEsc(x.theme)) + '</small></div>';
    }).join('') : '<div class="wyd-sug-none">没有匹配的题材或股票</div>';
    box.classList.add('on');
}
/* 过滤：市场（创/科）、阴阳（首阳 / x阳 / x阴）、断板天数 ≤ N、搜索（题材 / 股票）；各组不选 = 不限制。
 * 搜题材名 → 显示该题材全部股票；搜股票名称/代码 → 只显示命中的卡片；再与其余条件取交集。 */
var _wydF = {boards: {}, trends: {}};
function watchYdFilterToggle(group, key, el) {
    var m = _wydF[group];
    if (m[key]) delete m[key]; else m[key] = 1;
    if (el) el.classList.toggle('on', !!m[key]);
    watchYdFilter();
}
function watchYdFilterReset() {
    _wydF = {boards: {}, trends: {}};
    [].forEach.call(document.querySelectorAll('#watchYdFilter .wyd-f-chip.on'), function(e) { e.classList.remove('on'); });
    var n = document.getElementById('watchYdBreak'), q = document.getElementById('watchYdSearch');
    if (n) n.value = '';
    if (q) q.value = '';
    var sg = document.getElementById('watchYdSug');
    if (sg) sg.classList.remove('on');
    watchYdFilter();
}
function watchYdFilter() {
    var inp = document.getElementById('watchYdSearch'), body = document.getElementById('watchYd20Body');
    if (!inp || !body) return;
    var q = inp.value.trim().toLowerCase(), shown = 0;
    var nb = document.getElementById('watchYdBreak'), maxBreak = nb && nb.value !== '' ? Number(nb.value) : null;
    var hasB = Object.keys(_wydF.boards).length > 0, hasT = Object.keys(_wydF.trends).length > 0;
    var active = !!q || hasB || hasT || maxBreak !== null, seen = {};
    var old = body.querySelector('.wyd-nomatch');
    if (old) old.remove();
    [].forEach.call(body.querySelectorAll('.wyd-block'), function(b) {
        var themeHit = !q || b.getAttribute('data-t').indexOf(q) >= 0, n = 0;
        [].forEach.call(b.querySelectorAll('.wyd-card'), function(c) {
            var ok = (themeHit || c.getAttribute('data-n').indexOf(q) >= 0) &&
                (!hasB || _wydF.boards[c.getAttribute('data-b')]) &&
                (!hasT || _wydF.trends[c.getAttribute('data-tr')]) &&
                (maxBreak === null || Number(c.getAttribute('data-gap')) <= maxBreak);
            c.style.display = ok ? '' : 'none';
            if (ok) { n++; seen[c.getAttribute('data-n')] = 1; }
        });
        b.style.display = n ? '' : 'none';
        if (n) shown++;
    });
    var st = document.getElementById('watchYdStat');
    if (st) st.innerHTML = active ? '匹配 <b>' + Object.keys(seen).length + '</b> 只 · ' + shown + ' 个题材' : '';
    if (active && !shown) body.insertAdjacentHTML('afterbegin', '<div class="lt-trajectory-loading wyd-nomatch">没有符合当前过滤条件的题材或股票</div>');
}
function watchYdPick(i) {
    var x = (window._watchYdIndex || [])[i];
    var box = document.getElementById('watchYdSug');
    if (box) box.classList.remove('on');
    var inp = document.getElementById('watchYdSearch');
    if (!x || !inp) return;
    inp.value = x.name;
    watchYdFilter();
    var sec = document.getElementById('watchYd20Body');
    window.scrollTo({top: sec.getBoundingClientRect().top + window.scrollY - 150, behavior: 'smooth'});
}
document.addEventListener('input', function(e) { if (e.target && e.target.id === 'watchYdSearch') { watchYdFilter(); watchYdSuggest(); } });
document.addEventListener('focusin', function(e) { if (e.target && e.target.id === 'watchYdSearch') watchYdSuggest(); });
document.addEventListener('keydown', function(e) {
    if (!e.target || e.target.id !== 'watchYdSearch') return;
    if (e.key === 'Enter') { var f = document.querySelector('#watchYdSug .wyd-sug-i'); if (f) watchYdPick(Number(f.getAttribute('data-i'))); }
    else if (e.key === 'Escape') { document.getElementById('watchYdSug').classList.remove('on'); }
});
document.addEventListener('mousedown', function(e) {
    var it = e.target && e.target.closest && e.target.closest('#watchYdSug .wyd-sug-i');
    if (it) { e.preventDefault(); watchYdPick(Number(it.getAttribute('data-i'))); return; }
    if (!(e.target && e.target.closest && e.target.closest('.wyd-search'))) { var b = document.getElementById('watchYdSug'); if (b) b.classList.remove('on'); }
});
