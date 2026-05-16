#!/bin/bash
# =============================================================================
# Cloudflare Tunnel 启动脚本
# =============================================================================
# 功能：将本地服务暴露到互联网
# 使用：./cloudflare_tunnel.sh
# =============================================================================

# 检查 cloudflared 是否安装
if ! command -v cloudflared &> /dev/null; then
    if [ -f /opt/homebrew/bin/cloudflared ]; then
        alias cloudflared=/opt/homebrew/bin/cloudflared
    else
        echo "cloudflared 未安装"
        echo "请运行: brew install cloudflare/cloudflare/cloudflared"
        exit 1
    fi
fi

echo ""
echo "=========================================="
echo "  Cloudflare Tunnel 启动中..."
echo "=========================================="
echo ""

# 使用简短命令启动 tunnel
cloudflared tunnel --url http://localhost:8080