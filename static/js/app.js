/**
 * 股票分析看板 V2 - 主应用逻辑
 */

(function() {
    'use strict';

    // 全局变量
    let currentStockCode = '';
    let currentStockPrefix = '';

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
            window.location.href = 'report_latest.html';
            return;
        }
        // 跳转到指定日期的报告
        window.location.href = date + '/report.html';
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
            } else {
                content.classList.add('show');
                icon.classList.add('expanded');
            }
        }
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
        // 跳转到归档文件
        window.location.href = 'archive/' + filename;
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

        // 从 localStorage 恢复上次查看的 section
        const savedSection = localStorage.getItem('currentSection') || 'trend';
        showSection(savedSection);

        // 绑定导航栏点击事件（使用事件委托）
        document.querySelector('.sidebar').addEventListener('click', function(e) {
            const navLink = e.target.closest('.nav-link');
            if (navLink) {
                e.preventDefault();
                const sectionId = navLink.getAttribute('data-section');
                if (sectionId) {
                    showSection(sectionId);
                }
            }
        });

        // 绑定侧边栏折叠按钮
        const toggleBtn = document.querySelector('.sidebar-toggle');
        if (toggleBtn) {
            toggleBtn.addEventListener('click', toggleSidebar);
        }

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
                treeDiv.innerHTML = '<p style="color:#e53e3e;">分析失败: ' + error.message + '</p>';
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
        if (!board || !btn) return;

        if (board.style.display === 'none' || board.style.display === '') {
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
            const dateFormatted = s.date.substring(4, 6) + '月' + s.date.substring(6, 8) + '日';
            return `
                <div class="trend-stock-card">
                    <img class="trend-kline"
                         src="http://image.sinajs.cn/newchart/daily/n/${prefix}${s.code}.png?_t=${ts}"
                         onclick="openKLineModal('${s.code}', '${s.name}')"
                         alt="${s.name}"
                         onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 200 120%22><rect fill=%22%23f0f0f0%22 width=%22200%22 height=%22120%22/><text x=%2250%22 y=%2260%22 fill=%22%23999%22 font-size=%2212%22>加载失败</text></svg>'">
                    <div class="trend-stock-info">
                        <span class="stock-name">${s.name}</span>
                        <span class="stock-date">${dateFormatted}</span>
                    </div>
                </div>
            `;
        }).join('');
    }

    // 暴露全局函数
    window.getSinaCode = getSinaCode;
    window.openKLineModal = openKLineModal;
    window.closeKLineModal = closeKLineModal;
    window.switchKLineTab = switchKLineTab;
    window.toggleSidebar = toggleSidebar;
    window.showSection = showSection;
    window.switchReport = switchReport;
    window.toggleConcept = toggleConcept;
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

})();
