# 股票分析看板

---

## 快速上手（一键安装）

### 1. 安装环境
```bash
chmod +x install.sh
./install.sh
```

### 2. 启动服务
```bash
source .venv/bin/activate
./start.sh
```

### 3. 访问服务
启动后显示临时公网地址，访问即可。

---

## 项目结构

```
├── install.sh          # 一键安装脚本
├── start.sh            # 启动所有服务
├── stop.sh             # 停止所有服务
├── package.sh          # 打包项目（用于分享/部署）
├── requirements.txt    # Python 依赖
├── main_dashboard.py   # 日报看板
├── stock_dashboard_v3.py  # 概念联动看板
├── realtime_monitor.py    # 实时监控
├── data/               # 数据目录
│   ├── zt_pool/        # 涨停池
│   ├── concept_stock/  # 概念映射
│   └── hot/            # 热门数据
└── reports/            # 生成的报告
```

---

## 核心功能

| 程序 | 功能 |
|------|------|
| `main_dashboard.py` | 涨停板历史形态分析 |
| `stock_dashboard_v3.py` | 热门概念联动 + 涨停联动 |
| `realtime_monitor.py` | 实时涨停监控（90秒刷新） |

---

## 部署到云主机

### 方式一：直接部署
```bash
# 上传项目到云主机
scp -r stock_analysis_skill_v3 user@server:/path/to/

# 在云主机安装并启动
ssh user@server
cd stock_analysis_skill_v3
chmod +x install.sh && ./install.sh
source .venv/bin/activate
python -m http.server 8080
```

### 方式二：打包后部署
```bash
./package.sh                        # 生成 stock_analysis_skill_v3_package.zip
scp stock_analysis_skill_v3_package.zip user@server:/path/to/
ssh user@server
unzip stock_analysis_skill_v3_package.zip
cd stock_analysis_skill_v3_package
./install.sh && ./start.sh
```

---

## 数据迁移说明

| 目录/文件 | 说明 | 建议 |
|-----------|------|------|
| `data/concept_stock/` | 概念映射核心数据 | ✅ 建议迁移 |
| `data/zt_pool/` | 每日涨停池 | ✅ 建议迁移 |
| `data/trade_calendar_*.json` | 交易日历 | ✅ 建议迁移 |
| `data/kline_data/` | K线缓存 | ❌ 可忽略 |
| `reports/` | 生成的报告 | ❌ 可忽略 |

---

## 依赖

- Python 3.8+
- `adata`, `akshare`, `pandas`, `easyquotation`, `requests`
- `cloudflared`（可选，用于暴露服务到互联网）

---

## 常见问题

**Q: 启动后看不到公网地址？**
A: 检查 `tail -f /tmp/stock_tunnel.log`

**Q: 云主机无法访问数据？**
A: 确保迁移了 `data/concept_stock/` 目录