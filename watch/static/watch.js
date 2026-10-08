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

    // —— 关闭主页面自带的 60s 轮询（_twsRefreshBoardLive 有 55s 节流，且不刷新板块强度表）——
    window._twsStartPoll = function () {};
    window._twsPoll = function () {};
    window._twsRefreshBoardLive = function () {};     // 主页面另有 60s 全局定时器会调它，统一由本文件 30s 总时钟接管

    // —— 覆盖：时间轴用压缩午休的版本；时间轴里的题材名点击 → 跳到下方「标签轨迹」表格中对应题材行 ——
    window._twsRenderTimeline = window.watchRenderTimeline;
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
            promo.innerHTML = _twsRenderThemePromotion(d) ||
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
                '<span class="wb-foot-note">全页每 30s 刷新 · 仅 9:25~15:00 自动刷新</span></div>' +
            '</header>' +

            '<div class="rt-section lt-trajectory-section" id="twWindStrengthSection">' +
            '<h3 style="margin:6px 0 8px 0;font-size:0.9em;color:#ffd700;">⚡ 精选板块强度 · Top10细分题材卡片 ' +
            '<span class="rt-refresh-icon" onclick="manualRefreshTws()" title="刷新">↻</span></h3>' +
            '<div id="twWindStrengthBody"><div class="loading">加载中...</div></div></div>' +

            '<div class="rt-section lt-trajectory-section" id="watchDeclineSection">' +
            '<h3 style="margin:6px 0 8px 0;font-size:0.9em;color:#2ee66b;">🔻 跌幅 <span class="count-badge">跌幅 &gt; 5%</span> ' +
            '<span class="rt-refresh-icon" onclick="watchRefreshTrajectory()" title="刷新">↻</span></h3>' +
            '<div id="watchDeclineBody"><div class="lt-trajectory-loading">加载中...</div></div></div>' +

            '<div class="rt-section lt-trajectory-section" id="twLtTrajectorySection">' +
            '<h3 style="margin:6px 0 8px 0;font-size:0.9em;color:#4fc3f7;">🌐 涨停原因标签轨迹 <span class="count-badge">近20日</span> ' +
            '<span class="rt-refresh-icon" onclick="watchRefreshTrajectory()" title="刷新轨迹数据">↻</span></h3>' +
            '<div id="twLtTrajectoryBody"><div class="lt-trajectory-loading">加载中...</div></div></div>' +

            '<div class="rt-section lt-trajectory-section" id="watchPromoSection">' +
            '<div id="watchPromoBody"><div class="lt-trajectory-loading">加载中...</div></div></div>';
    }

    function tickBar() {
        var c = document.getElementById('watchClock');
        if (!c) return;
        c.textContent = fmtClock(bjNow());
        var live = _twsRefreshGate();
        var s = document.getElementById('watchState');
        s.textContent = live ? '盘中 · 自动刷新中' : '非交易时段 · 暂停自动刷新';
        s.className = 'watch-state' + (live ? ' live' : '');
    }

    window.watchRefreshTrajectory = function () {
        return fetch(_trajPlainUrl('tw') + '&surge=1&_t=' + Date.now())
            .then(function (r) { return r.json(); })
            .then(function (d) {
                var body = document.getElementById('twLtTrajectoryBody');
                if (body && d && d.dates && d.dates.length) {
                    var decl = document.getElementById('watchDeclineBody');
                    if (decl) decl.innerHTML = watchRenderDecline(d);
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
            fetch('/api/theme_wind_strength?max_age=15&_t=' + Date.now()).then(function (r) { return r.json(); }).catch(function () { return null; })
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
    window.watchRefreshStrength = function () { return refreshStrength(false); };
    window.manualRefreshTws = window.watchRefreshStrength;      // 标题上的 ↻ 沿用同一条刷新链

    // 30s 总时钟：仅在 9:25~15:00 且页面可见时刷新；K线弹框打开时一并刷新
    function tick() {
        if (!_twsRefreshGate() || document.hidden) return;
        refreshStrength(false);
        watchRefreshTrajectory();
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
        setInterval(tick, REFRESH_MS);
        document.addEventListener('visibilitychange', function () { if (!document.hidden) tick(); });
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
    else setTimeout(boot, 0);
})();
