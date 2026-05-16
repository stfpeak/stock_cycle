#!/bin/bash
# =============================================================================
# 股票分析服务 - 后台启动脚本
# =============================================================================
# 功能：启动 HTTP 服务器 + 实时监控（后台运行）
# 使用：./start_services.sh
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "=========================================="
echo "  股票分析服务 - 启动器"
echo "=========================================="
echo ""

# 检查 cloudflared 是否安装
if ! command -v cloudflared &> /dev/null; then
    echo "⚠️  cloudflared 未安装"
    echo "   请运行: brew install cloudflare/cloudflare/cloudflared"
    echo ""
fi

# 启动 HTTP 服务器（后台）
echo "🚀 启动 HTTP 服务器 (端口 8080)..."
python -m http.server 8080 &
HTTP_PID=$!
echo "   HTTP Server PID: $HTTP_PID"

# 启动实时监控（后台，90秒刷新）
echo "🚀 启动实时监控 (90秒自动刷新)..."
python realtime_monitor.py &
MONITOR_PID=$!
echo "   Monitor PID: $MONITOR_PID"

echo ""
echo "=========================================="
echo "  服务已启动"
echo "=========================================="
echo ""
echo "访问地址："
echo "  本地:   http://localhost:8080"
echo "  远程:   cloudflared tunnel run --url http://localhost:8080"
echo ""
echo "报告地址："
echo "  - http://localhost:8080/realtime_report.html   (实时涨停，90秒刷新)"
echo "  - http://localhost:8080/report_latest.html     (日报，30分钟刷新)"
echo "  - http://localhost:8080/reports/dashboard.html (看板，1小时刷新)"
echo ""
echo "按 Ctrl+C 停止所有服务"
echo ""

# 保存 PID 到文件
echo "$HTTP_PID" > /tmp/stock_http.pid
echo "$MONITOR_PID" > /tmp/stock_monitor.pid

# 等待任意一个进程退出
wait