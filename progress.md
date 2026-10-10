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

## Session: 2026-09-12

### 复盘模块与数据同步经验
- **Status:** paused，服务已关闭，后续继续开发
- 完成市场结构/题材复盘模块增强：
  1. 今日复盘总结按“市场环境 → 题材阶段 → 关键角色 → 明日任务 → 买卖条件 → 剧本/观察点”生成。
  2. 盘中题材每日总结、题材涨停天梯复盘与“实时-今日涨停”复用同一 akshare 实时涨停池。
  3. 仅北京时间交易日 9:25~15:00 每分钟刷新；盘后和非交易日不自动请求。
  4. 同层断板股按断板天数从短到长排列；历史回放显示首板以来累计涨幅。
  5. 题材涨停数量达到 4 只及以上时，在时间滑块上显示小高潮标记。
  6. 更新状态只按涨停日数据判断，不能把 K 线历史覆盖缺口混入“缺 X 天数据”。
- 已验证：Python 编译通过，嵌入前端 JavaScript `node --check` 通过。
- GitHub 已推送：`4df41d1 feat: improve review sync and ladder calculations`。
- 云主机已同步并重启：`106.53.189.86:6688`；同步脚本会跳过 `data/stocks_kline.db`。
- 以后发布流程：先语法检查 → 本地验证 → 提交 GitHub → 用户确认后执行 `./sync.sh` 云同步并核验远程 6688。
- 重要约束：历史复盘不能使用未来数据；更新提示区分涨停数据与 K 线辅助数据；不要再次把 K 线“缺 4 天”显示在更新按钮后。

## Session: 2026-09-12（K线缩略图与发布）

### 本次经验
- 实时-今日涨停表格新增日K与分时缩略图，固定容器尺寸，避免影响表格列宽和行高。
- 缩略图白底；悬停时单图独立放大，并以右边缘为锚点向左展开，避免屏幕右侧裁切。
- 悬停查看时按 10 秒节流刷新新浪图片 URL，盘中可请求最新图；表格刷新时也带时间戳防止旧缓存。
- 修改后先执行 Python 编译与嵌入 JavaScript `node --check`，再重启本地服务验证。
- 本次提交：`8052b4b feat: improve inline realtime chart preview`，已推送 GitHub，并通过 `./sync.sh` 同步云主机、重启远程服务。
- 停止服务前记录状态；下次继续开发先启动：`python3 stock_linkage_simple.py` → http://localhost:6688

## Session: 2026-05-23

### Phase 6: 前端Tab数据预取缓存 + 云主机故障排查
- **Status:** complete
- **Started:** 2026-05-23
- Actions taken:
  1. 新增 `_tabCache` / `_cachedFetch(url)` / `_clearTabCache()` / `_prefetchAllTabs()` 缓存体系
  2. 替换 8 个 `load*()` 函数中的 `fetch` 为 `_cachedFetch`
  3. `_cachedFetch` 空数组保护：`[]` 不缓存，确保预取空时自动重试
  4. 数据更新后 `_clearTabCache()` 清空缓存
  5. 错别字修正：首版屠龙 → 首板屠龙
  6. 排查云主机同花顺热股/概念数据为空：
     - adata 直调正常 → finder 调用正常 → 线程测试正常
     - 根因：服务用 `.venv/bin/python3` 运行，但 venv 缺少 `adata` 模块
     - 修复：`.venv/bin/pip install adata`
  7. 打包项目到 `~/Desktop/stock_concept_cycle.tar.gz`（含数据库文件，166MB）
- Files created/modified:
  - stock_linkage_simple.py (预取缓存 + 空数组保护)
  - DESIGN.md (错别字修正)
  - MEMORY.md (记忆更新)
- Commits:
  - `a114030` feat: add tab data prefetch cache and fix typo
  - `725ce15` fix: _cachedFetch not caching empty arrays, fix cloud venv adata dep

