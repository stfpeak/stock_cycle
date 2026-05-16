#!/bin/bash
# =============================================================================
# 股票分析看板 - 项目打包脚本
# =============================================================================
# 用途：将 stock_analysis_skill_v3 项目打包为 zip 文件，方便分享
# 使用：chmod +x package.sh && ./package.sh
# =============================================================================

set -e

PROJECT_DIR="/Users/dafeng/work/AIcode/githubsrc/stock_analysis_skill_v3"
PACKAGE_DIR="/Users/dafeng/work/AIcode/githubsrc/stock_analysis_skill_v3_package"
OUTPUT_ZIP="/Users/dafeng/work/AIcode/githubsrc/stock_analysis_skill_v3_package.zip"

cd "$(dirname "$0")"

echo "=========================================="
echo "股票分析看板 - 项目打包"
echo "=========================================="

# 清理旧文件
echo ""
echo "[1/4] 清理旧文件..."
rm -rf "$PACKAGE_DIR"
rm -f "$OUTPUT_ZIP"

# 同步文件
echo ""
echo "[2/4] 同步项目文件..."
rsync -av \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.DS_Store' \
    --exclude='data/zt_pool/' \
    --exclude='data/kline_data/' \
    --exclude='data/stocks_kline.db' \
    --exclude='data/all_a_stocks.json' \
    --exclude='data/cls_stocks_data.csv' \
    --exclude='data/stock2.0.xlsx' \
    --exclude='reports/' \
    --exclude='archive/' \
    --exclude='cache/' \
    "$PROJECT_DIR/" "$PACKAGE_DIR/"

# 打包
echo ""
echo "[3/4] 打包为 zip..."
cd "$(dirname "$PACKAGE_DIR")"
zip -r "$OUTPUT_ZIP" "$(basename "$PACKAGE_DIR")"

# 显示结果
echo ""
echo "[4/4] 打包完成！"
echo "输出文件: $OUTPUT_ZIP"
echo "文件大小: $(ls -lh "$OUTPUT_ZIP" | awk '{print $5}')"
echo ""
echo "使用方法:"
echo "  unzip stock_analysis_skill_v3_package.zip"
echo "  pip install -r requirements.txt"
echo "  python main_dashboard.py"