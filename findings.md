# Findings & Decisions

## Requirements
- 6 项待开发功能来自上次会话总结
- 核心文件：`stock_linkage_finder.py`（分析引擎）、`stock_linkage_simple.py`（Web 服务）
- 数据源：`data/stocks_kline.db`（K线 SQLite）、`data/zt_pool/YYYYMMDD.csv`（涨停池）
- 概念映射：`data/concept_stock/ths_concept_stock.json`

## Research Findings
- `stock_linkage_simple.py` 使用 Python 内置 `http.server`，无外部依赖，稳定运行于端口 5001
- `stock_linkage_web.py` 使用 FastAPI，上次因版本兼容问题不可用
- 联动检测逻辑在 `stock_linkage_finder.py` 的 `find_stock_linkages()` 方法中
- 当前只检测 T+1/T+2/T+3（隔N天），未检测 T+0（同日）
- 双源涨停检测：涨停池 CSV（45 天）+ K线数据库（79 天）

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| 主攻 stock_linkage_simple.py 增强 | 已稳定运行，无外部依赖问题 |
| 联动检测扩展参数支持 lag=0 | 最小改动实现 T+0 支持 |
| Canvas 图表优先于 Chart.js | 减少前端依赖，且已有实现基础 |

## Issues Encountered
| Issue | Resolution |
|-------|------------|
| Python 三引号中 `\'` 转义导致 JS SyntaxError | 改为 data-* 属性 + 事件委托，已修复 |
| 概率计算分母 bug | 分母=有效观测天数(能查到 lag 日期的天数)而非 len-lag |
| K线 DB 日期格式不匹配(含横线 vs 无横线) | SQL 查询时格式化为 `YYYY-MM-DD` |
| bottleneck 版本过低(pandas warning) | pip install --upgrade bottleneck 1.3.5→1.6.0 |

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| 主攻 stock_linkage_simple.py 增强 | 已稳定运行，无外部依赖问题 |
| 联动检测扩展参数支持 lag=0 | 最小改动实现 T+0 支持 |
| Canvas 图表优先于 Chart.js | 减少前端依赖，且已有实现基础 |
| Chart.js CDN 用于统计图表 | 成熟稳定，4 种图表类型支持，CDN 加载快 |
| 推荐算法使用 K线 DB 批量查询 | 避免 N+1 问题，单次查询效率高 |
| 回调评分：质量 60% + 热度 40% | 平衡形态和活跃度 |

## Key Data
- 有涨停记录的股票：1748 只
- 总涨停事件：5090 次
- 概念总数：385 个
- 交易日范围：20260105 ~ 20260507 (79天)
- 涨停分布：1次(705只) 2-3次(567只) 4-6次(313只) 7-10次(119只) 11-20次(44只)
- 回调推荐候选池：888只（近15日有涨停），最终推荐 Top 30

## Resources
- 主分析引擎：`stock_linkage_finder.py`
- 运行中 Web 服务：`stock_linkage_simple.py`（端口 5001）
- K线数据库：`data/stocks_kline.db`
- 涨停池目录：`data/zt_pool/`
- 概念-股票映射：`data/concept_stock/ths_concept_stock.json`
- 交易日历：`data/trade_calendar_2026.json`

## Visual/Browser Findings
（待补充）
