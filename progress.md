# Progress Log

## Session: 2026-05-08

### Phase 0: 项目恢复与规划
- **Status:** complete
- **Started:** 2026-05-08
- Actions taken:
  - 读取项目记忆文件和当前 git 状态
  - 安装 planning-with-files skill（Manus 风格规划工作流）
  - 创建 task_plan.md / findings.md / progress.md
  - 回顾已完成的 4 项工作和 6 项待开发功能
- Files created/modified:
  - task_plan.md (created)
  - findings.md (created)
  - progress.md (created)

### Phase 1: 算法增强 + Web UI 更新
- **Status:** complete
- **Started:** 2026-05-08
- Actions taken:
  - 完成 V5 算法升级（stock_linkage_finder.py）：
    1. T+0 同日涨停联动检测 —— 新增 lag=0 支持
    2. 去重 —— 同只股票跨概念只出现一次，显示共享概念数
    3. 方向性分析 —— 增加反向 B→A 概率统计
    4. 概率计算 bug 修复 —— 分母改为"有效观测天数"而非 "len - lag"
  - 更新 Web UI（stock_linkage_simple.py）：
    1. 联动表格新增 T+0 列（红色概率条）和概念数列
    2. 联动事件详情行展示反向概率
    3. 方向性摘要徽章（A→B 联动 N 只 / 强联动 N 只）
    4. 概念分析联动对新增 T+0 ~ T+3 列
    5. 版本号更新为 V5
  - 验证：概率异常 0 条，所有值在 0-100%
- Files created/modified:
  - stock_linkage_finder.py (updated, V5)
  - stock_linkage_simple.py (updated, V5 UI)

### Phase 2: 统计图表
- **Status:** complete
- **Started:** 2026-05-08
- Actions taken:
  - 新增 StockLinkageFinder 统计方法：
    - `get_stats_summary()` — 整体摘要（股票/涨停事件数/分布）
    - `get_top_stocks_by_zt(n)` — 涨停次数最多的股票
    - `get_top_concepts_by_zt(n)` — 涨停活跃度最高的概念
    - `get_daily_zt_activity(days)` — 每日涨停股票数趋势
    - `get_concept_daily_heatmap(top_n, days)` — 概念涨停热力图矩阵（供后续热力图使用）
  - 新增 `/api/stats` 端点，返回所有统计数据
  - 新增「📈 统计」Tab 页面，包含：
    - 4 个统计卡片（有涨停股票1748只 / 总涨停事件5090次 / 日期范围 / 概念总数385个）
    - 水平柱状图：涨停次数最多股票 Top 20（Chart.js）
    - 水平柱状图：涨停活跃概念 Top 20（涨停事件+涨停股票数双系列）
    - 折线图：每日涨停股票数（近60天）
    - 饼图：涨停次数分布
- Files created/modified:
  - stock_linkage_finder.py (新增统计方法)
  - stock_linkage_simple.py (新增 /api/stats 端点 + 统计 Tab UI)

### Phase 3: 涨停回调买入推荐算法
- **Status:** complete
- **Started:** 2026-05-08
- Actions taken:
  - 新增 `recommend_pullback_stocks()` 方法：
    1. 筛选近 15 个交易日有涨停的股票（888 只候选）
    2. 批量 K 线查询（5/6 规则：至少 5 根有效 K 线）
    3. 连板检测（连续涨停分析）
    4. 回调状态评估：
       - 回调天数（1-5 天为佳）
       - 回调深度（2-6% 为最佳健康回调）
       - 成交量萎缩比例（<0.7 缩量企稳最好）
       - 均线支撑（MA5 > MA10 站上）
       - 概念热度归一化
    5. 综合评分：回调质量 60% + 热度 40%
    6. 自动生成买入建议
  - 新增 `_generate_buy_advice()` 方法 — 生成中文买点建议
  - 新增 `🔥 推荐` Tab 页面 — 卡片列表展示 Top 30 推荐
  - 新增 `/api/recommend` 端点
  - 推荐结果：每条包含涨停日期、连板数、回调天数/深度、量比、均线位置、概念热度、买点建议
- Files created/modified:
  - stock_linkage_finder.py (新增推荐算法)
  - stock_linkage_simple.py (新增推荐 Tab + API)

### Phase 4: 概念轮动热力图
- **Status:** pending
- Actions taken:
  - （待开始）
- Files created/modified:
  -

## Test Results
| Test | Input | Expected | Actual | Status |
|------|-------|----------|--------|--------|
|      |       |          |        |        |

## Error Log
| Timestamp | Error | Attempt | Resolution |
|-----------|-------|---------|------------|
|           |       | 1       |            |

## 5-Question Reboot Check
| Question | Answer |
|----------|--------|
| Where am I? | Phase 3 complete - Recommend Algorithm done |
| Where am I going? | Phase 4: Concept Rotation Heatmap |
| What's the goal? | Complete all 5 phases for StockLinkageFinder V5 |
| What have I learned? | See findings.md |
| What have I done? | V5 algorithm upgrade + Stats charts + Recommend algorithm + Fix bottlenecks dependency |

## 会话结束：2026-05-08
- Phase 1-3 已完成
- 服务已停止
- 下次启动：`python stock_linkage_simple.py` → http://localhost:5001
