# A股题材轮动分析系统 — 设计方案

## 1. 项目概述

A股题材（概念）轮动分析与涨停联动检测系统。核心功能：

- **N字战法**：涨停连板 → 回调企稳 → 识别二波主升机会
- **涨停联动**：某只股票涨停后，同概念其他股票跟涨的概率分析
- **15日涨停板**：近期有涨停的股票分类展示
- **涨停回调推荐**：回调到位、具备反弹潜力的候选股票
- **自动K线补全**：启动时检测缺失数据，后台自动从 tushare 拉取

---

## 2. 系统架构

```
                    ┌─────────────────────────┐
                    │   stock_linkage_simple.py │  ← HTTP Server (端口 6688)
                    │   (单个HTML模板 + Python  │
                    │    HTTP路由)              │
                    └──────────┬──────────────┘
                               │ 调用
                    ┌──────────▼──────────────┐
                    │   stock_linkage_finder.py │  ← 分析引擎
                    │   (StockLinkageFinder)    │
                    └──────────┬──────────────┘
                               │ 依赖
          ┌────────────────────┼────────────────────┐
          ▼                    ▼                    ▼
  concept_data_fetcher    kline_database.py    update_zt_kline.py
  (概念数据加载)           (SQLite K线DB)      (tushare 数据获取)
```

### 2.1 核心文件职责

| 文件 | 职责 | 关键类/函数 |
|------|------|-------------|
| `stock_linkage_simple.py` | Web 服务器 + 全部前端（HTML/CSS/JS 内嵌）。端口 6688，单文件 | `Handler(HTTPRequestHandler)` |
| `stock_linkage_finder.py` | 分析引擎。涨停检测、联动分析、N字战法、推荐算法 | `StockLinkageFinder` |
| `kline_database.py` | SQLite K线数据库封装。读写 `stocks_kline.db` | `KlineDB` |
| `concept_data_fetcher.py` | 加载同花顺概念数据 JSON | `ConceptDataFetcher` |
| `update_zt_kline.py` | 从 tushare 批量获取K线数据 | `update_zt_stocks_kline()` |
| `fetch_kline_data.py` | 旧版K线获取（adata库，已弃用，改用 tushare） | — |

---

## 3. 数据源

### 3.1 涨停池 CSV（东方财富）
- 目录：`data/zt_pool/YYYYMMDD.csv`
- 45 个交易日，约 1332 只独立股票
- 字段：代码、名称、涨跌幅、最新价、连板数、炸板次数、封板时间等

### 3.2 K线数据库（SQLite）
- 文件：`data/stocks_kline.db`
- 表 `kline_daily`：~160万条记录，覆盖 5500+ 股票，日期范围 2025-02-19 ~ 至今
- 字段：stock_code, trade_date, open, high, low, close, volume, change_pct 等
- 涨停阈值：主板 ≥ 9.8%，创业板/科创板 ≥ 19.5%（根据 `change_pct` 字段）

### 3.3 同花顺概念数据
- 文件：`data/concept_stock/ths_concept_stock.json`
- 385 个概念 → 过滤后 358 个题材概念 → 5421 只股票
- 过滤关键词（非题材概念）：专精特新、人民币贬值、举牌、国企改革、ST板块等 27 个

### 3.4 交易日历
- 文件：`data/trade_calendar_2026.json`
- 格式：`["2025-02-19", "2025-02-20", ...]`
- 300 个交易日，JSON 文件中移除 `-` 后作为 `self.trade_dates`

---

## 4. 初始化流程（StockLinkageFinder.__init__）

```
1. ConceptDataFetcher()         → 加载同花顺概念 JSON
2. KlineDB()                    → 连接 SQLite，初始化 tushare
3. _build_concept_stock_map()   → 构建概念↔股票映射，过滤非题材概念
4. _load_trade_calendar()       → 加载交易日历（300天）
5. _load_zt_pool_data()         → 扫描 zt_pool/*.csv 加载45天涨停数据
6. _load_zt_from_db()           → SQL查询 change_pct 检测DB涨停
7. _merge_zt_data()             → 合并CSV+DB双源涨停记录
8. _check_and_auto_update()     → 检测缺失，后台线程自动补全
```

---

## 5. 核心算法

### 5.1 涨停联动分析

文件：`stock_linkage_finder.py` 方法 `find_stock_linkages()`

**原理**：对目标股票每个涨停日期，查找同概念其他股票在 lag 天后的涨停情况。

```
对目标股票A的每个涨停日期d:
  对同概念每只股票B:
    如果B在 d+lag 天也有涨停 → 计数+1

P(A→B) = count(B在A涨停后lag天也涨停) / A的涨停总天数
```

- lag=0: T+0 同日联动（同一交易日）
- lag=1: T+1 隔日联动（次日）
- lag=2: T+2 两日后
- lag=3: T+3 三日后

