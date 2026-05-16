#!/bin/bash
# =============================================================================
# 股票分析看板 - 启动脚本
# =============================================================================
# 功能：显示菜单让用户选择运行哪个程序
# 使用：chmod +x run.sh && ./run.sh
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "=========================================="
echo "  股票分析看板 - 启动器"
echo "=========================================="
echo ""
echo "请选择要运行的程序："
echo ""
echo "  [1] main_dashboard.py      - 涨停板看板（历史形态分析）"
echo "  [2] stock_dashboard_v3.py - 股票分析报告看板（热门概念+涨停联动）"
echo "  [3] realtime_monitor.py   - 实时涨停监控"
echo "  [q] 退出"
echo ""
read -p "请输入选项 [1-3, q]: " choice

case "$choice" in
    1)
        echo ""
        echo "启动涨停板看板..."
        python main_dashboard.py --open-browser
        ;;
    2)
        echo ""
        echo "启动股票分析报告看板..."
        python stock_dashboard_v3.py
        ;;
    3)
        echo ""
        echo "启动实时涨停监控..."
        python realtime_monitor.py
        ;;
    q|Q)
        echo "退出"
        exit 0
        ;;
    *)
        echo "无效选项"
        exit 1
        ;;
esac