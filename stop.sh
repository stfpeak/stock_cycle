#!/bin/bash
# =============================================================================
# 股票分析服务 - 停止脚本
# =============================================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo ""
echo "=========================================="
echo -e "  ${YELLOW}📈 股票分析服务停止中...${NC}"
echo "=========================================="
echo ""

# 停止所有相关进程
echo -e "${YELLOW}🛑 停止 HTTP 服务器...${NC}"
pkill -f "python -m http.server" 2>/dev/null && echo -e "   ✅ 已停止" || echo -e "   ⚠️  未运行"

echo -e "${YELLOW}🛑 停止实时监控...${NC}"
pkill -f "realtime_monitor.py" 2>/dev/null && echo -e "   ✅ 已停止" || echo -e "   ⚠️  未运行"

echo -e "${YELLOW}🛑 停止 Cloudflare Tunnel...${NC}"
pkill -f "cloudflared tunnel" 2>/dev/null && echo -e "   ✅ 已停止" || echo -e "   ⚠️  未运行"

# 清理 PID 文件
rm -f /tmp/stock_tunnel.pid /tmp/stock_http.pid /tmp/stock_monitor.pid 2>/dev/null

echo ""
echo "=========================================="
echo -e "  ${GREEN}✅ 所有服务已停止${NC}"
echo "=========================================="
echo ""