### 5-Question Reboot Check
| Question | Answer |
|----------|--------|
| Where am I? | Phase 6 complete - Prefetch Cache + adata fix |
| Where am I going? | Phase 4: 概念轮动热力图 (pending) / Phase 5: 数据导出 (pending) |
| What's the goal? | Complete all 6 phases for StockLinkageFinder |
| What have I learned? | venv deps check, cachedFetch empty array protection |
| What have I done? | Prefetch cache, adata venv fix, cloud deploy, project packaging |

## Session: 2026-09-14（题材风向晋级失败与页签预加载）

### 本次经验
- 题材风向“细分题材晋级”中，晋级失败不能只筛上一交易日 2 板及以上；上一交易日该细分题材的全部涨停股，今日未继续涨停的都要进入虚线下方，首板显示为 `1板未晋级`。
- 最近 4 个交易日的每一列都执行同样的失败追踪逻辑；最新交易日涨跌幅取实时行情，历史日期优先取本地 K 线库。
- “连板涨停表现、连板速览、断板重启”放在“细分题材晋级”之前，题材文件夹位置保持不动。
- 题材风向加载完成后，后台立即预加载市场结构；增加 `_marketStructureLoading` 防止用户切换页签时重复请求，市场结构切换时直接复用已加载内容。
- 修改前后均执行 Python 编译检查并重启本地服务验证；本次服务停止前状态正常。
- 本次提交：`df250d0`、`055ae07`、`813b125`，已推送 GitHub 并同步云主机；云同步跳过 `data/stocks_kline.db`，远程服务重启正常。

### 下次继续
- 启动：`python3 -u stock_linkage_simple.py` → http://localhost:6688
- 继续开发前先检查题材风向接口和市场结构后台预加载，不要把失败股票逻辑重新限制为 2 板以上。

## Session: 2026-09-17（连板联动页与发布经验）

- 新增“连板联动”页签，位置固定在“市场结构”和“开盘啦”之间；复用市场结构题材涨停天梯、导航、时间滑块、K线弹框和断板轨迹。
- 连板联动额外扫描近100个交易日的涨停理由标签/简介，过滤次新、中报增长、资产重组、并购重组等泛概念，最多展示4个细分题材。
- 连板联动的题材演化窗口为15日；股票卡片使用两行布局：第一行股票与状态/当日涨跌幅，第二行历史细分题材标签；不显示“累计涨幅待补”。
- 代码改动提交为 `f4d1905 feat: add ladder linkage page`，已推送 GitHub 并同步云主机；同步脚本跳过 `data/stocks_kline.db`。
- 本次停止服务前已完成 Python 语法检查、页面访问检查和远程服务重启验证。
- 下次继续：先启动 `python3 stock_linkage_simple.py`，再检查“连板联动”接口首次加载耗时及卡片视觉布局。

## Session: 2026-09-30（竞价快照与连板联动滑块修复）

- 本次经验：竞价报告正式生成前，必须先保存北京时间 9:25 后的全市场实时行情快照；模拟报告只能标注为预览，不能冒充真实竞价快照、不能写入正式报告或触发 webhook。
- 竞价底稿使用 `levistock.stocks_all_em(filter_st=False)`，保存代码、名称、实时涨跌幅、现价、开盘价、昨收、成交额、成交量、最高/最低价；每日首次有效快照不可覆盖，路径为 `data/auction_market_snapshots/YYYYMMDD.json`，目录不纳入 Git。
- 连板联动卡片与市场结构卡片必须使用独立 DOM ID、日期索引和数据源；否则两个页面后台并行加载时，滑块会更新到错误页面或读取错误数据。
- 修复了连板联动滑块生成的 JavaScript 转义错误；以后嵌入前端脚本要同时检查 Python 编译和实际返回 HTML 的 `node --check`。
- 本次已验证：Python 编译通过、浏览器实际内联 JavaScript 语法通过；本地服务已停止，后续启动 `bash start_dev.sh` → `http://localhost:6688`。

## Session: 2026-09-30（竞价采集重试与报告结构）

