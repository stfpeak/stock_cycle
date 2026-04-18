/**
 * 股票分析看板 V2 - 主应用逻辑
 */

(function() {
    'use strict';

    // 全局变量
    let currentStockCode = '';
    let currentStockPrefix = '';

    // ================================================
    // JSON报告加载功能
    // ================================================

    /**
     * Escape HTML entities to prevent XSS
     */
    function escapeHtml(text) {
        if (!text) return '';
        var div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /**
     * 加载最新报告数据
     */
    function loadLatestReport() {
        // Check if user selected a specific archive date
        var selectedDate = localStorage.getItem('selectedArchiveDate');
        if (selectedDate) {
            localStorage.removeItem('selectedArchiveDate');
            loadReportData(selectedDate);
            return;
        }

        var xhr = new XMLHttpRequest();
        xhr.open('GET', 'reports/data/', true);
        xhr.onreadystatechange = function() {
            if (xhr.readyState === 4 && xhr.status === 200) {
                var files = parseDirectoryListing(xhr.responseText);
                var latestDate = findLatestDate(files);
                if (latestDate) {
                    loadReportData(latestDate);
                } else {
                    showLoadError('未找到报告数据');
                }
            } else if (xhr.readyState === 4 && xhr.status !== 200) {
                showLoadError('无法加载数据目录');
            }
        };
        xhr.send();
    }

    /**
     * 解析目录列表HTML
     */
    function parseDirectoryListing(html) {
        var files = [];
        var matches = html.matchAll(/<a href="(\d{8}\.json)">/g);
        for (var match of matches) {
            files.push(match[1]);
        }
        return files;
    }

    /**
     * 从文件名列表找到最新日期
     */
    function findLatestDate(files) {
        if (!files || files.length === 0) return null;
        files.sort();
        return files[files.length - 1].replace('.json', '');
    }

    /**
     * 加载指定日期的报告数据
     */
    function loadReportData(date) {
        var jsonPath = 'reports/data/' + date + '.json';
        var xhr = new XMLHttpRequest();
        xhr.open('GET', jsonPath, true);
        xhr.onreadystatechange = function() {
            if (xhr.readyState === 4) {
                if (xhr.status === 200 || xhr.status === 304) {
                    try {
                        var data = JSON.parse(xhr.responseText);
                        renderReport(data);
                    } catch (e) {
                        console.error('JSON解析失败:', e);
                        showLoadError('数据解析失败');
                    }
                } else {
                    showLoadError('数据加载失败: ' + xhr.status);
                }
            }
        };
        xhr.send();
    }

    /**
     * 显示加载错误
     */
    function showLoadError(message) {
        var footer = document.getElementById('footer');
        if (footer) {
            footer.innerHTML = '<p style="color:red;">' + escapeHtml(message) + '</p>';
        }
    }

    /**
     * 根据数据渲染页面
     */
    function renderReport(data) {
        if (!data || !data.date || !data.dates || !data.stats) {
            showLoadError('数据格式错误');
            return;
        }
        // 1. 渲染头部信息
        var dateEl = document.getElementById('report-date');
        if (dateEl) {
            dateEl.innerHTML = data.date.substring(0,4) + '年' + data.date.substring(4,6) + '月' + data.date.substring(6,8) + '日 | 分析时段: ' +
                data.dates[data.dates.length-1].substring(0,4) + '年' + data.dates[data.dates.length-1].substring(4,6) + '月' + data.dates[data.dates.length-1].substring(6,8) + '日 至 ' +
                data.date.substring(0,4) + '年' + data.date.substring(4,6) + '月' + data.date.substring(6,8) + '日';
        }

        // 2. 渲染统计卡片
        var statEl = document.getElementById('stat-concepts');
        if (statEl) statEl.textContent = data.stats.concept_count;
        statEl = document.getElementById('stat-top20');
        if (statEl) statEl.textContent = data.stats.top20_zt_count;
        statEl = document.getElementById('stat-other');
        if (statEl) statEl.textContent = data.stats.other_zt_count;
        statEl = document.getElementById('stat-notzt');
        if (statEl) statEl.textContent = data.stats.not_zt_hot_count;
        statEl = document.getElementById('stat-todayzt');
        if (statEl) statEl.textContent = data.stats.today_zt_count;

        // 3. 渲染归档下拉框
        var archiveSelect = document.getElementById('archive-select');
        if (archiveSelect) {
            archiveSelect.innerHTML = '<option value="">选择查看归档...</option><option value="latest">最新报告</option>';
            (data.archives || []).forEach(function(archiveDate) {
                var displayDate = archiveDate.substring(0,4) + '-' + archiveDate.substring(4,6) + '-' + archiveDate.substring(6,8);
                archiveSelect.innerHTML += '<option value="' + archiveDate + '">' + escapeHtml(displayDate) + '</option>';
            });
        }

        // 4. 渲染连板天梯
        renderLadder(data.ladder, data.dates, data.date);

        // 5. 渲染连板矩阵
        renderMatrix(data.matrix, data.date);

        // 6. 渲染今日涨停看板
        renderTodayBoard(data.today_board);

        // 7. 渲染涨停简图
        renderJianxi(data);

        // 8. 渲染热门概念板块一览
        renderMainThemes(data);
        renderConceptsGrid(data);

        // 9. 渲染TOP20概念详情
        renderConceptDetails(data.top20_concepts);

        // 10. 渲染其他章节
        renderOtherStocks(data.other_stocks);
        renderNotZtStocks(data.not_zt_hot_stocks);
        renderMultiConceptStocks(data.multi_concept_stocks);

        // 更新标题
        document.title = '热门概念板块涨停股分析报告 V2 - ' + data.date.substring(0,4) + '年' + data.date.substring(4,6) + '月' + data.date.substring(6,8) + '日';

        // 隐藏footer加载提示
        var footer = document.getElementById('footer');
        if (footer) footer.style.display = 'none';
    }

    /**
     * 渲染连板天梯
     */
    function renderLadder(ladder, allDates, targetDate) {
        var container = document.getElementById('ladder-container');
        if (!container) return;
        if (!ladder) {
            container.innerHTML = '<div class="jianxi-summary">暂无数据</div>';
            return;
        }

        // 使用所有日期（最多15个交易日）
        var recentDates = (allDates || []).slice(0, 15);
        var html = '';

        recentDates.forEach(function(dateStr) {
            var stocks = ladder[dateStr] || [];
            var shortDate = dateStr.substring(4, 6) + dateStr.substring(6, 8);
            html += '<div class="rhythm-date"><div class="rhythm-header">' + shortDate + '日</div><div class="rhythm-content">';

            if (stocks.length === 0) {
                html += '<div class="jianxi-summary">-</div>';
            } else {
                stocks.forEach(function(stock) {
                    // stock格式: [name, lianban, concepts, rank, code]
                    var name = stock[0];
                    var lb = stock[1];
                    var concepts = stock[2];
                    var code = stock[4];

                    var lbClass = lb >= 3 ? 'lb-3' : (lb === 2 ? 'lb-2' : 'lb-1');
                    var lbTag = lb >= 3 ? '3板+' : (lb === 2 ? '2板' : '首板');
                    // Determine board type for inline tag
                    var boardTag = '';
                    if (code.startsWith('60')) {
                        boardTag = "<span class='board-inline board-zhu'>主</span>";
                    } else if (code.startsWith('00') || code.startsWith('002') || code.startsWith('003')) {
                        boardTag = "<span class='board-inline board-chuang'>创</span>";
                    } else if (code.startsWith('688')) {
                        boardTag = "<span class='board-inline board-ke'>科</span>";
                    }
                    html += '<div class="rhythm-item" data-stock="' + escapeHtml(name) + '">' +
                        '<div class="stock-block ' + lbClass + '" onclick="openKLineModal(\'' + code + '\', \'' + escapeHtml(name) + '\')">' +
                        '<span class="name">' + escapeHtml(name) + '</span>' +
                        '<span class="lb-tag">' + lbTag + ' ' + boardTag + '</span></div></div>';
                });
            }
            html += '</div></div>';
        });

        container.innerHTML = html;

        // 重新初始化股票高亮
        initStockHighlight();
    }

    /**
     * 渲染连板矩阵
     */
    function renderMatrix(matrix, targetDate) {
        var container = document.getElementById('matrix-container');
        var table = document.getElementById('matrix-table');
        if (!container || !table) return;
        if (!matrix) {
            table.innerHTML = '<tr><td>暂无数据</td></tr>';
            return;
        }

        // 获取所有概念和日期
        var concepts = Object.keys(matrix).slice(0, 15); // 限制最多15个概念
        var allDates = [];
        concepts.forEach(function(concept) {
            var dates = Object.keys(matrix[concept] || {});
            dates.forEach(function(d) {
                if (allDates.indexOf(d) === -1) allDates.push(d);
            });
        });
        // 过滤日期：只显示 <= targetDate 的日期
        allDates = allDates.filter(function(d) { return d <= targetDate; });
        allDates.sort().reverse(); // 降序排列
        var recentDates = allDates.slice(0, 6); // 最多6天

        // 生成表头
        var html = '<thead><tr><th class="matrix-th">概念</th>';
        recentDates.forEach(function(dateStr) {
            html += '<th class="matrix-th">' + dateStr.substring(4,6) + '/' + dateStr.substring(6,8) + '</th>';
        });
        html += '</tr></thead><tbody>';

        // 生成数据行
        concepts.forEach(function(concept) {
            html += '<tr><td class="matrix-concept">' + escapeHtml(concept) + '</td>';
            recentDates.forEach(function(dateStr) {
                var stocks = matrix[concept][dateStr] || [];
                if (stocks.length > 0) {
                    var stockHtml = stocks.map(function(s) {
                        return '<span class="matrix-stock" onclick="openKLineModal(\'' + s.code + '\', \'' + escapeHtml(s.name) + '\')">' +
                            escapeHtml(s.name) + '<span class="matrix-lb">' + (s.lianban >= 3 ? '3+' : s.lianban) + '板</span></span>';
                    }).join('');
                    html += '<td class="matrix-cell">' + stockHtml + '</td>';
                } else {
                    html += '<td class="matrix-cell">-</td>';
                }
            });
            html += '</tr>';
        });
        html += '</tbody>';

        table.innerHTML = html;
    }

    /**
     * 渲染今日涨停看板
     */
    function renderTodayBoard(todayBoard) {
        var container = document.getElementById('today-board-container');
        var descEl = document.getElementById('today-board-desc');
        if (!container) return;
        if (!todayBoard) {
            container.innerHTML = '<div class="jianxi-summary">暂无数据</div>';
            return;
        }

        var totalCount = todayBoard.total_count || todayBoard.count || 0;
        if (descEl) {
            descEl.textContent = todayBoard.date ? todayBoard.date.substring(0,4) + '年' + todayBoard.date.substring(4,6) + '月' + todayBoard.date.substring(6,8) + '日 | 共' + totalCount + '只涨停' : '今日涨停概况';
        }

        var conceptGroups = todayBoard.concept_groups || [];
        var html = '';

        conceptGroups.forEach(function(group) {
            var stocks = group.stocks || [];
            if (stocks.length > 0) {
                html += '<div class="today-board-concept">';
                html += '<div class="today-board-header">' + escapeHtml(group.concept_name || group.name || '其他') + ' <span class="today-board-count">' + stocks.length + '只</span></div>';
                html += '<div class="today-board-stocks">';

                stocks.forEach(function(stock) {
                    var lb = stock.lianban || 1;
                    var lbTag = lb >= 3 ? '3+' : (lb === 2 ? '2板' : '首板');
                    var lbClass = lb >= 3 ? 'lb-3' : (lb === 2 ? 'lb-2' : 'lb-1');
                    var stockName = stock.name || stock[0] || '';
                    var stockCode = stock.code || stock[1] || '';
                    html += '<div class="today-stock-item ' + lbClass + '" onclick="openKLineModal(\'' + stockCode + '\', \'' + escapeHtml(stockName) + '\')">' +
                        '<span class="today-stock-name">' + escapeHtml(stockName) + '</span>' +
                        '<span class="today-stock-lb">' + lbTag + '</span></div>';
                });

                html += '</div></div>';
            }
        });

        if (!html) {
            html = '<div class="jianxi-summary">暂无涨停数据</div>';
        }

        container.innerHTML = html;
    }

    /**
     * 渲染涨停简图
     */
    function renderJianxi(data) {
        var container = document.getElementById('jianxi-container');
        var descEl = document.getElementById('jianxi-desc');
        if (!container) return;

        if (data.jianxi_image) {
            var dateDisplay = data.jianxi_date ? data.jianxi_date.substring(4,6) + '-' + data.jianxi_date.substring(6,8) : '';
            if (descEl) {
                descEl.innerHTML = '韭研公社涨停简图 | ' + escapeHtml(dateDisplay) + '日';
            }
            container.innerHTML =
                '<img src="' + data.jianxi_image + '" alt="涨停简图" class="jianxi-image" onerror="this.style.display=\'none\'; this.nextElementSibling.style.display=\'block\';">' +
                '<div class="jianxi-fallback" style="display:none; text-align:center; padding:40px; color:#999;">图片加载失败，请刷新重试</div>';
        } else {
            container.innerHTML = '<div style="text-align:center; padding:40px; color:#999;">暂无简图数据</div>';
        }
    }

    /**
     * 渲染市场主线标签
     */
    function renderMainThemes(data) {
        var container = document.getElementById('main-themes-container');
        if (!container) return;

        var hotConcepts = data.hot_concepts || [];
        if (hotConcepts.length === 0) {
            container.innerHTML = '';
            return;
        }

        // 取前5个热门概念作为主线
        var mainThemes = hotConcepts.slice(0, 5);
        var html = '<div class="main-themes-tags">';
        mainThemes.forEach(function(c) {
            html += '<span class="main-theme-tag">' + escapeHtml(c.name) + '</span>';
        });
        html += '</div>';
        container.innerHTML = html;
    }

    /**
     * 渲染热门概念网格
     */
    function renderConceptsGrid(data) {
        var container = document.getElementById('concepts-grid-container');
        if (!container) return;

        var hotConcepts = data.hot_concepts || [];
        if (hotConcepts.length === 0) {
            container.innerHTML = '';
            return;
        }

        var html = '<div class="concept-grid-items">';
        hotConcepts.forEach(function(c) {
            html += '<div class="concept-grid-item">' +
                '<span class="concept-grid-name">' + escapeHtml(c.name) + '</span>' +
                '<span class="concept-grid-value">热度: ' + Math.round(c.hot_value) + '</span></div>';
        });
        html += '</div>';
        container.innerHTML = html;
    }

    /**
     * 渲染TOP20概念详情
     */
    function renderConceptDetails(top20Concepts) {
        var container = document.getElementById('concept-details-container');
        if (!container) return;

        if (!top20Concepts || top20Concepts.length === 0) {
            container.innerHTML = '<div class="jianxi-summary">暂无数据</div>';
            return;
        }

        var html = '';

        top20Concepts.forEach(function(concept, index) {
            var conceptId = 'concept-' + index;
            var stocks = concept.stocks || [];
            var stats = concept.stats || {};

            html += '<div class="concept-accordion-item">';
            html += '<div class="concept-header" id="concept-header-' + conceptId + '" onclick="toggleConcept(\'' + conceptId + '\')">';
            html += '<span class="expand-icon" id="icon-' + conceptId + '">▼</span>';
            html += '<span class="concept-name">' + escapeHtml(concept.concept_name) + '</span>';
            html += '<span class="concept-stats">今日涨停:' + (stats.today_zt_count || 0) + ' | 15日涨停:' + (stats.days_15_zt_count || 0) + ' | 最强:' + (stats.max_lianban_10d || 0) + '板</span>';
            html += '<span class="concept-hot-value">热度:' + Math.round(concept.hot_value) + '</span>';
            html += '</div>';

            html += '<div class="concept-content" id="concept-content-' + conceptId + '">';

            // 渲染股票列表
            if (stocks.length > 0) {
                html += '<div class="concept-stocks-list">';
                stocks.forEach(function(stock) {
                    var ztDatesStr = stock.zt_dates ? stock.zt_dates.map(function(d) { return d.substring(4,6) + '/' + d.substring(6,8); }).join(', ') : '';
                    html += '<div class="concept-stock-item" onclick="openKLineModal(\'' + stock.code + '\', \'' + escapeHtml(stock.name) + '\')">';
                    html += '<div class="concept-stock-main">';
                    html += '<span class="concept-stock-name">' + escapeHtml(stock.name) + '</span>';
                    html += '<span class="concept-stock-lb">' + (stock.max_lianban >= 3 ? '3+' : stock.max_lianban) + '板</span>';
                    html += '<span class="concept-stock-ztcount">' + stock.zt_count + '次涨停</span>';
                    html += '</div>';
                    html += '<div class="concept-stock-meta">';
                    html += '<span class="concept-stock-concepts">' + escapeHtml((stock.concepts || '').substring(0, 50)) + '</span>';
                    html += '</div>';
                    html += '</div>';
                });
                html += '</div>';
            } else {
                html += '<div class="jianxi-summary">暂无涨停数据</div>';
            }

            // 走势看板
            html += '<div class="concept-trend-board" id="board-' + conceptId + '" style="display:none;">';
            html += '<button id="btn-' + conceptId + '" class="toggle-trend-btn tab-btn" onclick="toggleTrendBoard(\'' + conceptId + '\')" style="background:#38a169;color:#fff;border-radius:6px;padding:6px 12px;margin:10px 0;">📈 查看走势看板</button>';
            html += '<div class="concept-trend-grid" id="grid-' + conceptId + '"></div>';
            html += '<div class="concept-stocks-data" id="concept-stocks-' + conceptId + '" style="display:none;">' + JSON.stringify(stocks) + '</div>';
            html += '</div>';

            html += '</div></div>';
        });

        container.innerHTML = html;
    }

    /**
     * 渲染其他概念涨停股
     */
    function renderOtherStocks(stocks) {
        var container = document.getElementById('other-stocks-container');
        if (!container) return;

        if (!stocks || stocks.length === 0) {
            container.innerHTML = '<div class="jianxi-summary">暂无数据</div>';
            return;
        }

        // 按概念分组
        var grouped = {};
        stocks.forEach(function(stock) {
            var concepts = stock.concepts || [];
            var mainConcept = concepts[0] || '其他';
            if (!grouped[mainConcept]) grouped[mainConcept] = [];
            grouped[mainConcept].push(stock);
        });

        var html = '';
        Object.keys(grouped).forEach(function(concept) {
            var conceptStocks = grouped[concept];
            html += '<div class="other-concept-group">';
            html += '<div class="other-concept-header">' + escapeHtml(concept) + ' <span class="other-concept-count">' + conceptStocks.length + '只</span></div>';
            html += '<div class="other-concept-stocks">';

            conceptStocks.forEach(function(stock) {
                var lbTag = stock.lianban >= 3 ? '3+' : (stock.lianban === 2 ? '2板' : '首板');
                var lbClass = stock.lianban >= 3 ? 'lb-3' : (stock.lianban === 2 ? 'lb-2' : 'lb-1');
                html += '<div class="other-stock-item ' + lbClass + '" onclick="openKLineModal(\'' + stock.code + '\', \'' + escapeHtml(stock.name) + '\')">';
                html += '<span class="other-stock-name">' + escapeHtml(stock.name) + '</span>';
                html += '<span class="other-stock-lb">' + lbTag + '</span></div>';
            });

            html += '</div></div>';
        });

        container.innerHTML = html;
    }

    /**
     * 渲染未涨停热股
     */
    function renderNotZtStocks(stocks) {
        var container = document.getElementById('not-zt-container');
        if (!container) return;

        if (!stocks || stocks.length === 0) {
            container.innerHTML = '<div class="jianxi-summary">暂无数据</div>';
            return;
        }

        var html = '<div class="not-zt-list">';
        stocks.forEach(function(stock) {
            var changeClass = stock.change_pct >= 0 ? 'up' : 'down';
            var changeSign = stock.change_pct >= 0 ? '+' : '';
            html += '<div class="not-zt-item" onclick="openKLineModal(\'' + stock.stock_code + '\', \'' + escapeHtml(stock.short_name) + '\')">';
            html += '<div class="not-zt-main">';
            html += '<span class="not-zt-rank">#' + stock.rank + '</span>';
            html += '<span class="not-zt-name">' + escapeHtml(stock.short_name) + '</span>';
            html += '<span class="not-zt-code">' + stock.stock_code + '</span>';
            html += '<span class="not-zt-change ' + changeClass + '">' + changeSign + stock.change_pct.toFixed(2) + '%</span>';
            html += '</div>';
            html += '<div class="not-zt-meta">';
            html += '<span class="not-zt-hot">热度:' + Math.round(stock.hot_value) + '</span>';
            html += '<span class="not-zt-concepts">' + escapeHtml((stock.concept_tag || '').replace(/;/g, ' | ')) + '</span>';
            html += '</div>';
            html += '</div>';
        });
        html += '</div>';

        container.innerHTML = html;
    }

    /**
     * 渲染多概念股票
     */
    function renderMultiConceptStocks(stocks) {
        var container = document.getElementById('multi-concept-container');
        if (!container) return;

        if (!stocks || stocks.length === 0) {
            container.innerHTML = '<div class="jianxi-summary">暂无数据</div>';
            return;
        }

        var html = '<div class="multi-concept-list">';
        stocks.forEach(function(stock) {
            var concepts = stock.concepts || [];
            html += '<div class="multi-concept-item" onclick="openKLineModal(\'' + stock.code + '\', \'' + escapeHtml(stock.name) + '\')">';
            html += '<div class="multi-concept-main">';
            html += '<span class="multi-concept-name">' + escapeHtml(stock.name) + '</span>';
            html += '<span class="multi-concept-code">' + stock.code + '</span>';
            html += '<span class="multi-concept-lb">' + stock.max_lianban + '板</span>';
            html += '<span class="multi-concept-ztcount">' + stock.zt_count + '次涨停</span>';
            html += '</div>';
            html += '<div class="multi-concept-tags">';
            concepts.slice(0, 6).forEach(function(c) {
                html += '<span class="multi-concept-tag">' + escapeHtml(c) + '</span>';
            });
            if (concepts.length > 6) {
                html += '<span class="multi-concept-tag more">+' + (concepts.length - 6) + '</span>';
            }
            html += '</div>';
            html += '</div>';
        });
        html += '</div>';

        container.innerHTML = html;
    }

    // ================================================
    // K线图功能
    // ================================================

    /**
     * 获取新浪股票代码
     */
    function getSinaCode(code) {
        if (code.startsWith('60') || code.startsWith('68')) return 'sh' + code;
        if (code.startsWith('00') || code.startsWith('30')) return 'sz' + code;
        return 'sh' + code;
    }

    /**
     * 打开K线弹窗
     */
    function openKLineModal(code, name, event) {
        currentStockCode = code;
        currentStockPrefix = getSinaCode(code);
        document.getElementById('kline-title').innerText = name + ' (' + code + ')';
        document.getElementById('kline-modal').style.display = 'flex';
        switchKLineTab('min');
        if (event) event.stopPropagation();
    }

    /**
     * 关闭K线弹窗
     */
    function closeKLineModal() {
        document.getElementById('kline-modal').style.display = 'none';
        document.getElementById('kline-img').src = '';
    }

    /**
     * 切换K线标签页
     */
    function switchKLineTab(type, elm) {
        // 更新标签状态
        document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
        if (elm) {
            elm.classList.add('active');
        } else {
            const tabs = document.querySelectorAll('.tab-btn');
            if (type === 'min') tabs[0] && tabs[0].classList.add('active');
            if (type === 'daily') tabs[1] && tabs[1].classList.add('active');
            if (type === 'weekly') tabs[2] && tabs[2].classList.add('active');
            if (type === 'monthly') tabs[3] && tabs[3].classList.add('active');
        }

        // 优化 Sina CDN 缓存: 每10秒更新一次
        let t = Math.floor(new Date().getTime() / 10000);
        let url = "http://image.sinajs.cn/newchart/" + type + "/n/" + currentStockPrefix + ".png?" + t;

        // 显示加载状态
        let img = document.getElementById('kline-img');
        if (img) {
            img.src = '';
            img.alt = 'K线图急速拉取中...';
            img.style.opacity = '0.5';
            img.onload = function() { img.style.opacity = '1'; };
            img.onerror = function() { img.alt = '获取失败，请重试'; };
            img.src = url;
        }
    }

    // ================================================
    // 侧边栏功能
    // ================================================

    /**
     * 切换侧边栏折叠状态
     */
    function toggleSidebar() {
        const sidebar = document.querySelector('.sidebar');
        const toggle = document.querySelector('.sidebar-toggle');
        const mainContent = document.querySelector('.main-content');

        sidebar.classList.toggle('collapsed');
        toggle.classList.toggle('collapsed');
        mainContent.classList.toggle('expanded');

        // 记住状态
        const isCollapsed = sidebar.classList.contains('collapsed');
        localStorage.setItem('sidebarCollapsed', isCollapsed);
    }

    /**
     * 初始化侧边栏状态
     */
    function initSidebar() {
        // 始终保持侧边栏展开状态，忽略保存的收起状态
        const sidebar = document.querySelector('.sidebar');
        const toggle = document.querySelector('.sidebar-toggle');
        const mainContent = document.querySelector('.main-content');
        sidebar && sidebar.classList.remove('collapsed');
        toggle && toggle.classList.remove('collapsed');
        mainContent && mainContent.classList.remove('expanded');
        localStorage.setItem('sidebarCollapsed', 'false');
    }

    // ================================================
    // Section 导航功能
    // ================================================

    /**
     * Tab 到 Section 的映射
     * 每个 Tab 对应一个完整的 page-section
     */
    const TAB_SECTIONS = {
        'trend': ['trend'],
        'concept-detail': ['concept-detail'],
        'sentiment': ['sentiment']
    };

    /**
     * 显示指定区块
     */
    function showSection(sectionId) {
        // 获取该 tab 对应的 section
        const sectionsToShow = TAB_SECTIONS[sectionId] || [sectionId];

        // 隐藏所有 section
        document.querySelectorAll('.page-section').forEach(section => {
            section.classList.remove('active');
        });

        // 显示目标 section
        sectionsToShow.forEach(secId => {
            const target = document.getElementById('section-' + secId);
            if (target) {
                target.classList.add('active');
            }
        });

        // 更新导航栏 active 状态
        document.querySelectorAll('.nav-link').forEach(link => {
            link.classList.remove('active');
            if (link.getAttribute('data-section') === sectionId) {
                link.classList.add('active');
            }
        });

        // 记录当前 section 到 localStorage
        localStorage.setItem('currentSection', sectionId);

        // 滚动到顶部
        window.scrollTo(0, 0);
    }

    /**
     * 切换报告（日期选择）
     */
    function switchReport(date) {
        if (!date) return;
        if (date === 'latest') {
            loadLatestReport();
            return;
        }
        // 加载指定日期
        loadReportData(date);
    }

    // ================================================
    // 概念折叠功能
    // ================================================

    /**
     * 切换概念详情展开/收起
     */
    function toggleConcept(conceptId) {
        var content = document.getElementById('concept-content-' + conceptId);
        var icon = document.getElementById('icon-' + conceptId);
        if (content && icon) {
            if (content.classList.contains('show')) {
                content.classList.remove('show');
                icon.classList.remove('expanded');
                icon.textContent = '▼';
            } else {
                content.classList.add('show');
                icon.classList.add('expanded');
                icon.textContent = '▲';
            }
        }
    }

    // 全局状态：记录当前是否已展开所有
    var allConceptsExpanded = false;

    /**
     * 一键展开/收起所有概念板块和走势看板
     */
    function toggleAllConcepts() {
        allConceptsExpanded = !allConceptsExpanded;

        if (allConceptsExpanded) {
            // 展开所有
            document.querySelectorAll('.concept-content').forEach(function(content) {
                content.classList.add('show');
            });
            document.querySelectorAll('.expand-icon').forEach(function(icon) {
                icon.classList.add('expanded');
                icon.textContent = '▲';
            });
            // 收起所有走势看板（不加载K线图）
            document.querySelectorAll('.concept-trend-board').forEach(function(board) {
                board.style.display = 'none';
            });
            document.querySelectorAll('[id^="btn-"]').forEach(function(btn) {
                if (btn && btn.textContent && btn.textContent.includes('收起走势看板')) {
                    btn.textContent = '📈 查看走势看板';
                }
            });
            // 更新按钮状态
            document.querySelectorAll('.toggle-all-btn').forEach(function(btn) {
                btn.textContent = '📕 一键收起全部';
                btn.style.background = '#718096';
            });
        } else {
            // 收起所有
            document.querySelectorAll('.concept-content').forEach(function(content) {
                content.classList.remove('show');
            });
            document.querySelectorAll('.expand-icon').forEach(function(icon) {
                icon.classList.remove('expanded');
                icon.textContent = '▼';
            });
            document.querySelectorAll('.toggle-all-btn').forEach(function(btn) {
                btn.textContent = '📖 一键展开全部';
                btn.style.background = '#4299e1';
            });
        }
    }

    /**
     * 渲染走势看板股票卡片（带缓存）
     */
    var trendBoardRendered = {};  // 缓存已渲染的概念ID

    // 全局状态：记录当前是否已展开所有走势看板
    var allTrendBoardsExpanded = false;

    /**
     * 一键展开/收起所有走势看板
     */
    function toggleAllTrendBoards() {
        allTrendBoardsExpanded = !allTrendBoardsExpanded;

        if (allTrendBoardsExpanded) {
            // 先展开所有板块内容
            document.querySelectorAll('.concept-content').forEach(function(content) {
                content.classList.add('show');
            });
            document.querySelectorAll('.expand-icon').forEach(function(icon) {
                icon.classList.add('expanded');
                icon.textContent = '▲';
            });
            // 展开所有走势看板并渲染卡片
            document.querySelectorAll('.concept-trend-board').forEach(function(board) {
                board.style.display = 'block';
            });
            // 渲染所有走势看板的K线卡片
            document.querySelectorAll('.concept-trend-board').forEach(function(board) {
                var conceptId = board.id.replace('board-', '');
                renderTrendBoardCards(conceptId);
            });
            // 更新所有"查看走势看板"按钮为"收起走势看板"
            document.querySelectorAll('[id^="btn-"]').forEach(function(btn) {
                if (btn && btn.textContent && btn.textContent.includes('查看走势看板')) {
                    btn.textContent = '📉 收起走势看板';
                }
            });
            // 更新按钮状态
            document.querySelectorAll('.toggle-all-btn').forEach(function(btn) {
                btn.textContent = '📕 一键收起全部';
                btn.style.background = '#718096';
            });
            document.querySelectorAll('.toggle-trend-btn').forEach(function(btn) {
                btn.textContent = '📉 一键收起走势看板';
                btn.style.background = '#718096';
            });
        } else {
            // 收起所有走势看板
            document.querySelectorAll('.concept-trend-board').forEach(function(board) {
                board.style.display = 'none';
            });
            // 更新所有"收起走势看板"按钮为"查看走势看板"
            document.querySelectorAll('[id^="btn-"]').forEach(function(btn) {
                if (btn && btn.textContent && btn.textContent.includes('收起走势看板')) {
                    btn.textContent = '📈 查看走势看板';
                }
            });
            // 更新按钮状态
            document.querySelectorAll('.toggle-trend-btn').forEach(function(btn) {
                btn.textContent = '📈 一键展开走势看板';
                btn.style.background = '#38a169';
            });
        }
    }

    function renderTrendBoardCards(conceptId) {
        // 如果已经渲染过，直接返回（使用缓存）
        if (trendBoardRendered[conceptId]) {
            return true;  // 返回true表示已缓存
        }

        var dataEl = document.getElementById('concept-stocks-' + conceptId);
        if (!dataEl) return false;
        var grid = document.getElementById('grid-' + conceptId);
        if (!grid) return false;

        grid.innerHTML = '';

        var stocks;
        try {
            stocks = JSON.parse(dataEl.textContent);
        } catch (e) {
            console.error('Failed to parse concept stocks data:', e);
            return false;
        }

        if (!stocks || stocks.length === 0) {
            grid.innerHTML = '<div class="jianxi-summary">暂无涨停数据</div>';
            trendBoardRendered[conceptId] = true;  // 标记为已渲染（即使为空）
            return true;
        }

        grid.innerHTML = stocks.map(function(s) {
            var prefix = s.code.startsWith('6') ? 'sh' : 'sz';
            var ts = Date.now();
            var ztDatesStr = (s.zt_dates || []).map(function(d) { return d.substring(4, 6) + '/' + d.substring(6, 8); }).join(', ');
            return '<div class="trend-stock-card">' +
                '<img class="trend-kline" ' +
                'src="http://image.sinajs.cn/newchart/daily/n/' + prefix + s.code + '.png?_t=' + ts + '" ' +
                'onclick="openKLineModal(\'' + s.code + '\', \'' + escapeHtml(s.name) + '\')" ' +
                'alt="' + escapeHtml(s.name) + '" ' +
                'onerror="this.src=\'data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 200 120%22><rect fill=%22%23f0f0f0%22 width=%22200%22 height=%22120%22/><text x=%2250%22 y=%2260%22 fill=%22%23999%22 font-size=%2212%22>加载失败</text></svg>\'"> ' +
                '<div class="trend-stock-info">' +
                '<div class="stock-name">' + escapeHtml(s.name) + ' <span style="color:#666;font-weight:normal;">(' + s.code + ')</span></div>' +
                '<div class="zt-info">' +
                '<span class="zt-count">' + s.zt_count + '次涨停</span>' +
                '<div class="zt-dates">' + ztDatesStr + '</div>' +
                '</div></div></div>';
        }).join('');

        // 标记为已渲染
        trendBoardRendered[conceptId] = true;
        return true;
    }

    // ================================================
    // 股票高亮效果
    // ================================================

    /**
     * 初始化股票名称高亮效果
     */
    function initStockHighlight() {
        const rhythmItems = document.querySelectorAll('.rhythm-item');

        rhythmItems.forEach(item => {
            item.addEventListener('mouseenter', function() {
                const stockName = this.getAttribute('data-stock');
                if (!stockName) return;

                // 高亮所有相同名称的股票
                rhythmItems.forEach(other => {
                    if (other.getAttribute('data-stock') === stockName) {
                        const block = other.querySelector('.stock-block');
                        if (block) block.classList.add('highlighted');
                    }
                });
            });

            item.addEventListener('mouseleave', function() {
                // 移除所有高亮
                rhythmItems.forEach(other => {
                    const block = other.querySelector('.stock-block');
                    if (block) block.classList.remove('highlighted');
                });
            });
        });
    }

    // ================================================
    // 归档切换功能
    // ================================================

    /**
     * 加载归档文件
     */
    function loadArchive(filename) {
        if (!filename) return;
        if (filename === 'report_latest.html') {
            window.location.reload();
            return;
        }
        // If it's a date (8 digits), load the static HTML file from archive
        if (/^\d{8}$/.test(filename)) {
            window.location.href = 'reports/archive/' + filename + '/report_' + filename + '.html';
            return;
        }
        // For other filenames, try to load via AJAX
        switchReport(filename);
    }

    // ================================================
    // 键盘快捷键
    // ================================================

    /**
     * 初始化键盘快捷键
     */
    function initKeyboardNav() {
        document.addEventListener('keydown', function(e) {
            const sections = ['overview', 'ladder', 'matrix', 'today', 'concepts',
                              'details', 'other', 'notzt', 'multi'];
            const currentSection = localStorage.getItem('currentSection') || 'overview';
            const currentIndex = sections.indexOf(currentSection);

            // 避免在输入框中触发
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;

            if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
                e.preventDefault();
                const nextIndex = Math.min(currentIndex + 1, sections.length - 1);
                showSection(sections[nextIndex]);
            } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
                e.preventDefault();
                const prevIndex = Math.max(currentIndex - 1, 0);
                showSection(sections[prevIndex]);
            } else if (e.key === 'Escape') {
                showSection('overview');
            } else if (e.key === 'b' || e.key === 'B') {
                // 切换侧边栏
                toggleSidebar();
            }
        });
    }

    // ================================================
    // 初始化
    // ================================================

    document.addEventListener('DOMContentLoaded', function() {
        // 初始化侧边栏
        initSidebar();

        // 加载侧边栏归档列表
        if (document.getElementById('sidebar-content')) {
            // 从页面提取当前日期（取分析时段的结束日期）
            var reportDateEl = document.getElementById('report-date') || document.querySelector('.header-subtitle');
            if (reportDateEl) {
                var matches = reportDateEl.textContent.match(/(\d{4})(\d{2})(\d{2})/g);
                if (matches && matches.length > 0) {
                    // 使用最后一个匹配（分析时段结束日期）
                    var lastMatch = matches[matches.length - 1];
                    var match = lastMatch.match(/(\d{4})(\d{2})(\d{2})/);
                    if (match) {
                        currentReportDate = match[1] + match[2] + match[3];
                    }
                }
            }
            loadSidebarArchives();
        }

        // 从 localStorage 恢复上次查看的 section
        const savedSection = localStorage.getItem('currentSection') || 'trend';
        showSection(savedSection);

        // 绑定导航栏点击事件（使用事件委托）
        var sidebarEl = document.querySelector('.sidebar');
        if (sidebarEl) {
            sidebarEl.addEventListener('click', function(e) {
                const navLink = e.target.closest('.nav-link');
                if (navLink) {
                    e.preventDefault();
                    const sectionId = navLink.getAttribute('data-section');
                    if (sectionId) {
                        showSection(sectionId);
                    }
                }
            });
        }

        // 绑定侧边栏折叠按钮
        const toggleBtn = document.querySelector('.sidebar-toggle');
        if (toggleBtn) {
            toggleBtn.addEventListener('click', toggleSidebar);
        }

        // 全局事件委托：确保一键展开按钮始终可用
        document.addEventListener('click', function(e) {
            var target = e.target.closest('button');
            if (target) {
                if (target.classList.contains('toggle-all-btn') || target.dataset.action === 'toggle-all') {
                    e.preventDefault();
                    toggleAllConcepts();
                } else if (target.classList.contains('toggle-trend-btn') || target.dataset.action === 'toggle-trend') {
                    e.preventDefault();
                    toggleAllTrendBoards();
                }
            }
        });

        // 初始化股票高亮
        initStockHighlight();

        // 初始化键盘导航
        initKeyboardNav();

        // K线弹窗关闭
        const modalOverlay = document.getElementById('kline-modal');
        if (modalOverlay) {
            modalOverlay.addEventListener('click', function(e) {
                if (e.target === modalOverlay) {
                    closeKLineModal();
                }
            });
        }

        // ESC 关闭弹窗
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') {
                closeKLineModal();
            }
        });

        // 初始化涨停简图
        initJianxi();
    });

    // ================================================
    // 涨停简图功能
    // ================================================

    // API基础URL
    const JIANXI_API = 'http://localhost:5001';

    /**
     * 初始化涨停简图 - 获取日期列表并加载最新图片
     */
    async function initJianxi() {
        try {
            // 获取可用日期列表
            const response = await fetch(`${JIANXI_API}/api/jianxi/list`);
            const data = await response.json();

            if (data.success && data.files.length > 0) {
                const dateSelect = document.getElementById('jianxi-date');
                if (dateSelect) {
                    // 清空现有选项
                    dateSelect.innerHTML = '';

                    // 按日期降序排列
                    data.files.sort((a, b) => b.date.localeCompare(a.date));

                    // 添加选项
                    data.files.forEach((file, index) => {
                        const option = document.createElement('option');
                        // date格式: 20260410 -> 2026-04-10 显示为 04月10日
                        const formatted = file.date.substring(4, 6) + '月' + file.date.substring(6, 8) + '日';
                        option.value = file.date;
                        option.textContent = formatted;
                        if (index === 0) option.selected = true;
                        dateSelect.appendChild(option);
                    });

                    // 日期切换时自动刷新图片
                    dateSelect.addEventListener('change', refreshJianxi);
                }
            }
        } catch (e) {
            console.error('获取涨停简图列表失败:', e);
        }

        // 延迟加载图片
        setTimeout(refreshJianxi, 500);
    }

    /**
     * 刷新涨停简图
     */
    function refreshJianxi() {
        const dateSelect = document.getElementById('jianxi-date');
        const img = document.getElementById('jianxi-image');
        const loading = document.getElementById('jianxi-loading');
        // date format: 20260410
        const date = dateSelect ? dateSelect.value : '';

        if (!img) return;

        // 显示加载状态
        if (loading) loading.style.display = 'flex';
        img.style.opacity = '0.5';

        // 清除旧结果
        const result = document.getElementById('jianxi-result');
        if (result) result.style.display = 'none';

        // 使用本地API获取图片（带时间戳防止缓存）
        const imageUrl = `${JIANXI_API}/api/jianxi/image/${date}?t=` + new Date().getTime();
        img.src = imageUrl;
    }

    /**
     * 更新涨停简图数据
     */
    async function updateJianxiData() {
        const status = document.getElementById('jianxi-update-status');
        const btn = document.getElementById('jianxi-update-btn');

        if (btn) {
            btn.disabled = true;
            btn.textContent = '📥 更新中...';
        }

        if (status) {
            status.style.display = 'block';
            status.innerHTML = '<div class="loading-spinner"></div> 正在检查更新...';
        }

        try {
            const response = await fetch('http://localhost:5001/api/jianxi/update', {
                method: 'POST',
                signal: AbortSignal.timeout(60000)
            });

            const result = await response.json();

            if (status) {
                if (result.success) {
                    status.innerHTML = `<span style="color: green;">✅ ${result.message}</span>`;
                    refreshJianxi();
                } else {
                    status.innerHTML = `<span style="color: red;">❌ ${result.error}</span>`;
                }
            }
        } catch (error) {
            console.error('更新失败:', error);
            if (status) {
                status.innerHTML = '<span style="color: red;">❌ 更新失败</span>';
            }
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.textContent = '📥 更新数据';
            }
            setTimeout(() => {
                if (status) status.style.display = 'none';
            }, 3000);
        }
    }

    /**
     * 涨停简图加载完成
     */
    function onJianxiLoad() {
        const loading = document.getElementById('jianxi-loading');
        const img = document.getElementById('jianxi-image');
        if (loading) loading.style.display = 'none';
        if (img) img.style.opacity = '1';
    }

    /**
     * 涨停简图加载失败
     */
    function onJianxiError() {
        const loading = document.getElementById('jianxi-loading');
        const img = document.getElementById('jianxi-image');
        if (loading) {
            loading.innerHTML = '<span style="color:#e53e3e;">图片加载失败，请点击"刷新图片"重试</span>';
        }
        if (img) img.style.opacity = '1';
    }

    /**
     * AI分析涨停简图（使用模拟数据演示）
     */
    async function analyzeJianxi() {
        const img = document.getElementById('jianxi-image');
        const resultDiv = document.getElementById('jianxi-result');
        const treeDiv = document.getElementById('jianxi-tree');
        const summaryDiv = document.getElementById('jianxi-summary');
        const btn = document.getElementById('jianxi-analyze-btn');

        if (!img || !img.src) {
            alert('请先加载涨停简图');
            return;
        }

        // 禁用按钮，显示加载状态
        if (btn) {
            btn.disabled = true;
            btn.textContent = '🤖 AI分析中...';
        }

        try {
            // 显示加载动画
            if (treeDiv) {
                treeDiv.innerHTML = '<div class="loading-spinner"></div><p style="text-align:center;color:var(--gray-500);">正在分析涨停简图...</p>';
            }
            if (resultDiv) resultDiv.style.display = 'block';

            // 模拟 AI 分析延迟
            await new Promise(resolve => setTimeout(resolve, 1500));

            // 使用演示数据
            const data = getMockJianxiData();
            displayJianxiResult(data);

        } catch (error) {
            console.error('分析失败:', error);
            if (treeDiv) {
                treeDiv.innerHTML = '<p style="color:#e53e3e;">分析失败: ' + escapeHtml(error.message) + '</p>';
            }
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.textContent = '🤖 AI分析涨停简图';
            }
        }
    }

    /**
     * 获取模拟数据（用于演示）
     */
    function getMockJianxiData() {
        return {
            sectors: [
                {
                    name: "共封装光学(CPO)",
                    hot_value: 37322,
                    today_zt: 5,
                    stocks_15d: 45,
                    max_board: "2板",
                    boards: 5,
                    stocks: [
                        { code: "600355", name: "青山纸业", board: "首板" },
                        { code: "600105", name: "永鼎股份", board: "首板" },
                        { code: "301368", name: "德明利", board: "首板" },
                        { code: "300502", name: "英唐智控", board: "首板" },
                        { code: "603220", name: "沃格光电", board: "2板" }
                    ]
                },
                {
                    name: "量子科技",
                    hot_value: 28910,
                    today_zt: 2,
                    stocks_15d: 15,
                    max_board: "2板",
                    boards: 3,
                    stocks: [
                        { code: "000555", name: "神州信息", board: "首板" },
                        { code: "600764", name: "中国海防", board: "首板" }
                    ]
                },
                {
                    name: "AI语料",
                    hot_value: 24560,
                    today_zt: 2,
                    stocks_15d: 15,
                    max_board: "3板",
                    boards: 2,
                    stocks: [
                        { code: "300229", name: "拓尔思", board: "首板" },
                        { code: "603918", name: "金桥信息", board: "3板" }
                    ]
                },
                {
                    name: "光通信",
                    hot_value: 19880,
                    today_zt: 3,
                    stocks_15d: 20,
                    max_board: "2板",
                    boards: 4,
                    stocks: [
                        { code: "688668", name: "鼎通科技", board: "首板" },
                        { code: "300308", name: "中际旭创", board: "首板" },
                        { code: "002229", name: "博创科技", board: "2板" }
                    ]
                },
                {
                    name: "商业航天",
                    hot_value: 15670,
                    today_zt: 2,
                    stocks_15d: 12,
                    max_board: "2板",
                    boards: 2,
                    stocks: [
                        { code: "002025", name: "航天电器", board: "首板" },
                        { code: "600879", name: "航天电子", board: "首板" }
                    ]
                },
                {
                    name: "DeepSeek",
                    hot_value: 17830,
                    today_zt: 3,
                    stocks_15d: 21,
                    max_board: "3板",
                    boards: 4,
                    stocks: [
                        { code: "300248", name: "新开普", board: "首板" },
                        { code: "603869", name: "新智认知", board: "首板" },
                        { code: "688590", name: "新致软件", board: "首板" },
                        { code: "300542", name: "新晨科技", board: "3板" }
                    ]
                },
                {
                    name: "智谱AI",
                    hot_value: 15430,
                    today_zt: 9,
                    stocks_15d: 38,
                    max_board: "5板+",
                    boards: 6,
                    stocks: [
                        { code: "301166", name: "软通动力", board: "首板" },
                        { code: "300248", name: "新开普", board: "首板" },
                        { code: "002376", name: "新北洋", board: "首板" },
                        { code: "603869", name: "新智认知", board: "首板" },
                        { code: "600785", name: "新华百货", board: "首板" },
                        { code: "300468", name: "新光互联", board: "首板" },
                        { code: "301076", name: "新瀚新材", board: "首板" },
                        { code: "002873", name: "新天药业", board: "首板" },
                        { code: "300013", name: "新宁物流", board: "首板" },
                        { code: "688590", name: "新致软件", board: "首板" },
                        { code: "300542", name: "新晨科技", board: "3板" },
                        { code: "688023", name: "安恒信息", board: "5板+" }
                    ]
                },
                {
                    name: "AI语料(续)",
                    hot_value: 9860,
                    today_zt: 4,
                    stocks_15d: 27,
                    max_board: "3板",
                    boards: 4,
                    stocks: [
                        { code: "300129", name: "新天科技", board: "首板" },
                        { code: "300766", name: "每日互动", board: "首板" },
                        { code: "603888", name: "新华网", board: "首板" },
                        { code: "300468", name: "新光互联", board: "首板" },
                        { code: "300542", name: "新晨科技", board: "3板" }
                    ]
                }
            ],
            summary: "市场主线为AI算力相关概念（CPO、量子科技、光通信），连板股表现强势，市场情绪较好。涨停股主要集中在科技成长方向。"
        };
    }

    /**
     * 获取图片Base64（跨域需要后端代理）
     */
    function getImageBase64(url) {
        return new Promise((resolve, reject) => {
            const img = new Image();
            img.crossOrigin = 'anonymous';
            img.onload = function() {
                try {
                    const canvas = document.createElement('canvas');
                    canvas.width = img.width;
                    canvas.height = img.height;
                    const ctx = canvas.getContext('2d');
                    ctx.drawImage(img, 0, 0);
                    resolve(canvas.toDataURL('image/png').split(',')[1]);
                } catch (e) {
                    reject(new Error('无法获取图片数据'));
                }
            };
            img.onerror = function() {
                reject(new Error('图片加载失败'));
            };
            img.src = url;
        });
    }

    /**
     * 显示分析结果
     */
    function displayJianxiResult(data) {
        const treeDiv = document.getElementById('jianxi-tree');
        const summaryDiv = document.getElementById('jianxi-summary');
        const resultDiv = document.getElementById('jianxi-result');

        if (!treeDiv || !data) return;

        let html = '';

        // 遍历每个板块
        for (const sector of (data.sectors || [])) {
            html += `<div class="sector">
                <div class="sector-name">
                    ${sector.name}
                    <span class="board-tag">${sector.boards || '1板'}</span>
                </div>
                <div class="stock-list">`;

            for (const stock of (sector.stocks || [])) {
                html += `<div class="stock-item">
                    <span class="stock-name">${stock.name}</span>
                    <span class="stock-code">${stock.code}</span>`;
                if (stock.keyword) {
                    html += `<span class="stock-keyword">${stock.keyword}</span>`;
                }
                html += `</div>`;
            }

            html += `</div></div>`;
        }

        treeDiv.innerHTML = html;

        if (summaryDiv && data.summary) {
            summaryDiv.innerHTML = `<strong>📝 市场概述：</strong>${data.summary}`;
        }

        if (resultDiv) resultDiv.style.display = 'block';
    }

    /**
     * 获取全部异动解析列表
     * 通过调用后端API获取数据
     */
    async function fetchActionList() {
        const status = document.getElementById('action-list-status');
        const content = document.getElementById('action-list-content');
        const btn = document.getElementById('action-fetch-btn');
        const dateSelect = document.getElementById('jianxi-date');

        if (btn) {
            btn.disabled = true;
            btn.textContent = '🔄 获取中...';
        }

        if (status) {
            status.style.display = 'block';
            status.innerHTML = '<div class="loading-spinner"></div> 正在获取异动数据...';
        }

        if (content) {
            content.innerHTML = '<div class="loading-spinner"></div><p style="text-align:center;color:var(--gray-500);">正在从服务器获取数据...</p>';
        }

        // 获取当前选中的日期
        const dateValue = dateSelect ? dateSelect.value : '';
        const dateFormatted = dateValue ? dateValue.substring(0, 4) + '-' + dateValue.substring(4, 6) + '-' + dateValue.substring(6, 8) : '2026-04-10';

        try {
            const response = await fetch(`http://localhost:5001/api/action/list?date=${dateFormatted}`, {
                method: 'GET',
                signal: AbortSignal.timeout(30000)
            });

            const result = await response.json();

            if (result.success && ((result.stocks && result.stocks.length > 0) || (result.sectors && result.sectors.length > 0))) {
                displayActionList(result);
                if (status) {
                    const count = result.count || (result.sectors ? result.sectors.reduce((sum, s) => sum + (s.stocks?.length || s.count || 0), 0) : 0);
                    status.innerHTML = `<span style="color: green;">✅ 获取成功，共 ${count} 条异动数据</span>`;
                }
            } else {
                const errorMsg = result.error || '获取数据失败';
                if (content) {
                    content.innerHTML = `<div style="text-align:center;padding:40px;color:var(--gray-500);">
                        <p>⚠️ ${errorMsg}</p>
                        <p style="font-size:0.9em;margin-top:10px;">请确保：</p>
                        <p style="font-size:0.85em;">1. jianxi_server.py 已启动</p>
                        <p style="font-size:0.85em;">2. 数据已通过Chrome DevTools提取并保存</p>
                        <p style="font-size:0.85em;">提示：使用 Chrome DevTools MCP 命令行工具提取数据</p>
                    </div>`;
                }
                if (status) {
                    status.innerHTML = `<span style="color: orange;">⚠️ ${errorMsg}</span>`;
                }
            }
        } catch (e) {
            console.error('获取异动数据失败:', e);
            if (content) {
                content.innerHTML = `<div style="text-align:center;padding:40px;color:var(--gray-500);">
                    <p>⚠️ 网络错误或服务未启动</p>
                    <p style="font-size:0.9em;margin-top:10px;">请运行: python jianxi_server.py</p>
                </div>`;
            }
            if (status) {
                status.innerHTML = `<span style="color: red;">❌ 请求失败: ${e.message}</span>`;
            }
        }

        if (btn) {
            btn.disabled = false;
            btn.textContent = '🌐 从韭研公社获取';
        }
    }

    /**
     * 显示异动列表 - 支持板块-题材层级结构
     */
    function displayActionList(data) {
        const content = document.getElementById('action-list-content');
        if (!content) return;

        // 判断是旧格式(stocks数组)还是新格式(sectors数组)
        const stocks = Array.isArray(data) ? data : (data.stocks || []);
        const sectors = data.sectors || [];

        let html = '';

        if (sectors.length > 0) {
            // 新格式：板块-题材结构
            for (const sector of sectors) {
                const theme = sector.theme || '';

                html += `<div class="action-sector-card">
                    <div class="action-sector-header" onclick="this.parentElement.classList.toggle('expanded')">
                        <div class="action-sector-info">
                            <span class="action-sector-name">${sector.name}</span>
                            <span class="action-sector-count">${sector.count}只</span>
                        </div>
                        <div class="action-sector-theme">${theme ? '📌 ' + theme.substring(0, 60) + (theme.length > 60 ? '...' : '') : ''}</div>
                    </div>
                </div>`;
            }
        } else {
            // 旧格式：平铺股票列表
            for (const stock of stocks) {
                const boardTag = stock.board ? `<span class="action-stock-board">${stock.board}</span>` : '';
                const price = stock.price ? (stock.price / 100).toFixed(2) : '-';
                const reason = stock.reason || '';
                const expound = stock.expound || '';

                html += `<div class="action-stock-card">
                    <div class="action-stock-header" onclick="this.parentElement.classList.toggle('expanded')">
                        <div class="action-stock-info">
                            <span class="action-stock-name">${stock.name || '未知'}</span>
                            <span class="action-stock-code">${stock.code || ''}</span>
                            ${boardTag}
                        </div>
                        <div class="action-stock-meta">
                            <span>💰 ${price}</span>
                            <span>🕐 ${stock.time || '-'}</span>
                        </div>
                    </div>
                    <div class="action-stock-expound" style="display:none;">
                        ${reason ? `<div class="reason-tag">${reason}</div>` : ''}
                        ${expound}
                    </div>
                </div>`;
            }
        }

        content.innerHTML = html;
    }

    /**
     * 获取产业库列表
     */
    async function fetchIndustryList() {
        const content = document.getElementById('industry-list-content');
        const status = document.getElementById('industry-list-status');

        if (status) {
            status.style.display = 'block';
            status.innerHTML = '<div class="loading-spinner"></div> 正在获取产业库数据...';
        }
        if (content) {
            content.innerHTML = '<div class="loading-spinner"></div>';
        }

        try {
            const response = await fetch('http://localhost:5001/api/industry/list');
            const result = await response.json();

            if (result.success && result.data) {
                displayIndustryList(result.data);
                if (status) {
                    status.innerHTML = `<span style="color: green;">✅ 获取成功，共 ${result.data.length} 个产业</span>`;
                }
            } else {
                if (content) {
                    content.innerHTML = `<div style="text-align:center;padding:40px;color:var(--gray-500);">
                        <p>⚠️ ${result.error || '暂无数据'}</p>
                        <p style="font-size:0.9em;margin-top:10px;">请点击"更新数据"按钮获取最新数据</p>
                    </div>`;
                }
            }
        } catch (e) {
            if (content) {
                content.innerHTML = `<div style="text-align:center;padding:40px;color:var(--gray-500);">
                    <p>⚠️ 网络错误</p>
                    <p style="font-size:0.9em;margin-top:10px;">请确保 jianxi_server.py 已启动</p>
                </div>`;
            }
        }
    }

    /**
     * 显示产业库列表
     */
    function displayIndustryList(industries) {
        const content = document.getElementById('industry-list-content');
        if (!content) return;

        if (!industries || industries.length === 0) {
            content.innerHTML = '<p class="action-list-hint">暂无数据，请点击"获取数据"按钮</p>';
            return;
        }

        let html = '<div class="industry-list">';
        for (const item of industries) {
            const title = item.title || '';
            const keyword = item.keyword || '';
            const link = `https://www.jiuyangongshe.com/industryChain/${item.industry_id}`;

            // 提取相关股票关键词
            const stocks = keyword.split(/\s+/).filter(s => s.length > 1 && s.length < 20).slice(0, 15);

            html += `<div class="industry-item">
                <div class="industry-header">
                    <a href="${link}" target="_blank" class="industry-title">${title}</a>
                </div>
                <div class="industry-keywords">`;
            for (let i = 0; i < stocks.length; i += 5) {
                html += `<span class="keyword-group">${stocks.slice(i, i + 5).join(' | ')}</span>`;
            }
            html += `</div></div>`;
        }
        html += '</div>';

        content.innerHTML = html;
    }

    /**
     * 获取时间轴列表
     */
    async function fetchTimelineList() {
        const content = document.getElementById('timeline-list-content');
        const status = document.getElementById('timeline-list-status');

        if (status) {
            status.style.display = 'block';
            status.innerHTML = '<div class="loading-spinner"></div> 正在获取时间轴数据...';
        }
        if (content) {
            content.innerHTML = '<div class="loading-spinner"></div>';
        }

        try {
            const response = await fetch('http://localhost:5001/api/timeline/list');
            const result = await response.json();

            if (result.success && result.data) {
                displayTimelineList(result.data);
                if (status) {
                    status.innerHTML = `<span style="color: green;">✅ 获取成功，共 ${result.data.length} 天</span>`;
                }
            } else {
                if (content) {
                    content.innerHTML = `<div style="text-align:center;padding:40px;color:var(--gray-500);">
                        <p>⚠️ ${result.error || '暂无数据'}</p>
                        <p style="font-size:0.9em;margin-top:10px;">请点击"更新数据"按钮获取最新数据</p>
                    </div>`;
                }
            }
        } catch (e) {
            if (content) {
                content.innerHTML = `<div style="text-align:center;padding:40px;color:var(--gray-500);">
                    <p>⚠️ 网络错误</p>
                    <p style="font-size:0.9em;margin-top:10px;">请确保 jianxi_server.py 已启动</p>
                </div>`;
            }
        }
    }

    /**
     * 显示时间轴列表
     */
    function displayTimelineList(timelineData) {
        const content = document.getElementById('timeline-list-content');
        if (!content) return;

        let html = '<div class="timeline-container">';
        for (const dayData of timelineData) {
            const date = dayData.date || '';
            const events = dayData.list || [];

            html += `<div class="timeline-day">
                <div class="timeline-date">${date}</div>
                <div class="timeline-events">`;

            for (const event of events) {
                const title = event.title || '';
                const themes = event.timeline?.theme_list || [];
                const themeNames = themes.map(t => t.name).join(', ');
                const grade = event.timeline?.grade || 0;
                const gradeLabel = grade >= 5 ? '⭐' : (grade >= 3 ? '📌' : '');

                html += `<div class="timeline-event">
                    <div class="event-title">${gradeLabel} ${title}</div>
                    ${themeNames ? `<div class="event-themes">${themeNames}</div>` : ''}
                </div>`;
            }

            html += '</div></div>';
        }
        html += '</div>';

        content.innerHTML = html;
    }

    /**
     * 更新全部数据
     */
    async function updateAllData() {
        const statusEl = document.getElementById('global-update-status');
        if (statusEl) {
            statusEl.style.display = 'block';
            statusEl.innerHTML = '<div class="loading-spinner"></div> 正在更新全部数据...';
        }

        try {
            const response = await fetch('http://localhost:5001/api/all/update', { method: 'POST' });
            const result = await response.json();

            if (result.success) {
                const r = result.results;
                let msg = '更新完成: ';
                if (r.action) msg += '异动 ';
                if (r.industry) msg += '产业库 ';
                if (r.timeline) msg += '时间轴';

                if (statusEl) {
                    statusEl.innerHTML = `<span style="color: green;">✅ ${msg}</span>`;
                }

                // 刷新各区块
                fetchActionList();
                fetchIndustryList();
                fetchTimelineList();
            } else {
                if (statusEl) {
                    statusEl.innerHTML = '<span style="color: orange;">⚠️ 部分数据更新失败</span>';
                }
            }
        } catch (e) {
            if (statusEl) {
                statusEl.innerHTML = `<span style="color: red;">❌ 更新失败: ${e.message}</span>`;
            }
        }
    }

    // ================================================
    // 概念走势看板功能
    // ================================================

    /**
     * 切换走势看板展开/收起
     */
    function toggleTrendBoard(conceptId) {
        const board = document.getElementById('board-' + conceptId);
        const btn = document.getElementById('btn-' + conceptId);
        const content = document.getElementById('concept-content-' + conceptId);
        if (!board || !btn) return;

        if (board.style.display === 'none' || board.style.display === '') {
            // 如果父级板块内容是收起状态，先展开它
            if (content && !content.classList.contains('show')) {
                content.classList.add('show');
                // 更新展开图标
                const icon = document.querySelector('#concept-header-' + conceptId + ' .expand-icon');
                if (icon) {
                    icon.classList.add('expanded');
                    icon.textContent = '▲';
                }
            }
            board.style.display = 'block';
            btn.textContent = '📈 收起走势看板';
            // 首次展开时渲染卡片
            renderTrendBoardCards(conceptId);
        } else {
            board.style.display = 'none';
            btn.textContent = '📈 查看走势看板';
        }
    }

    /**
     * 渲染走势看板股票卡片
     */
    function renderTrendBoardCards(conceptId) {
        const dataEl = document.getElementById('concept-stocks-' + conceptId);
        if (!dataEl) return;
        const grid = document.getElementById('grid-' + conceptId);
        if (!grid) return;

        // Always clear and re-render when called
        grid.innerHTML = '';

        let stocks;
        try {
            stocks = JSON.parse(dataEl.textContent);
        } catch (e) {
            console.error('Failed to parse concept stocks data:', e);
            return;
        }

        if (!stocks || stocks.length === 0) {
            grid.innerHTML = '<div class="jianxi-summary">暂无涨停数据</div>';
            return;
        }

        grid.innerHTML = stocks.map(s => {
            const prefix = s.code.startsWith('6') ? 'sh' : 'sz';
            const ts = Date.now();
            // 格式化所有涨停日期: "04/01, 04/03"
            const ztDatesStr = (s.zt_dates || []).map(d => d.substring(4, 6) + '/' + d.substring(6, 8)).join(', ');
            return `
                <div class="trend-stock-card">
                    <img class="trend-kline"
                         src="http://image.sinajs.cn/newchart/daily/n/${prefix}${s.code}.png?_t=${ts}"
                         onclick="openKLineModal('${s.code}', '${s.name}')"
                         alt="${s.name}"
                         onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 200 120%22><rect fill=%22%23f0f0f0%22 width=%22200%22 height=%22120%22/><text x=%2250%22 y=%2260%22 fill=%22%23999%22 font-size=%2212%22>加载失败</text></svg>'">
                    <div class="trend-stock-info">
                        <div class="stock-name">${s.name} <span style="color:#666;font-weight:normal;">(${s.code})</span></div>
                        <div class="zt-info">
                            <span class="zt-count">${s.zt_count}次涨停</span>
                            <div class="zt-dates">${ztDatesStr}</div>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    }

    // ================================================
    // 侧边栏功能
    // ================================================

    /**
     * 切换侧边栏显示/隐藏
     */
    function toggleSidebar() {
        var sidebar = document.getElementById('sidebar');
        var container = document.getElementById('main-container');
        if (sidebar) {
            sidebar.classList.toggle('collapsed');
            if (container) {
                container.classList.toggle('sidebar-collapsed');
            }
        }
    }

    /**
     * 加载侧边栏归档列表
     */
    function loadSidebarArchives() {
        var xhr = new XMLHttpRequest();
        xhr.open('GET', 'reports/data/', true);
        xhr.onreadystatechange = function() {
            if (xhr.readyState === 4 && xhr.status === 200) {
                var files = parseDirectoryListing(xhr.responseText);
                buildSidebarHTML(files, currentReportDate);
            }
        };
        xhr.send();
    }

    var currentReportDate = '';

    /**
     * 构建侧边栏HTML
     */
    function buildSidebarHTML(dates, activeDate) {
        if (!dates || dates.length === 0) {
            var content = document.getElementById('sidebar-content');
            if (content) content.innerHTML = '<div style="padding: 20px; text-align: center; color: #718096; font-size: 0.85em;">暂无归档</div>';
            return;
        }

        // 按月份分组
        var months = {};
        dates.forEach(function(f) {
            var d = f.replace('.json', '');
            var year = d.substring(0, 4);
            var month = d.substring(4, 6);
            var key = year + '-' + month;
            if (!months[key]) months[key] = [];
            months[key].push(d);
        });

        // 排序月份（降序）
        var sortedMonths = Object.keys(months).sort().reverse();

        // 展开当前日期所在月份
        var activeMonth = activeDate ? activeDate.substring(0, 7) : '';

        var html = '';
        sortedMonths.forEach(function(month) {
            var isOpen = month === activeMonth;
            var monthLabel = month.substring(0, 4) + '年' + month.substring(5, 7) + '月';
            var days = months[month].sort().reverse(); // 每天降序

            html += '<div class="sidebar-section">';
            html += '<div class="sidebar-month' + (isOpen ? ' open' : '') + '" onclick="toggleSidebarMonth(this)">';
            html += '<span>' + monthLabel + '</span>';
            html += '<span class="arrow">▶</span>';
            html += '</div>';
            html += '<div class="sidebar-days">';
            days.forEach(function(d) {
                var displayDate = d.substring(4, 6) + d.substring(6, 8);
                var isActive = d === activeDate;
                html += '<div class="sidebar-day' + (isActive ? ' active' : '') + '" onclick="selectArchiveDate(\'' + d + '\', this)">' + displayDate + '</div>';
            });
            html += '</div>';
            html += '</div>';
        });

        var content = document.getElementById('sidebar-content');
        if (content) content.innerHTML = html;
    }

    /**
     * 切换侧边栏月份展开/收起
     */
    function toggleSidebarMonth(el) {
        el.classList.toggle('open');
    }

    /**
     * 选择归档日期
     */
    function selectArchiveDate(date, el) {
        // 高亮当前选中
        document.querySelectorAll('.sidebar-day').forEach(function(el) {
            el.classList.remove('active');
        });
        if (el) {
            el.classList.add('active');
        } else {
            // 直接调用时通过日期查找元素
            document.querySelectorAll('.sidebar-day').forEach(function(item) {
                if (item.textContent === date.substring(4, 6) + '-' + date.substring(6, 8) + '日') {
                    item.classList.add('active');
                }
            });
        }

        // 切换报告
        loadReportData(date);
    }

    /**
     * 渲染报告后更新侧边栏
     */
    var originalRenderReport = renderReport;
    renderReport = function(data) {
        currentReportDate = data.date;
        originalRenderReport(data);
        loadSidebarArchives();
    };

    // 暴露全局函数
    window.getSinaCode = getSinaCode;
    window.openKLineModal = openKLineModal;
    window.closeKLineModal = closeKLineModal;
    window.switchKLineTab = switchKLineTab;
    window.toggleSidebar = toggleSidebar;
    window.showSection = showSection;
    window.switchReport = switchReport;
    window.toggleConcept = toggleConcept;
    window.toggleAllConcepts = toggleAllConcepts;
    window.toggleAllTrendBoards = toggleAllTrendBoards;
    window.toggleTrendBoard = toggleTrendBoard;
    window.loadArchive = loadArchive;
    window.refreshJianxi = refreshJianxi;
    window.onJianxiLoad = onJianxiLoad;
    window.onJianxiError = onJianxiError;
    window.analyzeJianxi = analyzeJianxi;
    window.updateJianxiData = updateJianxiData;
    window.fetchActionList = fetchActionList;
    window.fetchIndustryList = fetchIndustryList;
    window.fetchTimelineList = fetchTimelineList;
    window.updateAllData = updateAllData;
    window.loadLatestReport = loadLatestReport;
    window.loadReportData = loadReportData;
    window.showLoadError = showLoadError;
    window.renderReport = renderReport;
    window.toggleSidebarMonth = toggleSidebarMonth;
    window.selectArchiveDate = selectArchiveDate;
    window.renderLadder = renderLadder;
    window.renderMatrix = renderMatrix;
    window.renderTodayBoard = renderTodayBoard;
    window.renderJianxi = renderJianxi;
    window.renderMainThemes = renderMainThemes;
    window.renderConceptsGrid = renderConceptsGrid;
    window.renderConceptDetails = renderConceptDetails;
    window.renderOtherStocks = renderOtherStocks;
    window.renderNotZtStocks = renderNotZtStocks;
    window.renderMultiConceptStocks = renderMultiConceptStocks;
    window.parseDirectoryListing = parseDirectoryListing;
    window.findLatestDate = findLatestDate;

})();
