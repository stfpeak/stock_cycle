#!/bin/bash
# =============================================================================
# 股票分析服务 - 一键启动脚本
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo ""
echo "=========================================="
echo -e "  📈 ${CYAN}股票分析服务启动中...${NC}"
echo "=========================================="
echo ""

# 检查 cloudflared
if ! command -v cloudflared &> /dev/null; then
    if [ -f /opt/homebrew/bin/cloudflared ]; then
        export PATH="/opt/homebrew/bin:$PATH"
    else
        echo -e "${RED}❌ cloudflared 未安装${NC}"
        echo "   请运行: brew install cloudflare/cloudflare/cloudflared"
        exit 1
    fi
fi

# 清理旧进程
echo -e "${YELLOW}🧹 清理旧进程...${NC}"
pkill -f "python -m http.server" 2>/dev/null || true
pkill -f "realtime_monitor.py" 2>/dev/null || true
pkill -f "cloudflared tunnel" 2>/dev/null || true
sleep 2

# 清理旧的 tunnel 凭证（强制使用新的临时 URL）
rm -f ~/.cloudflared/config.yml 2>/dev/null
mv ~/.cloudflared/*.json ~/.cloudflared/*.json.bak 2>/dev/null || true

# 启动 HTTP 服务器
echo -e "${GREEN}🚀 启动 HTTP 服务器 (端口 8080)...${NC}"
nohup python -m http.server 8080 > /tmp/stock_http.log 2>&1 &
sleep 2

if curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/ | grep -q "200"; then
    echo -e "   ✅ HTTP 服务器已启动"
else
    echo -e "   ${RED}❌ HTTP 服务器启动失败${NC}"
    exit 1
fi

# 启动实时监控
echo -e "${GREEN}🚀 启动实时监控 (90秒自动刷新)...${NC}"
nohup python realtime_monitor.py > /tmp/stock_monitor.log 2>&1 &
sleep 2
echo -e "   ✅ 实时监控已启动"

# 启动 Cloudflare Tunnel
echo ""
echo -e "${GREEN}🌐 启动 Cloudflare Tunnel...${NC}"
echo -e "   ${YELLOW}等待 URL 生成（约10秒）...${NC}"
echo ""

# 启动 tunnel，输出到日志
cloudflared tunnel --url http://localhost:8080 > /tmp/stock_tunnel.log 2>&1 &
TUNNEL_PID=$!

# 等待 URL 生成
sleep 12

# 提取 URL
TUNNEL_URL=$(grep -o 'https://[^ ]*trycloudflare.com' /tmp/stock_tunnel.log 2>/dev/null | head -1)

echo ""
echo "=========================================="
if [ -n "$TUNNEL_URL" ]; then
    echo -e "  ${GREEN}✅ 服务启动成功！${NC}"
    echo "=========================================="
    echo ""
    echo -e "${CYAN}📱 访问链接：${NC}"
    echo ""
    echo -e "   ${GREEN}首页:${NC}   $TUNNEL_URL"
    echo -e "   ${GREEN}实时:${NC}   $TUNNEL_URL/realtime_report.html"
    echo -e "   ${GREEN}日报:${NC}   $TUNNEL_URL/report_latest.html"
    echo -e "   ${GREEN}看板:${NC}   $TUNNEL_URL/reports/dashboard.html"
    echo ""
    echo -e "${CYAN}📋 功能说明：${NC}"
    echo "   • 实时涨停: 90秒自动刷新"
    echo "   • 日报/看板: 交易日16:30自动刷新"
else
    echo -e "  ${YELLOW}⚠️  Tunnel 启动中...${NC}"
    echo "=========================================="
    echo ""
    echo -e "   查看日志: ${YELLOW}tail -f /tmp/stock_tunnel.log${NC}"
fi
echo ""
echo "按 Ctrl+C 停止所有服务"
echo ""

# 保存 PID
echo "$TUNNEL_PID" > /tmp/stock_tunnel.pid

# 等待 Ctrl+C
wait