- 竞价快照根因证据：云端 `20260930.json` 只是一份旧版不完整竞价报告，`market_snapshot.available=false / stock_count=0`；云端日志显示 `levistock.stocks_all_em(filter_st=False)` 请求遇到 `RemoteDisconnected`。当前可见云端项目路径下未找到 `data/auction_market_snapshots/20260930.json`，因此不能把盘后行情补成9:25快照。
- 旧版“报告存在”不等于快照成功：旧服务在全市场请求失败后仍落盘/推送候选版。修复后 `_auction_save_report` 和飞书推送都要求同日、至少3000只股票的完整快照；无快照只保留旧存档并明确标注，不会被当成新报告。
- levistock `stocks_all_em` 使用东方财富 `stock_em` 接口，旧库逐页串行请求且无分页重试；任一页断连会让整批抛错。竞价专用采集改为同接口分页并发、单页重试；9:25:05后开始采集，失败在竞价窗口内重试。若数据源持续不可达，系统继续拒绝生成/推送正式报告。
- 精选板块 Top5 与题材风向 Top10 现在共用同一过滤与排序 helper；竞价报告近15交易日的细分题材涨停股及其竞价涨跌幅收进第二部分折叠区，股票按涨幅降序，不再作为第三部分单列。
- 验证：合成全市场快照报告完整性为 true；Top5按题材风向规则排序；近15日个股涨幅降序；模拟分页中断后重试成功；Python与页面内联 JavaScript 语法检查通过。当前9/30报告仍为旧版不完整存档，无法从缺失的原始快照真实重建。
- 本次代码只在本地修改，未同步云端/GitHub。服务已停止；下次从 `bash start_dev.sh` 启动后继续验证，发布前需先核对云端是否确有原始快照及部署权限。

## Session: 2026-10-08（实时今日涨停 K线题材筛选）

### 已完成并发布
- “实时 → 今日涨停 → K线走势”新增题材筛选条：默认全选，支持多选、全选、全取消；未选题材按钮变暗，K线网格只显示所选题材关联的股票。
- K线卡片顶部前置显示细分题材，保留股票名称、代码、涨停时间、日K/分时、列数选择、刷新和点击放大等既有功能。
- 题材筛选顺序的最终口径：严格复用“今日涨停”表内的股票显示顺序，逐只扫描股票；某题材第一次随哪只股票出现，即排在该位置。不要再按 `first_time` 或拼音重新排序。
- 曾尝试将股票弹框K线改为预取/缓存/异步资料区，用户认为效果不佳，已完整恢复原有弹框逻辑与样式。后续优化该弹框须先保留原交互并做可视化确认。

### 验证与发布
- 已执行 Python 编译、`git diff --check`、实际返回页面的内联 JavaScript 语法检查。
- GitHub 提交并推送：`ea065c4 feat: filter realtime limit-up kline themes`。
- 已运行 `./sync.sh` 同步云主机 `106.53.189.86`，远端服务已重启；远端页面已验证包含题材筛选逻辑。

### 下次继续
- 本地服务当前保持运行：`http://localhost:6688/`。
- 继续前重点人工确认：实时页点击“今日涨停 → K线走势”后，筛选条首项应与表格第一只股票所属题材一致；多题材股票可同时出现在多个题材筛选结果中。

## Session: 2026-10-08（题材轨迹参考列与涨跌幅配色）

