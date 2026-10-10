/* 实时盯盘页：复用主页面已有的渲染函数，只组装四个模块。
 * 顺序：① 精选板块强度 · Top10细分题材卡片 → ② 今日涨停时间轴 → ③ 涨停原因标签轨迹 → ④ 细分题材晋级
 * 其中 ①② 在同一个 #twWindStrengthBody 内；④ 由 _twsRenderBoardSummary 的覆盖版在每次渲染时顺带写入 #watchPromoBody。
 * 刷新：统一由本文件的 30s 总时钟驱动（9:25~15:00）——板块强度表+时间轴+晋级、跌幅卡片+轨迹（含最新两列涨跌幅）、K线弹框；
 * 主页面自带的 60s 轮询（_twsStartPoll/_twsPoll）已关闭，避免重复请求。
 */
(function () {
    'use strict';

    var REFRESH_MS = 30000;          // 全页统一刷新周期
    var lastStrength = '--';

    // —— 刷新窗口：仅「交易日 9:15~15:00」。非交易日 / 盘前 / 盘后不做任何定时请求，页面停在上一交易日收盘落盘状态 ——
    // 交易日判断问主服务（/api/ladder_dates?n=1 在交易日 9:00 后返回今天），按日期缓存；问到之前按「非交易日」处理，不刷新。
    var tradingDay = {date: '', ok: false, pending: false};
    function bjDateStr() { var d = bjNow(); return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); }
    function ensureTradingDay() {
        var today = bjDateStr();
        if (tradingDay.date === today || tradingDay.pending) return;
        tradingDay.pending = true;
        fetch('/api/ladder_dates?n=1&_t=' + Date.now()).then(function (r) { return r.json(); }).then(function (a) {
            if (bjNow().getHours() >= 9) { tradingDay.date = today; tradingDay.ok = !!(a && a[a.length - 1] === today); }
        }).catch(function () {}).then(function () { tradingDay.pending = false; });
    }
    window._twsRefreshGate = function () {
        var n = new Date();
        var t = ((n.getUTCHours() + 8) % 24) * 60 + n.getUTCMinutes();
        if (t < 555 || t >= 900) return false;
        ensureTradingDay();
        return tradingDay.date === bjDateStr() && tradingDay.ok;
    };

    // —— 关闭主页面自带的 60s 轮询（_twsRefreshBoardLive 有 55s 节流，且不刷新板块强度表）——
    window._twsStartPoll = function () {};
    window._twsPoll = function () {};
    window._twsRefreshBoardLive = function () {};     // 主页面另有 60s 全局定时器会调它，统一由本文件 30s 总时钟接管

    // —— 覆盖：时间轴用压缩午休的版本；时间轴里的题材名点击 → 跳到下方「标签轨迹」表格中对应题材行 ——
    window._twsRenderTimeline = window.watchRenderTimeline;
    window._ltTrajectoryPollLivePct = window.watchPollLivePct;   // 实时涨幅轮询：更新数字的同时按涨跌重新分栏
    window._twsJumpToTheme = function (el) {
        var theme = (el.getAttribute('data-jump-theme') || '').trim() || (el.getAttribute('data-jump-plate') || '').trim();
        if (!theme) return;
        if (!window.watchJumpThemeByName(theme) && typeof showToast === 'function') showToast('表格中暂无题材「' + theme + '」', 'info');
    };

    // —— 覆盖：核心池联动本页不展示，避免每 5 分钟触发 market_structure 重请求 ——
    window._twsCorePoolLoad = function () {};

    // —— 覆盖：汇总区只保留「今日涨停时间轴」（板块表在其上方，板块折叠目录不展示），晋级写入独立容器 ——
    window._twsRenderBoardSummary = function (d) {
        if (!d || !d.plates || !d.plates.length) return '';
        var promo = document.getElementById('watchPromoBody');
        if (promo) {
            promo.innerHTML = (_twsRenderThemePromotion(d) || '').replace('（4日连续观察 · 题材为主 · 按涨停时间）', '（4日连续观察 · 板块 + tags 题材 · 按涨停时间）') ||
                '<div class="lt-trajectory-loading">暂无细分题材晋级数据</div>';
        }
        return '<div class="tws-summary">' + _twsRenderTimeline(d) + '</div>';
    };

    function bjNow() {
        var n = new Date();
        return new Date(n.getTime() + (480 + n.getTimezoneOffset()) * 60000);
    }
    function pad(v) { return v < 10 ? '0' + v : '' + v; }
    function fmtClock(d) { return pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds()); }

    var lastTraj = '--';
    var wasLive = false;

    function renderShell(root) {
        root.innerHTML =
            '<header class="wb">' +
              '<div class="wb-top">' +
                '<div class="wb-brand"><span class="wb-eyebrow">REAL-TIME MARKET WATCH</span><h1>实时盯盘</h1>' +
                  '<span class="wb-sub">题材强度 · 涨停时间轴 · 跌幅 · 标签轨迹 · 题材晋级，一屏盯全盘</span></div>' +
                '<div class="wb-meta"><div class="wb-clock" id="watchClock">--:--:--</div>' +
                  '<div class="wb-meta-row"><span class="wb-tz">北京时间</span><span class="watch-state" id="watchState">--</span></div></div>' +
              '</div>' +
              '<div class="wb-questions">' +
                '<div class="wb-q"><span class="wb-qn">01</span><div><b>做高哪个题材？</b><small>HIGH · 高度与主线</small></div></div>' +
                '<div class="wb-q"><span class="wb-qn">02</span><div><b>做哪个题材补涨？</b><small>CATCH-UP · 补涨与低位</small></div></div>' +
                '<div class="wb-q"><span class="wb-qn">03</span><div><b>切换到哪个新题材？</b><small>ROTATION · 新题材与切换</small></div></div>' +
                '<div class="wb-q"><span class="wb-qn">04</span><div><b>哪个题材有套利机会？</b><small>ARBITRAGE · 套利与机会</small></div></div>' +
              '</div>' +
              '<div class="wb-foot"><span>板块 / 时间轴 / 晋级 更新 <b id="watchStrengthTs">--</b></span>' +
                '<span>跌幅 / 轨迹 更新 <b id="watchTrajTs">--</b></span>' +
                '<span class="wb-foot-note">全页每 30s 刷新 · 仅 9:15~15:00 自动刷新</span></div>' +
            '</header>' +

            '<div class="rt-section lt-trajectory-section" id="watchIndexSection">' +
            '<h3 style="margin:6px 0 8px 0;font-size:0.9em;color:#ffd700;">📊 大盘指数 ' +
            '<span class="rt-refresh-icon" onclick="watchRefreshIndices()" title="刷新">↻</span>' +
            '<span class="wi-ts" id="watchIndexTs"></span></h3>' +
            '<div id="watchIndexBody" class="wi-body"><div class="lt-trajectory-loading">加载中...</div></div></div>' +

            '<div class="rt-section lt-trajectory-section" id="twWindStrengthSection">' +
            '<h3 style="margin:6px 0 8px 0;font-size:0.9em;color:#ffd700;">⚡ 精选板块强度 · Top10细分题材卡片 ' +
            '<span class="rt-refresh-icon" onclick="manualRefreshTws()" title="刷新">↻</span></h3>' +
            '<div id="twWindStrengthBody"><div class="loading">加载中...</div></div></div>' +

            '<div class="rt-section lt-trajectory-section" id="watchDeclineSection">' +
            '<h3 id="watchDeclineHead" class="wd-head" onclick="watchToggleDecline()" title="点击展开 / 折叠">' +
            '<span class="wd-arrow" id="watchDeclineArrow">▶</span>🔻 跌幅 <span class="count-badge">跌幅 &gt; 5%</span> ' +
            '<span class="wd-count" id="watchDeclineCount"></span>' +
            '<span class="rt-refresh-icon" onclick="event.stopPropagation();watchRefreshTrajectory()" title="刷新">↻</span></h3>' +
            '<div id="watchDeclineBody" style="display:none"><div class="lt-trajectory-loading">加载中...</div></div></div>' +

            '<div class="rt-section lt-trajectory-section" id="twLtTrajectorySection">' +
            '<h3 style="margin:6px 0 8px 0;font-size:0.9em;color:#4fc3f7;">🌐 涨停原因标签轨迹 <span class="count-badge">近20日</span> ' +
            '<span class="rt-refresh-icon" onclick="watchRefreshTrajectory()" title="刷新轨迹数据">↻</span></h3>' +
            '<div id="twLtTrajectoryBody"><div class="lt-trajectory-loading">加载中...</div></div></div>' +

            '<div class="rt-section lt-trajectory-section" id="watchPromoSection">' +
            '<div id="watchPromoBody"><div class="lt-trajectory-loading">加载中...</div></div></div>' +

            '<div class="rt-section lt-trajectory-section" id="watchZtClassSection">' +
            '<h3 class="wd-head wz-head" onclick="watchToggleZtClass()" title="点击展开 / 折叠">' +
            '<span class="wd-arrow" id="watchZtClassArrow">▶</span>🗂 涨停分类 <span class="count-badge">近10日 · 涨停+大涨 · 按精选板块</span> ' +
            '<span class="wd-count" id="watchZtClassCount"></span></h3>' +
            '<div id="watchZtClassBody" style="display:none"><div class="lt-trajectory-loading">加载中...</div></div></div>';
    }

    function tickBar() {
        var c = document.getElementById('watchClock');
        if (!c) return;
        c.textContent = fmtClock(bjNow());
        var live = _twsRefreshGate();
        var s = document.getElementById('watchState');
        s.textContent = live ? '盘中 · 自动刷新中' : '非交易时段 · 暂停刷新，显示最近交易日收盘状态';
        s.className = 'watch-state' + (live ? ' live' : '');
        if (live && !wasLive) setTimeout(tick, 0);       // 刚进入盘中（9:15）立即刷新一次，不等下一个 30s
        wasLive = live;
    }

    window.watchRefreshTrajectory = function () {
        return fetch(_trajPlainUrl('tw') + '&surge=1&_t=' + Date.now())
            .then(function (r) { return r.json(); })
            .then(function (d) {
                var body = document.getElementById('twLtTrajectoryBody');
                if (body && d && d.dates && d.dates.length) {
                    var decl = document.getElementById('watchDeclineBody');
                    if (decl) decl.innerHTML = watchRenderDecline(d);   // 只替换内容，展开/折叠状态保留在容器上，30s 刷新不会被重置
                    var dc = document.getElementById('watchDeclineCount');
                    if (dc && d.decline) dc.textContent = d.decline.total + ' 只 · ' + d.decline.themes.length + ' 个题材';
                    body.innerHTML = watchRenderTrajectory(d, 'twLtTrajectoryBody');
                    var ts = document.getElementById('watchTrajTs');
                    if (ts) ts.textContent = lastTraj = fmtClock(bjNow());
                }
            })
            .catch(function (e) { console.error('刷新轨迹失败:', e); });
    };

    // 板块强度表 + 今日涨停时间轴 + 晋级：一次取数、整体重绘；保留时间轴/晋级的横向滚动位置
    function refreshStrength(initial) {
        var body = document.getElementById('twWindStrengthBody');
        var scrolls = [].map.call(document.querySelectorAll('#twWindStrengthSection .tws-tl-scroll, #watchPromoSection .tws-tl-scroll'),
            function (el) { return el.scrollLeft; });
        return Promise.all([
            initial ? Promise.resolve(typeof _kplLevelEnsureHotRank === 'function' ? _kplLevelEnsureHotRank() : null).catch(function () {}) : null,
            fetch('/api/sector_ranking?max_age=25&_t=' + Date.now()).then(function (r) { return r.json(); }).catch(function () { return null; }),
            fetch('/api/theme_wind_strength?max_age=15&lib=1&_t=' + Date.now()).then(function (r) { return r.json(); }).catch(function () { return null; })
        ]).then(function (arr) {
            if (!arr[2] || arr[2].error) throw new Error((arr[2] && arr[2].error) || '板块强度数据获取失败');
            _themeWindStrengthData = arr[2];
            body.innerHTML = renderThemeWindStrength(arr[1], arr[2]);
            [].forEach.call(document.querySelectorAll('#twWindStrengthSection .tws-tl-scroll, #watchPromoSection .tws-tl-scroll'),
                function (el, i) { if (scrolls[i]) el.scrollLeft = scrolls[i]; });
            var ts = document.getElementById('watchStrengthTs');
            if (ts) ts.textContent = lastStrength = fmtClock(bjNow());
        }).catch(function (e) {
            if (initial) body.innerHTML = '<div class="watch-err">加载失败：' + (e && e.message || e) +
                '<button onclick="location.reload()">重试</button></div>';
            else console.error('刷新板块强度失败:', e);
        });
    }
    // 大盘指数卡片：/api/market_sentiment 的 indices（上证/深成/创业板/科创50/沪深300/中证500）；失败时保留上一次内容
    window.watchRefreshIndices = function () {
        return fetch('/api/market_sentiment?_t=' + Date.now())
            .then(function (r) { return r.json(); })
            .then(function (d) {
                var list = (d && d.indices) || [];
                var body = document.getElementById('watchIndexBody');
                if (!body || !list.length) return;
                body.innerHTML = list.map(function (x) {
                    var pct = Number(x.change_pct), amt = Number(x.change_amt);
                    var cls = !isFinite(pct) || pct === 0 ? 'flat' : (pct > 0 ? 'up' : 'down');
                    var sg = pct > 0 ? '+' : '';
                    return '<div class="wi-card wi-' + cls + '"><span class="wi-name">' + _kplEsc(x.name) + '</span>' +
                        '<b class="wi-pct">' + (isFinite(pct) ? sg + pct.toFixed(2) + '%' : '--') + '</b>' +
                        '<span class="wi-px">' + (isFinite(Number(x.price)) ? Number(x.price).toFixed(2) : '--') +
                        (isFinite(amt) ? ' <i>' + (amt > 0 ? '+' : '') + amt.toFixed(2) + '</i>' : '') + '</span></div>';
                }).join('');
                var ts = document.getElementById('watchIndexTs');
                if (ts) ts.textContent = (d.data_date ? d.data_date + ' · ' : '') + '更新 ' + fmtClock(bjNow());
            })
            .catch(function (e) { console.error('刷新大盘指数失败:', e); });
    };
    // 「跌幅」卡片默认折叠，点标题展开；折叠时标题上仍显示股票数/题材数
    window.watchToggleDecline = function () {
        var body = document.getElementById('watchDeclineBody'), arrow = document.getElementById('watchDeclineArrow');
        if (!body) return;
        var open = body.style.display === 'none';
        body.style.display = open ? '' : 'none';
        if (arrow) arrow.textContent = open ? '▼' : '▶';
    };

    // ===================== 个股查询页（独立视图，点「返回」回到盯盘主页） =====================
    // 自上而下：搜索框(自动补全) → 板块名+tags 平铺 → KPL涨停记录 → K线 → 板块横排(近15日涨停/大涨，可拓展) → tags 横排(同)
    var sq = {ladderToken: 0, ladderDate: '', ladderLive: '', firstOpen: false, tagSel: {}, root: null, code: '', scrollY: 0, timer: null, token: 0};
    function sqEsc(v) { return _kplEsc(v == null ? '' : String(v)); }
    function sqPct(v) { v = Number(v); return (v === null || !isFinite(v)) ? '' : (v > 0 ? '+' : '') + v.toFixed(2) + '%'; }
    function sqBuildRoot() {
        var el = document.createElement('div');
        el.id = 'watchSqRoot';
        el.style.display = 'none';
        el.innerHTML =
            '<div class="sq2-bar"><button class="sq2-back" data-sq-back="1">← 返回实时盯盘</button><h2>🔍 个股查询</h2></div>' +
            '<div class="sq2-sec sq2-ladder" id="sq2Ladder"></div>' +
            '<div class="sq2-search"><div class="sq2-box"><svg class="sq2-ico" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>' +
            '<input id="sq2Input" type="text" placeholder="输入股票名称 / 代码，或板块、tags 名称，如 华电辽能、600396、固态电池" autocomplete="off" spellcheck="false">' +
            '<button class="sq2-go" data-sq-go="1">搜索</button></div><div class="sq2-sug" id="sq2Sug"></div></div>' +
            '<div id="sq2Result"><div class="lt-trajectory-loading">输入股票名称或代码开始查询</div></div>' +
            '<div class="sq2-sec" id="sq2ThemeSec"><div class="sq2-title">题材复盘 <small>点击任意板块 / tags 名称（连板天梯、板块列、标签行均可），在此展示该题材近1个月的涨停节奏</small>' +
            '<button class="sq2-tagfilter-btn" data-sq-tagpanel="1" title="只按 tags 过滤涨停节奏里的股票">🏷 tags 过滤</button></div>' +
            '<div class="sq2-chiprow" id="sq2ThemeChips"></div><div class="sq2-tagpanel" id="sq2TagPanel" style="display:none"></div><div id="sq2ThemeBody"><div class="sq2-none sq2-theme-hint">未选择题材。点击上方任意板块 / tags 名称即可查看。</div></div></div>';
        el.addEventListener('click', sqOnClick);
        document.querySelector('.container').appendChild(el);
        var inp = el.querySelector('#sq2Input');
        inp.addEventListener('input', function () {
            clearTimeout(sq.timer);
            var q = inp.value.trim(), box = document.getElementById('sq2Sug');
            if (!q) { box.classList.remove('on'); return; }
            sq.timer = setTimeout(function () {
                fetch('/api/sq_suggest?q=' + encodeURIComponent(q)).then(function (r) { return r.json(); }).then(function (d) {
                    if (inp.value.trim() !== q) return;
                    if (!d || !d.length) { box.classList.remove('on'); return; }
                    var lab = {stock: '股票', plate: '板块', tag: 'tags'};
                    box.innerHTML = d.map(function (x) {
                        return '<div class="sq2-sug-item" data-sq-pick="' + x.type + ':' + sqEsc(x.type === 'stock' ? x.code : x.name) + '">' +
                            '<i class="sq2-sug-t sq2-sug-' + x.type + '">' + lab[x.type] + '</i>' +
                            (x.type === 'stock' ? '<b>' + sqEsc(x.code) + '</b> ' + sqEsc(x.name) : sqEsc(x.name) + ' <small>' + x.n + ' 只</small>') + '</div>';
                    }).join('');
                    box.classList.add('on');
                }).catch(function () { box.classList.remove('on'); });
            }, 180);
        });
        inp.addEventListener('keydown', function (e) { if (e.key === 'Enter') sqSearch(inp.value); });
        document.addEventListener('click', function (e) {
            if (!e.target.closest || !e.target.closest('.sq2-search')) { var b = document.getElementById('sq2Sug'); if (b) b.classList.remove('on'); }
        });
        return el;
    }
    function sqOnClick(e) {
        var t = e.target.closest && e.target.closest('[data-sq-back],[data-sq-go],[data-sq-code],[data-sq-open],[data-sq-expand],[data-sq-jump],[data-sq-theme],[data-sq-toggle],[data-sq-pick],[data-sq-toggle-first],[data-sq-tagpanel],[data-sq-tagsel],[data-sq-ldate]');
        if (!t) return;
        if (t.hasAttribute('data-sq-back')) return watchCloseStockQuery();
        if (t.hasAttribute('data-sq-go')) return sqSearch(document.getElementById('sq2Input').value);
        if (t.hasAttribute('data-sq-expand')) return sqExpand(t);
        if (t.hasAttribute('data-sq-jump')) {
            var c = document.getElementById(t.getAttribute('data-sq-jump'));
            if (c) { c.scrollIntoView({behavior: 'smooth', block: 'center', inline: 'center'}); c.classList.add('flash'); setTimeout(function () { c.classList.remove('flash'); }, 1500); }
            return;
        }
        if (t.hasAttribute('data-sq-ldate')) return sqLoadLadder(t.getAttribute('data-sq-ldate'));
        if (t.hasAttribute('data-sq-tagpanel')) {
            var tp = document.getElementById('sq2TagPanel');
            tp.style.display = tp.style.display === 'none' ? '' : 'none';
            return;
        }
        if (t.hasAttribute('data-sq-tagsel')) {
            var tg = t.getAttribute('data-sq-tagsel');
            if (tg === '*') sq.tagSel = {}; else sq.tagSel[tg] = !sq.tagSel[tg];
            return sqThemeRender();
        }
        if (t.hasAttribute('data-sq-toggle-first')) {
            var fr = t.closest('.sq2-first'), col = fr.classList.toggle('collapsed'); sq.firstOpen = !col;
            t.querySelector('small').textContent = (t.querySelector('small').textContent.replace(/[▸▾]/, '') + (col ? '▸' : '▾')).replace(/\s+/g, ' ');
            return;
        }
        if (t.hasAttribute('data-sq-pick')) {
            var pk = t.getAttribute('data-sq-pick'), cut = pk.indexOf(':');
            document.getElementById('sq2Sug').classList.remove('on');
            return sqPick(pk.slice(0, cut), pk.slice(cut + 1));
        }
        if (t.hasAttribute('data-sq-toggle')) return document.getElementById(t.getAttribute('data-sq-toggle')).classList.toggle('collapsed');
        if (t.hasAttribute('data-sq-theme')) return sqThemeShow(t.getAttribute('data-sq-theme'));
        if (t.hasAttribute('data-sq-open')) {                  // 板块/tag 列里的股票：弹出 K 线弹框，不跳转
            var nm = t.getAttribute('data-sq-name') || '';
            return openDsStockFromRhythm(nm, t.getAttribute('data-sq-open'), '', [], -1);
        }
        var code = t.getAttribute('data-sq-code');
        document.getElementById('sq2Sug').classList.remove('on');
        sqLoad(code);
    }
    // 搜索：6位代码 → 个股；否则取联想第一项——股票显示个股情况，板块 / tags 显示题材复盘
    function sqSearch(val) {
        val = (val || '').trim();
        if (!val) return;
        document.getElementById('sq2Sug').classList.remove('on');
        var m = val.match(/(\d{6})/);
        if (m) return sqLoad(m[1]);
        fetch('/api/sq_suggest?q=' + encodeURIComponent(val)).then(function (r) { return r.json(); }).then(function (d) {
            if (d && d.length) sqPick(d[0].type, d[0].type === 'stock' ? d[0].code : d[0].name);
            else document.getElementById('sq2Result').innerHTML = '<div class="empty">未找到匹配的股票 / 板块 / tags</div>';
        });
    }
    function sqPick(type, v) {
        if (type === 'stock') return sqLoad(v);
        document.getElementById('sq2Input').value = v;
        sqThemeShow(type + ':' + v, true);
    }
    // 状态标识：最新日 → N板 / 首板 / 大涨；已断 → 曾N板（+断板天数）/ 曾首板（+N）/ 大涨（+N）
    function sqStatus(s) {
        if (!s.last || s.gap === null || s.gap === undefined) return '';
        var base = s.lb >= 2 ? s.lb + '板' : (s.lb === 1 ? '首板' : '大涨');
        return s.gap === 0 ? base : (s.lb >= 1 ? '曾' + base : base) + '（+' + s.gap + '）';
    }
    function sqStockRow(s, selfCode) {
        var tip = (s.ev || []).map(function (e) { return e[0] + (e[1] >= 2 ? ' ' + e[1] + '板' : (e[1] === 1 ? ' 首板' : ' 大涨')); }).join('，');
        var st = sqStatus(s);
        var cls = s.gap === 0 ? (s.lb >= 2 ? ' hot' : '') : ' broke';
        var pct = sqPct(s.pct);
        return '<div class="sq2-stk' + (s.code === selfCode ? ' self' : '') + '" data-sq-open="' + sqEsc(s.code) + '" data-sq-name="' + sqEsc(s.name) + '" title="' + sqEsc(s.name + ' ' + s.code + (tip ? ' · ' + tip : '')) + '">' +
            '<div class="sq2-l1"><i class="wz-bd wz-bd-' + sqEsc(s.board || '主') + '">' + sqEsc(s.board || '主') + '</i><span class="wz-nm">' + sqEsc(s.name || s.code) + '</span>' +
            (pct ? '<b class="' + (s.pct > 0 ? 'wz-up' : (s.pct < 0 ? 'wz-down' : '')) + '">' + pct + '</b>' : '') + '</div>' +
            (st ? '<div class="sq2-l2"><span class="sq2-st' + cls + '">' + sqEsc(st) + '</span></div>' : '') + '</div>';
    }
    function sqColumns(kind, cols, selfCode) {
        if (!cols.length) return '<div class="lt-trajectory-loading">暂无' + (kind === 'plate' ? '板块' : 'tags') + '</div>';
        return '<div class="sq2-scroll"><div class="sq2-cols">' + cols.map(function (c, i) {
            var id = 'sq2col-' + kind + '-' + i;
            return '<div class="sq2-col sq2-cat-' + sqEsc(c.cat || 'neutral') + '" id="' + id + '" data-kind="' + kind + '" data-name="' + sqEsc(c.name) + '">' +
                '<div class="sq2-colhead"><span class="sq2-colname" data-sq-theme="' + kind + ':' + sqEsc(c.name) + '" title="点击查看该题材的涨停节奏（题材复盘）">' + sqEsc(c.name) + '</span>' +
                '<small>' + c.active.length + ' / ' + c.total + '</small>' +
                '<button class="sq2-exp" data-sq-expand="1">拓展</button></div>' +
                '<div class="sq2-list">' + (c.active.length ? c.active.map(function (s) { return sqStockRow(s, selfCode); }).join('') :
                    '<div class="sq2-none">近15日无涨停/大涨</div>') + '</div></div>';
        }).join('') + '</div></div>';
    }
    function sqExpand(btn) {
        var col = btn.closest('.sq2-col'), list = col.querySelector('.sq2-list');
        if (col.classList.contains('expanded')) {                // 收起 → 回到「近15日涨停/大涨」
            col.classList.remove('expanded');
            list.innerHTML = col._activeHtml;
            btn.textContent = '拓展';
            return;
        }
        col._activeHtml = list.innerHTML;
        btn.textContent = '加载中…';
        fetch('/api/sq_members?kind=' + col.getAttribute('data-kind') + '&name=' + encodeURIComponent(col.getAttribute('data-name')))
            .then(function (r) { return r.json(); }).then(function (d) {
                list.innerHTML = d.stocks.map(function (s) { return sqStockRow(s, sq.code); }).join('') || '<div class="sq2-none">无成分股</div>';
                col.classList.add('expanded');
                btn.textContent = '收起（共 ' + d.total + '）';
            }).catch(function () { btn.textContent = '拓展'; });
    }
    function sqLoad(code) {
        var out = document.getElementById('sq2Result');
        var token = ++sq.token;
        sq.code = code;
        out.innerHTML = '<div class="lt-trajectory-loading">加载中...</div>';
        Promise.all([
            fetch('/api/stock_detail?code=' + encodeURIComponent(code)).then(function (r) { return r.json(); }).catch(function () { return {}; }),
            fetch('/api/sq_stock?code=' + encodeURIComponent(code)).then(function (r) { return r.json(); })
        ]).then(function (res) {
            if (token !== sq.token) return;
            var det = res[0] || {}, g = res[1];
            var name = g.name || det.name || code;
            document.getElementById('sq2Input').value = name;
            var chipsP = g.plates.map(function (c, i) { return '<span class="sq2-chip sq2-chip-p" data-sq-theme="plate:' + sqEsc(c.name) + '" title="点击查看题材复盘">' + sqEsc(c.name) + '</span>'; }).join('');
            var chipsT = g.tags.map(function (c, i) { return '<span class="sq2-chip sq2-chip-t" data-sq-theme="tag:' + sqEsc(c.name) + '" title="点击查看题材复盘">' + sqEsc(c.name) + '</span>'; }).join('');
            var self = g.self || {};
            var h = '<div class="sq2-head"><h3>' + sqEsc(name) + ' <span class="sq2-code">' + sqEsc(code) + '</span> <i class="wz-bd wz-bd-' + sqEsc(self.board || '主') + '">' + sqEsc(self.board || '主') + '</i>' +
                (sqPct(self.pct) ? ' <b class="' + (self.pct > 0 ? 'wz-up' : 'wz-down') + '">' + sqPct(self.pct) + '</b>' : '') + '</h3>' +
                (g.in_lib ? '' : '<div class="sq2-warn">该股票不在开盘红精选板块库中，板块 / tags 为空</div>') +
                '<div class="sq2-chiprow"><span class="sq2-lab">板块</span>' + (chipsP || '<span class="sq2-none">无</span>') + '</div>' +
                '<div class="sq2-chiprow"><span class="sq2-lab">tags</span>' + (chipsT || '<span class="sq2-none">无</span>') + '</div></div>';
            h += '<div class="sq2-sec"><div class="sq2-title">KPL涨停记录</div><div class="sq2-kpl">' +
                (typeof renderKplRecords === 'function' ? renderKplRecords(det.kpl_records, code, name) : '') + '</div></div>';
            h += '<div class="sq2-sec"><div class="sq2-title">K线图</div><div class="sq2-chartrow">' +
                '<div class="sq2-chart"><div class="sq2-chart-t">日K线 <button class="img-refresh-btn" onclick="reloadSinaImg(this)" title="重新加载">&#x27f3;</button></div>' +
                '<img class="sq2-kline" data-orig-src="' + sinaKlineImg(code) + '" src="' + sinaKlineImg(code) + '" onerror="retryImg(this)"></div>' +
                '<div class="sq2-chart"><div class="sq2-chart-t">分时图 <button class="img-refresh-btn" onclick="reloadSinaImg(this)" title="重新加载">&#x27f3;</button></div>' +
                '<img class="sq2-kline" data-orig-src="' + sinaMinImg(code) + '" src="' + sinaMinImg(code) + '" onload="checkMinImgLoad(this)" onerror="retryImg(this)"></div></div></div>';
            h += '<div class="sq2-sec"><div class="sq2-title">板块 <small>每列 = 该板块近15个交易日（' + sqEsc((g.dates[0] || '').slice(5)) + '~' + sqEsc((g.dates[g.dates.length - 1] || '').slice(5)) + '）有过涨停/大涨的股票（不含ST，已隐藏泛概念），排序：连板高度 → 首板 → 大涨 → 已断板（曾N板（+X）、大涨（+X）只标识，按断板天数）</small></div>' +
                sqColumns('plate', g.plates, code) + '</div>';
            h += '<div class="sq2-sec"><div class="sq2-title">tags <small>每列 = 具有相同 tag 的近15日涨停/大涨股票（点击股票弹出K线）</small></div>' + sqColumns('tag', g.tags, code) + '</div>';
            out.innerHTML = h;
            var tc = document.getElementById('sq2ThemeChips');
            if (tc) {
                tc.innerHTML = (g.plates.length || g.tags.length ? '<span class="sq2-lab">' + sqEsc(name) + '</span>' : '') +
                    g.plates.map(function (c) { return '<span class="sq2-chip sq2-chip-p" data-sq-theme="plate:' + sqEsc(c.name) + '">' + sqEsc(c.name) + '</span>'; }).join('') +
                    g.tags.map(function (c) { return '<span class="sq2-chip sq2-chip-t" data-sq-theme="tag:' + sqEsc(c.name) + '">' + sqEsc(c.name) + '</span>'; }).join('');
            }
            sqMarkTheme();
        }).catch(function (e) {
            if (token === sq.token) out.innerHTML = '<div class="watch-err">加载失败：' + sqEsc(e && e.message || e) + '</div>';
        });
    }

    // ---- 连板涨停表现（搜索框上方，同题材风向的「连板涨停表现」：N板→2板 + 昨日断板 + 首板）；板块/tags 用新库，每只股票显示全部板块和 tags ----
    function sqLadderChip(x, broken, lv) {
        var ft = Number(x.first_time), tm = (!broken && ft && ft < 999999) ? ('0' + Math.floor(ft / 10000)).slice(-2) + ':' + ('0' + Math.floor(ft / 100) % 100).slice(-2) : '';
        var plates = (x.plates || []).slice().sort(function (a, b) { return (b === x.plate) - (a === x.plate); });
        return '<div class="sq2-lchip' + (broken ? ' broken' : '') + '">' +
            '<div class="sq2-l1">' + (tm ? '<span class="wz-tm">' + tm + '</span>' : '') +
            '<i class="wz-bd wz-bd-' + sqEsc(x.board || '主') + '">' + sqEsc(x.board || '主') + '</i>' +
            '<span class="wz-nm sq2-lname sq2-lv-' + (broken ? 'broken' : (lv >= 5 ? 'high' : lv)) + '" data-sq-open="' + sqEsc(x.code) + '" data-sq-name="' + sqEsc(x.name) + '" title="点击弹出K线">' + sqEsc(x.name) + '</span>' +
            '<span class="sq2-lcode">' + sqEsc(x.code) + '</span>' +
            (sqPct(x.pct) ? '<b class="' + (x.pct > 0 ? 'wz-up' : (x.pct < 0 ? 'wz-down' : '')) + '">' + sqPct(x.pct) + '</b>' : '') + '</div>' +
            '<div class="sq2-l3">' + plates.map(function (n) {
                return '<span class="sq2-chip sq2-chip-p' + (n === x.plate ? ' main' : '') + '" data-sq-theme="plate:' + sqEsc(n) + '">' + sqEsc(n) + '</span>';
            }).join('') + (x.tags || []).map(function (n) {
                return '<span class="sq2-chip sq2-chip-t" data-sq-theme="tag:' + sqEsc(n) + '">' + sqEsc(n) + '</span>';
            }).join('') + '</div></div>';
    }
    // 日期：近15个交易日，默认最新交易日；盘中最新日=实时（30s 随总时钟刷新）。已收盘日由服务端提前计算并落盘，点击直接加载
    function sqLoadLadder(date, silent) {
        var box = document.getElementById('sq2Ladder');
        if (!box) return;
        var token = ++sq.ladderToken;
        if (!silent && date) box.classList.add('loading');
        fetch('/api/sq_ladder' + (date ? '?date=' + encodeURIComponent(date) : '')).then(function (r) { return r.json(); }).then(function (d) {
            if (token !== sq.ladderToken) return;
            box.classList.remove('loading');
            if (!d || !d.date) { box.innerHTML = '<div class="sq2-title">📈 连板涨停表现</div><div class="sq2-none">暂无数据</div>'; return; }
            sq.ladderDate = d.date; sq.ladderLive = d.is_live ? d.date : '';
            var n = (d.levels || []).reduce(function (a, l) { return a + l.current.length; }, 0);
            var h = '<div class="sq2-title sq2-ltoggle" data-sq-toggle="sq2Ladder" title="点击折叠 / 展开">📈 连板涨停表现 <small>' + sqEsc(d.date) + (d.is_live ? ' · <b class="sq2-livetag">盘中实时</b>' : '') +
                ' · 连板 ' + n + ' 只 · 首板 ' + (d.first_total || 0) + ' 只 · 点击名称弹出K线，点击板块 / tags 查看题材复盘</small></div>' +
                '<div class="sq2-ldates">' + (d.dates || []).slice().reverse().map(function (x) {
                    return '<span class="sq2-dchip' + (x === d.date ? ' on' : '') + (x === d.live ? ' live' : '') + '" data-sq-ldate="' + sqEsc(x) + '">' + sqEsc(x.slice(5)) + (x === d.live ? '<i>盘中</i>' : '') + '</span>';
                }).join('') + '</div><div class="sq2-ladder-rows">';
            (d.levels || []).forEach(function (l) {
                h += '<div class="tws-ladder-row"><div class="tws-ladder-level sc-lb' + (l.level >= 5 ? 'high' : l.level) + '">' + l.level + '板</div><div class="tws-ladder-groups">';
                if (l.current.length) h += '<div class="tws-ladder-group"><span class="tws-ladder-label">' + (d.is_live ? '今日' : '当日') + l.level + '板</span><span class="tws-ladder-chips">' + l.current.map(function (x) { return sqLadderChip(x, false, l.level); }).join('') + '</span></div>';
                if (l.broken.length) h += '<div class="tws-ladder-group tws-ladder-group-broken"><span class="tws-ladder-label">前一交易日' + (l.level - 1) + '板，当日未涨停</span><span class="tws-ladder-chips">' + l.broken.map(function (x) { return sqLadderChip(x, true); }).join('') + '</span></div>';
                h += '</div></div>';
            });
            if ((d.first || []).length) {
                h += '<div class="tws-ladder-row tws-ladder-first sq2-first' + (sq.firstOpen ? '' : ' collapsed') + '"><div class="tws-ladder-level sc-lb1 sq2-ftoggle" data-sq-toggle-first="1" title="点击展开 / 折叠首板">首板<small>' + (d.first_total || 0) + (sq.firstOpen ? ' ▾' : ' ▸') + '</small></div><div class="tws-ladder-groups">';
                d.first.forEach(function (g) {
                    h += '<div class="tws-ladder-group tws-ladder-group-first"><span class="tws-ladder-label"><span class="sq2-chip sq2-chip-p main" data-sq-theme="plate:' + sqEsc(g.plate) + '">' + sqEsc(g.plate) + '</span> <em>' + g.stocks.length + '只首板</em></span>' +
                        '<span class="tws-ladder-chips">' + g.stocks.map(function (x) { return sqLadderChip(x, false, 1); }).join('') + '</span></div>';
                });
                h += '</div></div>';
            }
            box.innerHTML = h + '</div>';
            sqMarkTheme();
        }).catch(function () { box.classList.remove('loading'); if (!silent) box.innerHTML = ''; });
    }
    window.watchSqTick = function () {          // 30s 总时钟：个股查询页可见且正看盘中实时日时刷新天梯
        if (sq.root && sq.root.style.display !== 'none' && sq.ladderLive) sqLoadLadder(sq.ladderLive, true);
    };
    function sqMarkTheme() {
        [].forEach.call(document.querySelectorAll('#watchSqRoot [data-sq-theme]'), function (c) {
            c.classList.toggle('on', !!sqTheme.key && c.getAttribute('data-sq-theme') === sqTheme.key);
        });
    }
    // ---- 题材复盘·涨停节奏：复用主页面「题材复盘」的 _kplRenderRhythmGrid（同内容/同交互/同样式），数据换成板块或 tag 的成分股 ----
    var sqTheme = {key: '', token: 0, seq: 0, data: null, kind: '', name: ''};
    function sqScrollToTheme() {        // 题材复盘在页面最下方：点击后一定滚到它，否则看起来「没反应」
        var sec = document.getElementById('sq2ThemeSec');
        if (sec) sec.scrollIntoView({behavior: 'smooth', block: 'start'});
    }
    function sqThemeShow(key, force) {
        var body = document.getElementById('sq2ThemeBody');
        if (!body) return;
        var sep = key.indexOf(':'), kind = key.slice(0, sep), name = key.slice(sep + 1);
        if (!force && sqTheme.key === key && body.innerHTML) {            // 再点一次 = 收起
            sqTheme.key = ''; sqTheme.data = null;
            body.innerHTML = '<div class="sq2-none sq2-theme-hint">未选择题材。点击上方任意板块 / tags 名称即可查看。</div>';
            document.getElementById('sq2TagPanel').innerHTML = '';
            sqMarkTheme();
            return;
        }
        sqTheme.key = key; sqTheme.data = null; sq.tagSel = {};
        document.getElementById('sq2TagPanel').innerHTML = '';
        sqMarkTheme();
        var token = ++sqTheme.token;
        body.innerHTML = '<div class="lt-trajectory-loading">加载「' + sqEsc(name) + '」涨停节奏...</div>';
        sqScrollToTheme();
        var now = new Date(), st = new Date(now); st.setMonth(st.getMonth() - 1);
        var f = function (d) { return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); };
        fetch('/api/sq_theme?kind=' + kind + '&name=' + encodeURIComponent(name) + '&date_start=' + f(st) + '&date_end=' + f(now))
            .then(function (r) { return r.json(); }).then(function (d) {
                if (token !== sqTheme.token) return;
                if (!d || d.error) throw new Error((d && d.error) || '加载失败');
                sqTheme.data = d; sqTheme.kind = kind; sqTheme.name = name;
                sqThemeRender();
                sqScrollToTheme();
            }).catch(function (e) {
                if (token === sqTheme.token) body.innerHTML = '<div class="watch-err">加载失败：' + sqEsc(e && e.message || e) + '</div>';
            });
    }
    // 涨停节奏里的上板时间：本地首封库没有的（含最新交易日）用 KPL 行自带的 first_time 补上
    function sqFillZtTimes(rows) {
        var m = {};
        (rows || []).forEach(function (r) {
            var ft = Number(r.first_time);
            if (r.date && r.stock_code && ft && ft < 999999) m[r.date.replace(/-/g, '') + r.stock_code] = ft;
        });
        var run = function () {
            [].forEach.call(document.querySelectorAll('#sq2ThemeBody .rg-first-zt-time'), function (n) {
                if (n.textContent) return;
                var v = m[(n.getAttribute('data-first-zt-date') || '') + (n.getAttribute('data-first-zt-code') || '')];
                var t = v && _kplFormatFirstZtTime(v);
                if (t) { n.textContent = t; n.title = '首次涨停时间 ' + t; }
            });
        };
        run(); setTimeout(run, 700); setTimeout(run, 2500);
    }
    // 渲染（可重复调用：勾选 tags 过滤时只重画，不再请求）：只按 tags 过滤 = 只保留命中任一已选 tag 的股票行
    function sqThemeRender() {
        var d = sqTheme.data, body = document.getElementById('sq2ThemeBody'), panel = document.getElementById('sq2TagPanel');
        if (!d || !body) return;
        var ct = d.code_tags || {}, rows = d.results || [];
        var sel = Object.keys(sq.tagSel).filter(function (t) { return sq.tagSel[t]; });
        // tags 统计（按当前题材涨停节奏里出现的股票去重）
        var cnt = {}, seen = {};
        rows.forEach(function (r) {
            var c = r.stock_code; if (!c || seen[c]) return; seen[c] = 1;
            (ct[c] || []).forEach(function (t) { cnt[t] = (cnt[t] || 0) + 1; });
        });
        var tags = Object.keys(cnt).sort(function (a, b) { return cnt[b] - cnt[a] || (a < b ? -1 : 1); });
        panel.innerHTML = '<div class="sq2-tp-head">只按 tags 过滤：勾选后仅保留命中任一所选 tags 的股票' +
            (sel.length ? ' <button class="sq2-tp-clear" data-sq-tagsel="*">清除（' + sel.length + '）</button>' : '') + '</div><div class="sq2-chiprow">' +
            (tags.length ? tags.map(function (t) {
                return '<span class="sq2-chip sq2-chip-t' + (sq.tagSel[t] ? ' on' : '') + '" data-sq-tagsel="' + sqEsc(t) + '">' + sqEsc(t) + ' <small>' + cnt[t] + '</small></span>';
            }).join('') : '<span class="sq2-none">无可用 tags</span>') + '</div>';
        var shown = rows;
        _kplGemStrongRise = d.gem_strong_rise || {};
        if (sel.length) {
            var hit = function (c) { return (ct[c] || []).some(function (t) { return sq.tagSel[t]; }); };
            shown = rows.filter(function (r) { return hit(r.stock_code); });
            var gs = {}; Object.keys(_kplGemStrongRise).forEach(function (c) { if (hit(c)) gs[c] = _kplGemStrongRise[c]; });
            _kplGemStrongRise = gs;
        }
        _kplTradeDates = d.trade_dates || [];
        var secId = 'sq' + (++sqTheme.seq);
        var html = _kplRenderRhythmGrid(shown, secId, secId + '-rhythm');
        var nStocks = {}; shown.forEach(function (r) { nStocks[r.stock_code] = 1; });
        body.innerHTML = '<div class="sq2-theme-head"><b>' + (sqTheme.kind === 'plate' ? '板块' : 'tag') + '：' + sqEsc(sqTheme.name) + '</b><span>成分股 ' + (d.members || 0) + ' 只（不含ST）· 近1个月' +
            (sel.length ? ' · 已按 tags 过滤：' + sel.map(sqEsc).join('、') + '（' + Object.keys(nStocks).length + ' 只）' : '') + '</span></div>' +
            '<div class="board-section merged-section">' + (html || '<div class="sq2-none">近1个月该题材成分股无涨停 / 大涨' + (sel.length ? '（当前 tags 过滤下）' : '') + '</div>') + '</div>';
        _kplLoadFirstZtTimes();
        sqFillZtTimes(shown);
        var grid = document.getElementById('kpl-rhythm-grid-' + secId);
        if (!grid) return;
        [].forEach.call(grid.querySelectorAll('.rg-row[data-stock]'), function (row) {
            row.addEventListener('mouseenter', function () {
                var nm = this.getAttribute('data-stock');
                [].forEach.call(grid.querySelectorAll('.rg-row[data-stock]'), function (o) {
                    [].forEach.call(o.querySelectorAll('.stock-block'), function (b) { b.classList.toggle('highlighted', o.getAttribute('data-stock') === nm); });
                });
            });
            row.addEventListener('mouseleave', function () {
                [].forEach.call(grid.querySelectorAll('.rg-row .stock-block'), function (b) { b.classList.remove('highlighted'); });
            });
            [].forEach.call(row.querySelectorAll('.stock-block'), function (block) {
                block.addEventListener('click', function (e) {
                    e.stopPropagation();
                    var nm = row.getAttribute('data-stock'), code = this.getAttribute('data-code');
                    if (!nm || !code) return;
                    var nav = _buildRhythmNavList(this), idx = -1;
                    for (var i = 0; i < nav.length; i++) { if (nav[i].code === code) { idx = i; break; } }
                    openDsStockFromRhythm(nm, code, '', nav, idx);
                });
            });
        });
    }
    // 进入：query 可为股票名称或代码，传入则自动搜索；返回：恢复盯盘主页和滚动位置
    window.watchOpenStockQuery = function (query) {
        if (!sq.root) sq.root = sqBuildRoot();
        var main = document.getElementById('watchRoot'), back = document.getElementById('watchBackNav');
        if (main.style.display !== 'none') sq.scrollY = window.scrollY;
        main.style.display = 'none';
        if (back) back.style.display = 'none';
        sq.root.style.display = '';
        window.scrollTo(0, 0);
        sqLoadLadder(sq.ladderDate && sq.ladderDate !== sq.ladderLive ? sq.ladderDate : null);
        if (query) { document.getElementById('sq2Input').value = query; sqSearch(query); }
        else document.getElementById('sq2Input').focus();
    };
    window.watchCloseStockQuery = function () {
        if (sq.root) sq.root.style.display = 'none';
        var main = document.getElementById('watchRoot'), back = document.getElementById('watchBackNav');
        main.style.display = '';
        if (back) back.style.display = '';
        window.scrollTo(0, sq.scrollY || 0);
    };
    // K 线弹框：去掉「东财概念标签」；「开盘红行业 / 概念标签」改为「开盘啦」，下面补上新库里的 板块 与 tags
    window._renderDcConcepts = function () { return ''; };
    window._renderKphIndustryConcepts = function (data, compact) {
        var esc = function (v) { return (typeof escapeHtml === 'function' ? escapeHtml(v) : String(v)); };
        var pill = function (v, bg, fg, bd) { return '<span class="stock-detail-tag" style="background:' + bg + ';color:' + fg + ';border-color:' + bd + ';">' + esc(v) + '</span>'; };
        var row = function (lab, arr, bg, fg, bd) {
            return '<div style="display:flex;flex-wrap:wrap;align-items:center;gap:4px;margin-top:6px;"><span style="color:#6b7280;font-size:0.8em;min-width:44px;">' + lab + '</span>' +
                (arr.length ? arr.map(function (c) { return pill(c, bg, fg, bd); }).join('') : '<span style="color:#888;font-size:0.85em;">暂无</span>') + '</div>';
        };
        var date = (data && data.kph_industry_as_of) || '';
        var title = '开盘啦' + (date ? ' · ' + date : '');
        var wrapA = compact ? '<div class="sq-concepts" style="margin-top:8px;"><div class="sq-concepts-label">' : '<div class="ds-stock-kline-section"><div class="ds-stock-kline-label">';
        return wrapA + title + '</div><div>' +
            row('行业/概念', (data && data.kph_industry_concepts) || [], '#fff3e0', '#a45100', '#f1c27d') +
            row('板块', (data && data.kph_plates) || [], '#e3f2fd', '#0d47a1', '#90caf9') +
            row('tags', (data && data.kph_tags) || [], '#f3e5f5', '#6a1b9a', '#ce93d8') +
            '</div></div>';
    };
    // 所有股票 K 线弹框里「查询概念」右边补一个「个股查询」（弹框是主页面脚本动态生成的，用 MutationObserver 兜底）
    function sqInjectButtons() {
        [].forEach.call(document.querySelectorAll('button'), function (b) {
            if (b.textContent.trim() !== '查询概念' || b.getAttribute('data-sq-added')) return;
            b.setAttribute('data-sq-added', '1');
            var m = (b.getAttribute('onclick') || '').match(/sqJumpToKpl\(\s*['"]([^'"]+)['"]/);
            if (!m) return;
            var nb = document.createElement('button');
            nb.textContent = '个股查询';
            nb.className = 'wz-sqbtn';
            nb.style.cssText = 'margin-left:8px;background:#26a69a;color:#fff;border:none;padding:8px 24px;border-radius:6px;font-size:0.95em;font-weight:600;cursor:pointer;';
            nb.onclick = function (e) {
                e.stopPropagation();
                ['closeDsStockModal', 'closeEnlargeCardModal'].forEach(function (fn) { try { if (typeof window[fn] === 'function') window[fn](); } catch (_) {} });
                [].forEach.call(document.querySelectorAll('.modal.active, .modal-overlay.active'), function (x) { x.classList.remove('active'); });
                watchOpenStockQuery(m[1]);
            };
            b.parentNode.insertBefore(nb, b.nextSibling);
        });
    }
    new MutationObserver(function () { sqInjectButtons(); }).observe(document.body, {childList: true, subtree: true});

    // 「涨停分类」：最后一个章节，默认折叠；只显示已收盘落盘的数据，首次展开时取一次，盘中 30s 总时钟不刷新它
    var ztClass = {loaded: false, loading: false};
    function ztFmtPct(v) { v = Number(v); return (v === null || !isFinite(v)) ? '' : (v > 0 ? '+' : '') + v.toFixed(1) + '%'; }
    function ztRenderStock(s) {
        var ft = Number(s.first_time), tm = (s.kind === 'zt' && ft && ft < 999999) ? ('0' + Math.floor(ft / 10000)).slice(-2) + ':' + ('0' + Math.floor(ft / 100) % 100).slice(-2) : '';
        var board = '<i class="wz-bd wz-bd-' + (s.board || '主') + '">' + (s.board || '主') + '</i>';
        var kind = s.kind === 'surge' ? '<i class="wz-badge wz-surge">大涨</i>' : (s.lb >= 2 ? '<i class="wz-badge wz-lb">' + s.lb + '板</i>' : '');
        var pct = ztFmtPct(s.pct);
        var tags = (s.tags || []).slice(0, 3).map(function (t) { return _kplEsc(t); }).join('·');
        return '<div class="wz-stk' + (s.kind === 'surge' ? ' wz-stk-surge' : '') + '" onclick="openDsStockFromRhythm(\'' + _kplEsc(s.name) + '\',\'' + s.code + '\',\'\',[],-1)" title="' + _kplEsc(s.name + ' ' + s.code + (s.tags && s.tags.length ? ' · ' + s.tags.join('、') : '')) + '">' +
            (tm ? '<span class="wz-tm">' + tm + '</span>' : '<span class="wz-tm">--:--</span>') + board +
            '<span class="wz-nm">' + _kplEsc(s.name) + '</span>' + kind +
            (pct ? '<b class="' + (s.pct > 0 ? 'wz-up' : 'wz-down') + '">' + pct + '</b>' : '') +
            (tags ? '<span class="wz-tags">' + tags + '</span>' : '') + '</div>';
    }
    function ztRender(d) {
        var dates = (d.dates || []).slice().reverse();      // 最新交易日在最左
        return '<div class="wz-scroll"><div class="wz-cols">' + dates.map(function (dt, i) {
            var day = d.days[dt] || {groups: []};
            return '<div class="wz-col"><div class="wz-colhead' + (i === 0 ? ' latest' : '') + '">' + dt.slice(5) +
                '<small>涨停 ' + (day.zt || 0) + ' · 大涨 ' + ((day.total || 0) - (day.zt || 0)) + '</small></div>' +
                (day.groups.length ? day.groups.map(function (g) {
                    return '<div class="wz-grp"><div class="wz-gname">' + _kplEsc(g.plate) + ' <span>' + g.n + '</span></div>' +
                        g.stocks.map(ztRenderStock).join('') + '</div>';
                }).join('') : '<div class="lt-trajectory-loading">当日无数据</div>') + '</div>';
        }).join('') + '</div></div>';
    }
    window.watchLoadZtClass = function () {
        if (ztClass.loading) return;
        ztClass.loading = true;
        var body = document.getElementById('watchZtClassBody');
        return fetch('/api/zt_classify?n=10').then(function (r) { return r.json(); }).then(function (d) {
            if (!d || !d.dates || !d.dates.length) throw new Error('暂无数据');
            body.innerHTML = ztRender(d);
            ztClass.loaded = true;
            var c = document.getElementById('watchZtClassCount');
            if (c) c.textContent = d.dates[0].slice(5) + ' ~ ' + d.dates[d.dates.length - 1].slice(5);
        }).catch(function (e) {
            body.innerHTML = '<div class="watch-err">加载失败：' + (e && e.message || e) + '</div>';
        }).then(function () { ztClass.loading = false; });
    };
    window.watchToggleZtClass = function () {
        var body = document.getElementById('watchZtClassBody'), arrow = document.getElementById('watchZtClassArrow');
        if (!body) return;
        var open = body.style.display === 'none';
        body.style.display = open ? '' : 'none';
        if (arrow) arrow.textContent = open ? '▼' : '▶';
        if (open && !ztClass.loaded) watchLoadZtClass();
    };
    window.watchRefreshStrength = function () { return refreshStrength(false); };
    window.manualRefreshTws = window.watchRefreshStrength;      // 标题上的 ↻ 沿用同一条刷新链

    // 30s 总时钟：仅在 9:25~15:00 且页面可见时刷新；K线弹框打开时一并刷新
    function tick() {
        if (!_twsRefreshGate() || document.hidden) return;
        refreshStrength(false);
        watchRefreshTrajectory();
        watchRefreshIndices();
        if (window.watchSqTick) watchSqTick();
        var modal = document.getElementById('tmmThemeKlineModal');
        if (modal && modal.classList.contains('active') && typeof refreshTmmThemeKlines === 'function') refreshTmmThemeKlines();
    }

    function boot() {
        var container = document.querySelector('.container');
        if (!container) return;
        var root = document.createElement('div');
        root.id = 'watchRoot';
        container.appendChild(root);
        var back = document.createElement('button');
        back.id = 'watchBackNav';
        back.textContent = '⬆ 题材导航';
        back.title = '回到表格上方的题材导航';
        back.onclick = function () { watchGoNav(); };
        document.body.appendChild(back);
        renderShell(root);
        currentTab = 'themewind';     // 主页面各轮询以此判断是否在可见页签
        _themeWindLoaded = true;
        tickBar();
        setInterval(tickBar, 1000);
        refreshStrength(true);
        watchRefreshTrajectory();
        watchRefreshIndices();
        setInterval(tick, REFRESH_MS);
        document.addEventListener('visibilitychange', function () { if (!document.hidden) tick(); });
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
    else setTimeout(boot, 0);
})();