概率条颜色编码：T+0红，T+1橙，T+2蓝，T+3灰

**方向性分析**：反向概率 P(B→A) 一并计算，展示联动方向。

### 5.2 N字战法（涨停回调分析）

文件：`stock_linkage_finder.py` 方法 `analyze_n_pattern()`

**策略**：股票涨停连板后回调企稳，识别二波主升机会。

**分类**（按回调深度）：

| 类别Key | 名称 | 回调范围 |
|---------|------|---------|
| tld | 屠龙刀战法 | ≥60%（深度回调+主升浪结构） |
| 0-2 | 浅调 | 0~2% |
| 2-5 | 正常回调 | 2~5% |
| 5-8 | 深度回调 | 5~8% |
| 8-10 | 深调 | 8~10% |
| 10+ | 超跌 | 10%+ |

**特殊标记**：
- ⭐ — 高连板（≥2板）+ 无大跌异动
- ⟳ — 震荡形态
- ⚠ — 有炸板记录
- 「屠龙刀」— 60%+深度回调+主升浪结构
- 「首板屠龙」— 首板后深度回调
- 「N+W双底」— N字+W底复合形态

### 5.3 15日涨停板

文件：`stock_linkage_finder.py` 方法 `get_zt_window_stocks()`

按涨停日期距今日的交易日距离分组：

| 分组 | 标签 | 条件 |
|------|------|------|
| hot | 3日狙击 | ≤3个交易日 |
| warm | 5日蓄势 | 4-5个交易日 |
| cool | 10日潜伏 | 6-10个交易日 |
| cold | 15日余波 | 11-15个交易日 |

默认显示前50只，可展开显示全部。每只股票带K线图。

### 5.4 涨停回调推荐

文件：`stock_linkage_finder.py` 方法 `recommend_pullback_stocks()`

**筛选**：近15个交易日有涨停的股票

**评分维度**（100分制）：
- 回调质量（60%）：回调深度30% + 回调天数20% + 量缩20% + 均线支撑15% + 动量15%
- 热度（40%）：涨停次数 + 概念热度 + 连板数

**输出**：Top 30 推荐列表，附带买点建议（如"回调1天+深度5%+缩量企稳"）

### 5.5 自动K线补全

文件：`stock_linkage_finder.py` 方法 `_check_and_auto_update()`

启动时检测流程：
1. 查询 `SELECT MAX(trade_date) FROM kline_daily`
2. 与交易日历对比，找出缺失的交易日
3. 如有缺失 → 后台 daemon 线程启动：
   - 单次SQL查询所有股票的最新日期
   - 批量跳过数据已完整的股票
   - 对需要更新的股票调用 tushare API（0.3s间隔）
   - 保存到 SQLite DB，重载 finder 内存数据

---

## 6. Web 前端（stock_linkage_simple.py）

### 6.1 技术栈
- 纯 HTML + CSS + JavaScript（单文件内嵌）
- Chart.js 4.4.1（统计图表）
- chartjs-plugin-datalabels（图表数据标签）
- 无框架依赖

### 6.2 页面结构

```
┌─────────────────────────────────────┐
│  📊 A股题材轮动分析系统              │
│  状态栏 [🔄 更新]                   │
├─────────────────────────────────────┤
│  搜索框：股票代码/名称 + 概念        │
├──────┬──────────────────────────────┤
│  Tab │  内容区域                     │
│ 导航  │                              │
│──────│                              │
│ N字  │  N字战法·涨停回调             │
│ 战法  │  ├ 左侧导航栏                 │
│      │  ├ 过滤器（概念/N+W/屠龙刀）   │
│ 联动  │  ├ 6个分类（可折叠+显示全部） │
│ 查询  │  ├ 额外关注（炸板/创业科创）  │
│      │  └ 15日涨停板（4子分类）      │
│ 概念  │                              │
│ 分析  │  概念Top20 + 概念搜索         │
│      │                              │
│ 🔥   │  涨停回调推荐Top30            │
│ 推荐  │                              │
│      │                              │
│ 📈   │  统计页                       │
│ 统计  │  ├ 日期范围选择器             │
│      │  ├ 股票涨停排行（柱状图）      │
│      │  ├ 概念涨停活跃度（柱状图）    │
│      │  ├ 连板分布（柱状图）          │
│      │  └ 热门涨停股200只            │
└──────┴──────────────────────────────┘
```

### 6.3 关键交互功能

| 功能 | 实现方式 |
|------|---------|
| Tab切换 | `switchTab()` → 显示/隐藏对应 `.tab-content` |
| 折叠/展开 | `toggleNpCategory()` → 切换 `.collapsed` + `display:none` |
| 显示全部 | `toggleZtBoard()` / `toggleAlertBoard()` → 显示隐藏额外卡片 |
| 网格列数 | `setNpGridCols(2/4/6)` → 修改 CSS grid-template-columns |
| 概念过滤 | `filterNPattern()` → JS端过滤分类数组，无需后端请求 |
| 查看K线 | 点击任意股票代码 → `showStockCard()` K线弹窗 |
| 收起K线 | `toggleNpKline()` → canvas display 切换 |
| K线画布 | `renderNpKline()` → Canvas API 绘制（含MA5/MA10/涨停标记） |
| 更新数据 | `updateAllData()` → 调API → 轮询状态 → 刷新页面 |

