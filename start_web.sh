#!/bin/bash
cd "$(dirname "$0")"
echo "启动股票联动查询服务..."
echo "访问地址: http://localhost:5000"
echo "按 Ctrl+C 停止"
echo ""
python stock_linkage_web.py
