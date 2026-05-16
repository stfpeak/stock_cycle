#!/bin/bash
# 股票分析看板 - 一键安装脚本
# 支持：macOS/Linux + Python 3.8+

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

echo ""
echo "=========================================="
echo -e "  📈 ${CYAN}股票分析看板 - 环境安装${NC}"
echo "=========================================="
echo ""

# 检查 Python
echo -e "${YELLOW}🔍 检查 Python 环境...${NC}"
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    echo -e "   ${RED}❌ 未找到 Python，请先安装 Python 3.8+${NC}"
    exit 1
fi

echo -e "   ✅ Python 版本: $($PYTHON_CMD --version)"

# 创建虚拟环境
echo ""
echo -e "${YELLOW}📦 创建虚拟环境...${NC}"
[ -d ".venv" ] && rm -rf .venv
$PYTHON_CMD -m venv .venv
source .venv/bin/activate
PIP_CMD=".venv/bin/pip"
echo -e "   ✅ 虚拟环境已创建: .venv"

# 安装依赖
echo ""
echo -e "${YELLOW}📥 安装 Python 依赖...${NC}"
$PIP_CMD install --upgrade pip
$PIP_CMD install -r "$SCRIPT_DIR/requirements.txt"
echo -e "   ✅ 依赖安装完成"

# 检查 cloudflared
echo ""
echo -e "${YELLOW}🌐 检查 Cloudflare Tunnel...${NC}"
if ! command -v cloudflared &> /dev/null; then
    echo -e "   ${YELLOW}⚠️  cloudflared 未安装（用于暴露服务到互联网）${NC}"
    echo "   macOS: brew install cloudflare/cloudflare/cloudflared"
    echo "   Linux: curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /tmp/cloudflared && chmod +x /tmp/cloudflared && sudo mv /tmp/cloudflared /usr/local/bin/"
fi

# 完成
echo ""
echo "=========================================="
echo -e "  ${GREEN}✅ 安装完成！${NC}"
echo "=========================================="
echo ""
echo -e "${CYAN}📋 启动方式：${NC}"
echo "   1. source .venv/bin/activate"
echo "   2. ./start.sh"
echo ""