- “涨停原因标签轨迹”矩阵的涨幅明确显示红色、跌幅显示绿色；最新交易日右侧增加“参考列”。
- 参考列复用前一交易日的股票清单、题材、板数、涨停时间，只将开盘涨跌幅与最新交易日盘中/收盘涨跌幅作为对比值；盘中复用 `/api/trajectory_live_pct` 分钟轮询，跌幅为负时股票卡片切换为绿色底。
- 仅最新日期窗口显示参考列，查看历史日期不带入未来行情。验证接口：最新日 `2026-10-08`，来源日期 `2026-09-30`；58 个题材、55 只去重股票；盘中报价接口返回开盘及实时涨跌幅。
- 已提交并推送 GitHub `main`：`53d2819 feat: improve theme trajectory reference comparison`；已用 `./sync.sh --safe-sync` 更新云端主程序、仅补传缺失舆情归档并重启。远端程序 SHA256 与本地一致，HTTP 返回 200。
- 本地项目服务已按要求停止。下次运行 `python3 -u stock_linkage_simple.py` 或 `bash start_dev.sh` 启动 `http://localhost:6688/` 后继续。
- 注意：仓库仍有未提交的运行时数据库/行情文件、截图和缓存，均未纳入本次提交；继续开发前先辨别与任务相关的改动，不要批量提交或清理。

## Session: 2026-10-09（实时盯盘页 `watch/`，端口 9999）

### 已完成并发布（GitHub `main` 最新 `743403f`，云主机已同步）
- 新增独立页面 `watch/`：`watch_server.py`（9999，反向代理 6688 的 `/api/*`）+ `static/watch.js`（页面组装、30s 总时钟）+ `static/watch_traj.js`（轨迹/时间轴渲染器，由主页面函数一次性分叉）+ `static/watch.css`。启停 `watch/watch.sh start|stop|restart|status`。
- 页面自上而下：Banner+四问 → 精选板块强度表 + 今日涨停时间轴（午休压缩为 15 分钟，题材名点击跳到轨迹表对应行）→ 「跌幅」卡片（跌幅>5% 全市场股票按 KPL 题材归类，默认折叠）→ 涨停原因标签轨迹 → 细分题材晋级。
- 轨迹表：题材导航（R1~R5=最新日涨停数 TOP5；小红点=新题材）、莫兰迪配色、首列题材标题 + K线走势按钮（复用连板联动弹框）+ 「昨日的票→今日表现 / 今日新增」总结 + 龙头/补涨/切换/套利 思考按钮（localStorage，按最新交易日，换日清空）；最新列拆「涨停/大涨 | 未涨停>2%」，参考列拆「晋级/阳线 | 阴线」；晋级/NEW 角标；未涨停>2% 行显示开盘/现价涨幅，名称后 `M(+N)`（近15日最近一次涨停/大涨，M=连板数、大涨=1，N=断板天数）。
- 后端（`stock_linkage_simple.py`）：`/api/ladder_trajectory?surge=1` 附带 surge_by_tag / reference_surge_by_tag / rise_by_tag / decline / 参考列 cur_pct；题材匹配=KPL ∪ 开盘红 ∪ 同花顺（与轨迹行名完全同名，每股最多挂2行）；`_trajectory_hist_index` 按最新交易日缓存、后台预算，盘中不重算；`theme_wind_strength`/`sector_ranking` 支持 `max_age`。
- 性能：9999 层 gzip（页面 1.58MB→约374KB）、热点接口内存缓存+盘中后台刷新、资源内联、去掉本页不用的启动请求、ETag/304。全页统一 30s 刷新（9:25~15:00）。
- 部署：`./sync.sh`（已加入 watch 同步与 9999 重启；注意重启块不能用 `pgrep -f` 匹配脚本名，会误杀自身 shell）。9999 当前为 **HTTP**（自签名 HTTPS 已回退；证书目录在云端 `watch/certs.off`，改回 `certs` 重启即恢复 HTTPS）。

### 云主机状态（106.53.189.86）
- 只保留 6688 与 9999（外加 sshd 22 与系统内部 DNS/NTP）。已停止并禁用开机自启：nginx、invest.service(8080)、CUPS、hermes-gateway、stock_dashboard.service（它曾对 6688 空转重启约88万次）；open-webui、hermes-web-ui 进程已退出；`stock_web/main.py` 报告进程已不在运行（疑为停 hermes-gateway 时连带结束，未核实）。
- 注意：主机重启后 6688/9999 **不会自动拉起**（已禁用自启服务），需运行 `./sync.sh`；如需自启，可为两者建 systemd 服务并让 sync.sh 改用 systemctl。

