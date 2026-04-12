# 进度日志

## 2026-04-13

### 股票代码前导零丢失修复

**问题**：以 `00` 开头的股票代码（如 `000555`）在转换过程中前导零丢失，变成 `555`，导致新浪K线URL无法正确生成。

**修复文件**：`stock_dashboard_v2.py`

**修复内容**：

| 位置 | 修复前 | 修复后 |
|:-----|:-------|:-------|
| Line 342 | `code = str(row['股票代码'])` | `code = str(row['股票代码']).zfill(6)` |
| Line 366 | `hot_stocks_set` 不格式化 | `hot_stocks_set` 使用 `str.zfill(6)` |
| Line 370 | `str(int(x))` | `str(int(x)).zfill(6)` |
| Line 379 | `code = str(stock['stock_code'])` | `code = str(stock['stock_code']).zfill(6)` |
| Line 397-398 | `股票代码` 不格式化 | 使用 `str.zfill(6)` |
| Line 421 | 比较不格式化 | 使用 `str.zfill(6)` 比较 |
| Line 484 | 比较不格式化 | 使用 `str.zfill(6)` 比较 |
| Line 553 | 比较不格式化 | 使用 `str.zfill(6)` 比较 |
| get_hot_rank | 不格式化比较 | 使用 `str.zfill(6)` 比较 |
| get_hot_value | 不格式化比较 | 使用 `str.zfill(6)` 比较 |
| get_all_concepts | 不格式化比较 | 使用 `str.zfill(6)` 比较 |

**效果**：
- `其他概念涨停股`: 255 → 272（+17，因为00开头股票被正确匹配）
- `多概念股票`: 158 → 153（-5，因为之前匹配有误）

**新浪K线URL修复**：
- 修复前：`sz555.png` → 错误
- 修复后：`sz000555.png` → 正确

### 运行命令

```bash
python stock_dashboard_v2.py  # 重新生成报告
```

---

## 2026-04-11/12

### 完成内容

1. **TOP20概念题材折叠菜单**
   - 每个概念可展开/收起详情
   - 包含今日涨停、15日涨停、最高连板、多板次数统计
   - expand-icon 旋转动画

2. **市场主线识别**
   - 在概念板块一览顶部显示主线题材
   - 条件：今日涨停≥2 且 热度>5000
   - 取前3名显示

3. **"1.0板"问题修复**
   - 在 `analyze_concept_stocks` 中使用 `int()` 转换连板数
   - 在 `generate_markdown` 中同样修复

4. **导航更名**
   - "概念详情" → "TOP20概念题材"

5. **toggleConcept() JS函数**
   - 添加到 HTML 底部 script 区域
   - 使用 `concept-content-{id}` 和 `icon-{id}` 切换显示

### 错误记录

| 错误 | 尝试次数 | 解决 |
|:---|:---:|:---|
| IndentationError | 1 | 修复 market theme 代码缩进 |
| UnboundLocalError | 1 | 移动 get_hot_rank 函数定义位置 |
| 概念匹配返回0 | 1 | 添加 `代码_str` 字段 |
| "1.0板"显示 | 1 | int() 转换 |

### 生成的报告

```
reports/
├── index.html              # 报告索引页
├── report_latest.html      # 最新报告软链接
└── 20260411/
    ├── report.md           # Markdown版本
    └── report.html         # HTML版本
```

### 运行命令

```bash
python stock_dashboard_v2.py  # 生成报告
python update_data.py           # 更新数据
```

### 涨停简图功能 (2026-04-12)

1. **新增文件**
   - `analyze_jianxi.py` - AI视觉分析脚本
   - `api_server.py` - Flask API 服务
   - `zt_jianxi.png` - 涨停简图示例图片

2. **修改文件**
   - `stock_dashboard_v2.py` - sentiment section 新增涨停简图UI
   - `static/css/dashboard.css` - 添加 jianxi-* 样式
   - `static/js/app.js` - 添加涨停简图相关JS函数

3. **功能说明**
   - 涨停简图图片展示（从韭研公社获取）
   - 日期选择器
   - AI分析按钮（预留后端API）
   - 刷新图片按钮
   - 可折叠的原站iframe

4. **待完成**
   - AI分析需要配置 OpenAI/Anthropic API
   - 运行 `python api_server.py` 启动API服务
   - 前端调用 `/api/analyze-jianxi` 获取分析结果

### 产业库和时间轴数据扩展 (2026-04-12)

1. **问题**
   - 产业库原本只有6个产业，用户要求显示更多
   - 时间轴原本只有4天，用户要求显示完整月份

2. **解决**
   - 从韭研公社网页提取完整的产业列表（15个产业）
   - 从韭研公社网页提取完整的时间轴（4月份28天）
   - 修复JSON中的中文引号问题

3. **更新的数据文件**
   - `data/industry_list.json` - 15个产业，每个都有 industry_id、title、keyword、content
   - `data/timeline_list.json` - 28天的时间轴事件

4. **API更新**
   - `jianxi_server.py` 中的 `/api/industry/update` 将 limit 从 15 改为 100

5. **验证结果**
   - 产业库：15个产业，每个都有可点击链接跳转韭研公社
   - 时间轴：28天完整展示所有事件

## 2026-04-12 下午（续）

### 概念走势看板功能 - 已完成提交

1. **功能说明**
   - 在TOP20概念板块的展开内容区添加"📈 查看走势看板"按钮
   - 点击后以网格方式平铺展示近15个交易日所有涨停股的K线走势
   - 排序规则：交易日期 ASC（越早涨停越前）+ 首次封板时间 ASC
   - 每行3个股票卡片（220px宽度），自适应换行
   - 使用新浪日K线API获取K线图
   - 点击K线图可查看大图（复用现有弹窗）

2. **提交记录**
   ```
   9c7e841 feat: add concept trend board feature for TOP20 concepts
   ```

3. **修改的文件**
   | 文件 | 说明 |
   |------|------|
   | `static/css/dashboard.css` | 添加走势看板CSS样式 |
   | `static/js/app.js` | 添加 toggleTrendBoard() 和 renderTrendBoardCards() |
   | `stock_dashboard_v2.py` | 添加按钮、JSON数据嵌入、看板HTML结构 |

4. **技术要点**
   - 数据嵌入：`<script type="application/json" id="concept-stocks-{id}">` 嵌入JSON
   - 首次封板时间：CSV的 `首次封板时间` 列（HHMMSS格式如92500表示09:25:00）
   - 格式化函数：`format_seal_time()` 处理NaN值并转换为HH:MM:SS
   - 日期排序：dates列表倒序，需 `reversed(dates)` 得到ASC

5. **遇到的问题及修复**
   | 问题 | 修复方案 |
   |:---|:---|
   | format_seal_time() NaN处理 | try/except，NaN返回空字符串 |
   | first_seal为None排序失败 | sort key用 `x['first_seal'] or ''` |
   | 重新渲染Bug（grid.children.length > 0） | 移除检查，每次先清空grid.innerHTML |
   | 日期显示"20260410"原始格式 | JS中格式化为"04月10日" |

6. **待继续的工作**
   - **K线图来源替换**：用户想找新浪K线替代方案（新浪不稳定）
     - 原计划讨论但转向了走势看板功能
     - 待后续讨论其他K线数据源

## 2026-03-22 (旧项目记录)

见原始 progress.md 历史记录（stock_analysis_skill 项目）
