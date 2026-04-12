# 概念涨停股走势看板设计

## 概述

在TOP20概念题材折叠展开后，添加"查看走势看板"功能按钮。点击后在概念内容区下方展示该概念近15个交易日涨停股的K线走势，以矩阵方式平铺展示。

## 功能位置

在每个概念的折叠内容区（`concept-content-{id}`）顶部添加看板触发按钮。

## 交互逻辑

1. **按钮文案**："📈 查看走势看板"
2. **点击行为**：在概念内容底部追加/展开走势看板区域
3. **再次点击**：收起走势看板，按钮文字恢复为"📈 查看走势看板"
4. **数据范围**：近15个交易日（基于当前报告日期往前推）

## 界面布局

### 看板头部
- 标题：`📈 {概念名称} 涨停股走势看板（近15日）`
- 关闭按钮：`✕` 收起看板

### 股票网格
- **排序规则**：
  - 主排序：`交易日期` ASC（越早涨停越前）
  - 次排序：`首次封板时间` ASC（同日内按时间排序）
  - **说明**：同一股票多次涨停（如4月9日首板、4月10日2板）会重复展示为多张卡片
- 布局：每行3个股票（固定宽度220px），自适应换行
- 每个股票卡片：
  - K线图：宽200px × 高120px
  - 股票名称在K线图下方
  - 涨停日期标注在名称右侧
  - 点击K线图可查看大图（复用现有弹窗）

### K线图说明
- 使用新浪日K线API：`http://image.sinajs.cn/newchart/daily/n/{prefix}.png`
- 返回的是该股票**最近约15个交易日**的日K走势图
- 股票前缀：`sh`（600/688开头）或 `sz`（000/300开头）
- 添加cache-busting参数：`?_t={timestamp}`

## 数据来源

- 从 `data/zt_pool/` 目录读取历史涨停数据
- 在报告生成时预计算每个概念的涨停股票列表
- 筛选条件：
  - 股票属于当前概念
  - 交易日期在近15个交易日内
  - 按 `交易日期` ASC、`首次封板时间` ASC 排序

## 技术实现

### HTML结构
```html
<div class="concept-trend-board" id="board-{conceptId}" style="display:none;">
  <div class="trend-board-header">
    <h4>📈 {概念名称} 涨停股走势看板（近15日）</h4>
    <button class="close-btn" onclick="toggleTrendBoard('{conceptId}')">✕</button>
  </div>
  <div class="trend-board-grid" id="grid-{conceptId}">
    <!-- 由 renderTrendBoardCards() 动态渲染 -->
  </div>
</div>
```

### 卡片HTML
```html
<div class="trend-stock-card">
  <img class="trend-kline" src="http://image.sinajs.cn/newchart/daily/n/sh600743.png?_t=1234567890"
       onclick="openKLineModal('600743', '华远控股')"
       alt="{股票名称}">
  <div class="trend-stock-info">
    <span class="stock-name">{名称}</span>
    <span class="stock-date">{涨停日期}</span>
  </div>
</div>
```

### CSS样式
```css
.concept-trend-board {
  margin-top: 20px;
  padding: 15px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
}
.trend-board-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 15px;
  padding-bottom: 10px;
  border-bottom: 2px solid #e2e8f0;
}
.trend-board-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 15px;
}
.trend-stock-card {
  width: 220px;
  text-align: center;
}
.trend-kline {
  width: 200px;
  height: 120px;
  cursor: pointer;
  border: 1px solid #e2e8f0;
  border-radius: 4px;
  background: #fff;
}
.trend-kline:hover {
  border-color: #4299e1;
}
.trend-stock-info {
  margin-top: 5px;
  font-size: 0.85em;
  color: #4a5568;
}
.stock-name { font-weight: 600; }
.stock-date { color: #a0aec0; margin-left: 8px; }
```

### JavaScript函数
```javascript
function toggleTrendBoard(conceptId) {
  const board = document.getElementById('board-' + conceptId);
  const btn = document.getElementById('btn-' + conceptId);
  if (board.style.display === 'none') {
    board.style.display = 'block';
    btn.textContent = '📈 收起走势看板';
    // 首次展开时渲染卡片
    renderTrendBoardCards(conceptId);
  } else {
    board.style.display = 'none';
    btn.textContent = '📈 查看走势看板';
  }
}

function renderTrendBoardCards(conceptId) {
  const dataEl = document.getElementById('concept-stocks-' + conceptId);
  if (!dataEl) return;
  const stocks = JSON.parse(dataEl.textContent);
  const grid = document.getElementById('grid-' + conceptId);
  if (!grid || grid.children.length > 0) return; // 已渲染则跳过

  // 不限制数量，全部展示

  grid.innerHTML = limited.map(s => {
    const prefix = s.code.startsWith('6') ? 'sh' : 'sz';
    const ts = Date.now();
    return `
      <div class="trend-stock-card">
        <img class="trend-kline"
             src="http://image.sinajs.cn/newchart/daily/n/${prefix}${s.code}.png?_t=${ts}"
             onclick="openKLineModal('${s.code}', '${s.name}')"
             alt="${s.name}"
             onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 200 120%22><rect fill=%22%23f0f0f0%22 width=%22200%22 height=%22120%22/><text x=%2250%22 y=%2260%22 fill=%22%23999%22 font-size=%2212%22>加载失败</text></svg>'">
        <div class="trend-stock-info">
          <span class="stock-name">${s.name}</span>
          <span class="stock-date">${s.date}</span>
        </div>
      </div>
    `;
  }).join('');
}
```

## 修改文件

1. `static/css/dashboard.css` - 添加走势看板样式
2. `static/js/app.js` - 添加 toggleTrendBoard 函数
3. `stock_dashboard_v2.py` - 在 generate_concept_section() 中：
   - 添加"查看走势看板"按钮
   - 预计算并嵌入涨停股票列表数据
   - 添加看板HTML结构

## 数据嵌入格式

在HTML中嵌入每个概念的涨停股票数据（用于JS渲染看板）：

```html
<script type="application/json" id="concept-stocks-{conceptId}">
[
  {"code": "600743", "name": "华远控股", "date": "20260410", "time": "09:31:12"},
  {"code": "603777", "name": "来伊份", "date": "20260410", "time": "09:35:08"},
  ...
]
</script>
```

## 修改文件

1. `static/css/dashboard.css` - 添加走势看板样式
2. `static/js/app.js` - 添加 toggleTrendBoard 和 renderTrendBoardCards 函数
3. `stock_dashboard_v2.py` - 在 generate_concept_section() 中：
   - 添加"查看走势看板"按钮（id: `btn-{conceptId}`）
   - 预计算并嵌入涨停股票列表数据（JSON script标签）
   - 添加看板HTML结构（id: `board-{conceptId}`, `grid-{conceptId}`）

## 注意事项

- K线图使用日线（daily），展示股票约15日走势
- 同一股票多次涨停会重复展示
- 新浪API图片加载失败时显示占位图