### 待办 / 待决定
- **安全**：`sync.sh` 明文含云主机 SSH 密码且仓库公开，需尽快改密码并改为环境变量/密钥。
- 可选优化：首屏数据内嵌进 HTML（省一次往返）；是否为 6688/9999 建 systemd 自启；是否放宽「每股最多挂2个题材行」或加近义词匹配；`stock_web` 报告进程是否恢复。
- 本地服务已停止（6688/9999）。下次 `bash start_dev.sh`（或 `python3 -u stock_linkage_simple.py`）启动 6688，再 `watch/watch.sh start` 启动 9999，打开 `http://localhost:9999/` 继续。
- 工作区仍有未提交的运行时数据库/行情文件、截图和缓存（非本次提交内容）；`progress.md` 本身本次未提交。

## Session: 2026-10-09（盘中实时数据修复：跌幅 / 未涨停>2% 无数据）

### 根因
- 这两块依赖「全市场实时行情」，原先用东方财富 clist（levistock `stocks_all_em` 同源，`push2delay`）。本机主域名 `push2`/`push2delay` 大量 502（取30页失败22~28页）；云主机 IP 被东财整体屏蔽（所有域名 0.1s 内断连）。取不到实时行情就退回读日线，而当日日线盘中不存在 → 空。
- 另有隐患：原函数按 200条/页、只取前 3000 只（按涨幅降序），跌幅最大的股票排在末尾会被整批漏掉；镜像域名每页实际最多 100 条。
- 参考列盘中下跌绿卡没排到右栏：服务端 `cur_pct` 为空 → 全部默认进左栏，绿色是前端轮询染的。

### 已完成并发布（GitHub `main` 最新 `6e56c7f`，云主机已同步并验证）
- 新增盘中全市场快照（`stock_linkage_simple.py`：`_sina_full_market` / `_em_full_market` / `_trajectory_movers_refresh` / `_trajectory_live_market_rows` / `_live_quotes_for_codes` / `_trajectory_movers_loop`）：后台线程盘中每 30s 取一次全市场（约 5572 只），新浪行情中心 `Market_Center.getHQNodeData` **按股票代码排序**分页（100条/页、约56页、6并发；本机约4~6s，云主机约1.4~2s）。**必须按代码排序**：按涨幅排序翻页期间股票互换位置，会漏/重约150只。备源东财编号镜像（`28/48/72/88/1.push2.eastmoney.com`，`fid=f12`）。任一页失败整批作废、沿用旧快照。
- 未涨停>2% / 跌幅榜 / 大涨 / 参考列实时涨幅 / `/api/trajectory_live_pct` 全部读这份内存快照（缺失代码才回退 `_spot_quotes_for_codes`）。6688 原有竞价/注意力看板的取数逻辑未动。
- 前端：`watch_traj.js` 新增 `watchRebalanceRef`（拿到实时涨幅立即在参考列「晋级/阳线(左) | 阴线(右)」间换栏并更新栏标题数量）与 `watchPollLivePct`（分叉自主页面轮询），`watch.js` 里接管 `_ltTrajectoryPollLivePct`。
- 验证（盘中）：本机/云主机均有数据；云端未涨停>2% 约142~145、跌幅榜 729~801 只，数值 30s 内变化；参考列 72 只 `cur_pct` 无缺失。

### 实时数据来源速查
- 全市场涨跌（本页）：新浪行情中心（主）→ 东财镜像（备，云主机被屏蔽）。
- 按代码报价：新浪 `hq.sinajs.cn` → 腾讯 `qt.gtimg.cn`（6688 的 `_spot_quotes_for_codes`）。
- 今日涨停池 + 首封时间：akshare `stock_zt_pool_em`（东财 push2ex），6688 盯盘页/时间轴/题材地图的核心来源；板块强度：levistock `sector_ranking_kph`（开盘红）。6688 盯盘页本身不拉全市场行情。