### 6.4 左侧导航（N字战法页）

固定导航栏，含 8 个章节：
1. 屠龙刀战法
2. 0~2%
3. 2~5%
4. 5~8%
5. 8~10%
6. 10%+
7. 额外关注
8. 15日涨停

使用 `IntersectionObserver` 高亮当前章节，`scrollIntoView({behavior:'smooth'})` 平滑跳转。

---

## 7. 端口与API

### 7.1 Web 服务
- 端口：**6688**
- 启动：`python3 stock_linkage_simple.py`
- 绑定 `0.0.0.0`，局域网/云服务器均可访问

### 7.2 API 端点

| 端点 | 参数 | 返回 |
|------|------|------|
| `/` | — | HTML页面 |
| `/api/search` | `q`(代码/名称), `start_date`, `end_date`, `top_n` | 股票列表 |
| `/api/linkage` | `stock`, `concept`, `min_prob` | 联动结果 |
| `/api/kline` | `stock`, `days` | K线数据 |
| `/api/concept_zt_stats` | `concept` | 概念涨停统计 |
| `/api/concept_linkage` | `concept`, `top_n` | 概念内联动对 |
| `/api/stats` | `start_date`, `end_date`, `top_n` | 统计摘要+排行+每日活动 |
| `/api/stats_bucket` | `type`, `bucket`, `start_date`, `end_date` | 分桶详情 |
| `/api/hot_stocks` | `start_date`, `end_date`, `top_n` | 热门涨停股 |
| `/api/recommend` | `top_n` | 涨停回调推荐 |
| `/api/zt_window` | `lookback_days`, `top_n` | 15日涨停板(含K线) |
| `/api/n_pattern` | `lookback_days` | N字战法分析 |
| `/api/gem_arbitrage` | `stock`, `max_lag` | 创业板套利 |
| `/api/concepts` | — | 所有概念名称 |
| `/api/update_data` | — | 触发数据更新(后台) |
| `/api/update_status` | — | 查询更新状态 |

---

## 8. 数据库结构

### 8.1 kline_daily 表

```sql
CREATE TABLE kline_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL,
    volume REAL, amount REAL,
    change_pct REAL, change_val REAL,
    prev_close REAL, turnover_ratio REAL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(stock_code, trade_date)
);
```

索引：`idx_kline_stock`, `idx_kline_date`, `idx_kline_stock_date`

### 8.2 stocks 表

```sql
CREATE TABLE stocks (
    stock_code TEXT PRIMARY KEY,
    stock_name TEXT,
    exchange TEXT,
    market TEXT
);
```

### 8.3 trade_calendar 表（未使用，日历依赖 JSON 文件）

```sql
CREATE TABLE trade_calendar (
    trade_date TEXT PRIMARY KEY,
    is_open INTEGER
);
```

---

## 9. 部署说明

### 9.1 云服务器部署

```bash
# 上传项目到服务器
scp -r stock_concept_cycle/ user@server:/path/to/

# 安装依赖
pip install -r requirements.txt

# 后台运行（持久化）
nohup python3 -u stock_linkage_simple.py > server.log 2>&1 &

# 或使用 systemd 服务
```

### 9.2 更新数据

- **自动更新**：服务器启动时检测缺失的K线数据，后台线程自动补全
- **手动更新**：点击页面状态行的 `🔄 更新` 按钮 → 后台更新 → 自动刷新页面
- **全量更新**：`python3 update_zt_kline.py --full`

### 9.3 必须数据文件

```
data/
├── stocks_kline.db           # K线数据库（~500MB）
├── trade_calendar_2026.json  # 交易日历
├── concept_stock/
│   └── ths_concept_stock.json # 同花顺概念
├── zt_pool/                   # 涨停池CSV（45个文件）
└── all_a_stocks.json          # 全A股列表（可选）
```

---

## 10. 关键配置

| 配置项 | 位置 | 值 |
|--------|------|-----|
| 端口 | `stock_linkage_simple.py` main() | 6688 |
| tushare token | `kline_database.py` line 32 | `TUSHARE_TOKEN` |
| 涨停阈值主板 | `concept_data_fetcher.py` | ≥9.8% |
| 涨停阈值创业/科创板 | `concept_data_fetcher.py` | ≥19.5% |
| K线更新间隔 | `stock_linkage_finder.py` worker | 0.3秒 |
| 非题材过滤词 | `stock_linkage_finder.py` | 27个关键词 |
