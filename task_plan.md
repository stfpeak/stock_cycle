# Task Plan: 股票概念轮动分析系统功能增强

## Goal
完成 StockLinkageFinder 的 6 项待开发功能，提升 A 股概念/涨停联动分析能力。

## Current Phase
Phase 4

## Phases

### Phase 1: 算法增强 + Web UI 更新 (T+0 + 方向性 + 去重)
- [x] 增加 T+0 同日涨停联动检测
- [x] 去重：同只股票跨概念只出现一次
- [x] 联动方向性分析 (A→B vs B→A)
- [x] 修复分母 bug：分母=有效观测天数而非 len-lag
- [x] 更新 Web UI 展示 T+0/方向性/去重
- **Status:** complete

### Phase 2: 统计划表
- [x] 总涨停次数统计图表（股票/概念维度）
- [x] Chart.js 图表（Top 股票/概念/每日趋势/分布饼图）
- [x] 📈 统计 Tab 页面
- **Status:** complete

### Phase 3: 涨停回调买入推荐算法
- [x] 候选筛选 + 连板检测 + 回调状态评分
- [x] 买点建议 + 综合排序
- [x] 🔥 推荐 Tab（卡片列表展示 Top 30）
- **Status:** complete

### Phase 4: 概念轮动热力图
- [ ] 实现概念-时间维度涨停热度矩阵
- [ ] 颜色编码热力图展示
- [ ] 支持日期范围筛选
- **Status:** pending

### Phase 5: 数据导出功能
- [ ] 实现 CSV/JSON 导出 API
- [ ] UI 添加导出按钮
- [ ] 支持联动结果、涨停统计等导出
- **Status:** pending

## Key Questions
1. FastAPI 具体版本号和兼容错误信息是什么？
2. T+0 联动阈值如何定义？同日涨停即算联动还是需要时间间隔？
3. 热力图数据量级多少，是否需要前端分页？

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| 沿用现有 stock_linkage_simple.py 作为主服务 | 已验证稳定运行，避免重复开发 |
| 新增功能先在 simple 版实现，再同步到 web 版 | 降低风险，快速迭代 |
| 优先实现 T+0 和方向性分析 | 这两个是基础增强，后续功能依赖 |

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
|       | 1       |            |