### 待办 / 待决定
- **安全**：`sync.sh` 明文含云主机 SSH 密码且仓库公开，需尽快改密码并改为环境变量/密钥（本日中途 SSH 曾短暂拒绝，后恢复，原因未明）。
- 新浪全市场每 30s 约 56 个请求；若被限流可降到 45s 一轮。若云主机以后也被新浪屏蔽，需换取数出口。
- 其余可选：为 6688/9999 建 systemd 自启（云主机重启后不会自动起来，需 `./sync.sh`）；首屏数据内嵌 HTML；是否放宽“每股最多挂2个题材行”；`stock_web` 报告进程是否恢复。
- 本地服务已停止（6688/9999）；云主机服务仍在运行。下次 `bash start_dev.sh`（或 `python3 -u stock_linkage_simple.py`）+ `watch/watch.sh start` 后继续。

## Session: 2026-10-10（开盘红精选板块库 + 涨停分类 + 个股查询页）

### 数据与库（`data/kpl_selected/`）
- `fetch_selected.py <日期...>`：levistock `sector_ranking_kph(zs_type=SECTOR_SELECTED, fetch_all=True)` 取 259~270 个精选板块 + `sector_stocks_his_kph` 取成分股（4 线程，约 4~5 分钟/日），落 `sectors_<日期>.csv` / `stocks_<日期>.csv`（已抓 2026-09-18~10-09 共 10 日；CSV 约 100MB 不入库）。
- `build_sector_class.py`：10 日 CSV → `sector_class.db`（stock / stock_plate(含 cur=最新快照所属) / stock_tag(各期并集) / plate_info / tag_home(标签归属板块，如 固态电池→锂电池)）。**数据特点**：KPL 每只股票 tags 只有 1~2 个且 10 日基本不变；板块表 `amount` 字段其实是成分股数、成分股表 `chg_1d` 不可用。
- 云主机需要 `sector_class.db`（`sync.sh` 已加入 include），CSV 不同步。

### 涨停分类（9999 最后一章，默认折叠，只显示已收盘数据）
- `/api/zt_classify?n=10`（`_zt_classify_build`）：近 10 日涨停+大涨（创/科/北>10% 未涨停）按精选板块 plate_name 归类。候选 = tags 同名板块 ∪ tags 归属板块，去泛概念（`_zt_class_generic`：并购重组/业绩/ST/国企/低价股/举牌/超跌/地域等，福建保留），得分 = 当日共用度，梯队股（连板≥2）权重 1+连板数，tags 关联再翻倍，并列取成分股少的。

### 个股查询页（9999 独立视图，今日涨停时间轴右上角「🔍 个股查询」；K 线弹框「查询概念」右侧「个股查询」）
- 接口：`/api/sq_suggest`（股票/板块/tags 联想）、`/api/sq_stock`、`/api/sq_members`、`/api/sq_ladder`（连板涨停表现：N板→2板+昨日断板+首板分组，首板默认折叠）、`/api/sq_theme`（板块/tag 成分股的 KPL 涨停行，复用 `_kpl_full_search(codes=…)`，不排除泛概念原因行；`only_tags=1` 为「仅 tags 口径」）。
- 页面：连板涨停表现 → 搜索（股票/板块/tags，通栏）→ 板块+tags 平铺 → KPL 记录 → 日K+分时(白底) → 板块列/tags 列（近15日涨停/大涨，按 连板→涨幅→断板天数，不含 ST，泛概念隐藏，可「拓展」，点股票弹 K 线）→ 题材复盘（复用主页面 `_kplRenderRhythmGrid`，点任意板块/tags 展示并自动滚到；右上角「仅 tags 口径」开关）。

### 待办
- tags 太少：可并入近 10 日 KPL 涨停记录的所属概念/涨停原因标签。
- 大板块（AI应用、医药）会吸走很多股票，可考虑给大板块降权。
- 其余待办同上一节（sync.sh 明文密码等）。
