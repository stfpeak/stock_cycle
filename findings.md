# 研究发现

## 技术发现

### 代码比较问题 (2026-04-11)
- **问题**：akshare 返回的 `代码` 列为 float 类型（如 600396.0），字符串比较失败
- **解决**：添加 `代码_str` 字段
```python
df_zt_pool['代码_str'] = df_zt_pool['代码'].apply(lambda x: str(int(x)))
```

### "1.0板" 小数点问题
- **问题**：`最大连板数` 为 float（如 1.0），显示时带小数点
- **解决**：使用 `int()` 转换
```python
lb = int(stock['最大连板数']) if pd.notna(stock['最大连板数']) else 1
```

### 交易日历获取失败
- **问题**：adata.stock.info.trade_calendar 返回列名不是 '日期'
- **解决**：使用 try/except + 工作日备用逻辑
```python
except Exception as e:
    print(f"  ⚠ 获取交易日历失败: {e}")
    # 备用：使用工作日计算
```

### 概念折叠功能 JS
- **问题**：折叠菜单需要客户端 JS 控制
- **解决**：toggleConcept() 函数
```javascript
function toggleConcept(conceptId) {
    var content = document.getElementById('concept-content-' + conceptId);
    var icon = document.getElementById('icon-' + conceptId);
    content.classList.toggle('show');
    icon.classList.toggle('expanded');
}
```

## 韭研公社简图获取 (2026-04-12)

### 关键发现
- **不能通过URL直接访问历史日期**：`/action/20260408` 会被重定向到最新日期
- **必须通过点击箭头逐日导航**：使用页面上的左右箭头 `` `` 逐日浏览
- **简图URL是JS动态加载的**：需要等待图片加载完成才能获取URL

### 获取步骤
1. 访问 `https://www.jiuyangongshe.com/action/YYYYMMDD`
2. 点击左侧箭头 `` 导航到目标日期的前一个日期
3. 再点击右侧箭头 `` 前进到目标日期
4. 点击"涨停简图"标签
5. 等待图片加载完成

### Chrome DevTools 提取脚本
```javascript
// 在页面加载完成后执行
const tabs = document.querySelectorAll('.yd-tabs_item');
const jianxiTab = Array.from(tabs).find(t => t.textContent.includes('涨停简图'));
if (jianxiTab) jianxiTab.click();

setTimeout(() => {
  const imgs = document.querySelectorAll('img');
  const jianxiImg = Array.from(imgs).find(img =>
    img.naturalWidth > 1000 && img.src.includes('jiucaigongshe') && !img.src.includes('resize')
  );
  console.log(jianxiImg ? jianxiImg.src : 'not found');
}, 1000);
```

### 图片URL特征
- 格式: `https://jiucaigongshe.oss-cn-beijing.aliyuncs.com/{UUID}.png`
- 尺寸: 通常 2280x4000+ 像素（大图）
- 特征: naturalWidth > 1000，src包含 `jiucaigongshe`

### 文件存储
- 简图目录: `data/jianxi/`
- URL缓存: `data/jianxi_urls.json`
- 更新命令: `python update_jianxi.py`

## 数据源

### akshare
- `ak.stock_zt_pool_em(date)` - 涨停板数据
- `ak.stock_board_concept_name_em()` - 概念板块列表

### adata
- `adata.stock.info.trade_calendar(year)` - 交易日历
- `adata.sentiment.hot.hot_concept_20_ths()` - 热门概念TOP20
- `adata.sentiment.hot.hot_rank_100_ths()` - 热股TOP100

### 同花顺
- `ak.stock_board_concept_name_ths()` - 概念板块详情
- `ak.stock_board_industry_cons_ths(symbol)` - 板块成分股

## 项目结构

```
stock_analysis_skill_v2/
├── stock_dashboard_v2.py     # 主报告生成脚本
├── update_data.py             # 数据更新脚本
├── data/
│   ├── zt_pool/               # 涨停数据（按日期）
│   ├── concepts/              # 概念数据
│   ├── hot_stocks/            # 热股数据
│   └── jianxi/                # 简图数据
├── cache/
│   └── update_status.json     # 更新状态记录
└── reports/                   # 报告输出
    ├── index.html             # 报告索引
    ├── report_latest.html      # 最新报告
    └── YYYYMMDD/              # 按日期归档
        ├── report.md
        └── report.html
```

## 报告页面结构

1. **总览** - 今日概况、核心数据
2. **连板天梯** - 梯度统计、连板股票
3. **概念矩阵** - TOP20概念关联矩阵
4. **今日涨停** - 今日涨停个股
5. **概念板块一览** - 市场主线识别
6. **TOP20概念题材** - 可折叠概念详情 + **走势看板**
7. **其他概念** - 非TOP20概念涨停股

## 概念走势看板技术要点 (2026-04-12)

### 首次封板时间格式
- CSV列名：`首次封板时间`
- 格式：HHMMSS数值（如 92500.0 表示 09:25:00）
- 格式化函数：
```python
def format_seal_time(t):
    if t is None:
        return ''
    try:
        s = str(int(t)).zfill(6)  # "092500"
        return f"{s[:2]}:{s[2:4]}:{s[4:]}"  # "09:25:00"
    except (ValueError, TypeError):
        return ''
```

### JSON数据嵌入方式
```html
<script type="application/json" id="concept-stocks-{conceptId}">
[{"code": "600743", "name": "华远控股", "date": "20260410", "time": "09:25:00"}, ...]
</script>
```

### 排序规则
- 主排序：交易日期 ASC（日期越早越前，需反转dates列表）
- 次排序：首次封板时间 ASC（同日内按时间排序，None值放最后）

### K线图URL
- 新浪日K线：`http://image.sinajs.cn/newchart/daily/n/{prefix}{code}.png`
- 前缀：sh（600/688开头）或 sz（000/300开头）
8. **未涨停热股** - TOP100中未涨停
9. **多概念股** - 跨3+概念的股票
