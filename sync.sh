#!/bin/bash
# ===== 快速同步到云主机 =====
# 用法:
#   ./sync.sh              # 同步文件并重启服务
#   ./sync.sh --norestart  # 只同步不重启
#   ./sync.sh --status     # 查看远程服务状态
#   ./sync.sh --reclaim    # 回收远程数据库空间（去重+VACUUM）
# =============================

set -e

HOST="106.53.189.86"
USER="ubuntu"
PASS="Dafeng@1010"
REMOTE_DIR="/home/ubuntu/invest/stock_dashboard"
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"

# Helper: 远程执行命令
remote() {
    sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no "$USER@$HOST" "$@"
}

# Helper: rsync同步
rsync_to() {
    sshpass -p "$PASS" rsync -avz --progress \
        -e "ssh -o StrictHostKeyChecking=no" "$@"
}

do_sync() {
    echo "========================================"
    echo "  同步文件到 $HOST:$REMOTE_DIR"
    echo "========================================"
    echo ""

    rsync_to \
        --include="*.py" \
        --include="*.json" \
        --include="*.sh" \
        --include="data/" \
        --include="data/zt_pool/" \
        --include="data/zt_pool/*.csv" \
        --include="data/concept_stock/" \
        --include="data/concept_stock/*.json" \
        --include="data/trade_calendar_2026.json" \
        --include="invest_logic/" \
        --include="invest_logic/**" \
        --exclude="invest_logic/.git/" \
        --exclude="invest_logic/__pycache__/" \
        --exclude="data/stocks_kline.db" \
        --exclude="__pycache__" \
        --exclude="*.pyc" \
        --exclude=".git" \
        --exclude=".gitignore" \
        --exclude="DESIGN.md" \
        --exclude="progress.md" \
        --exclude="data/np_*.txt" \
        --exclude=".claude/" \
        --exclude="data/analysis_output/" \
        --exclude="data/kline_data/" \
        --include="*/" \
        --exclude="*" \
        "$LOCAL_DIR/" "$USER@$HOST:$REMOTE_DIR/"

    echo ""
    echo "✅ 同步完成"
    echo "  (已同步: .py/.json/.sh + 概念数据, 跳过: stocks_kline.db)"
}

do_restart() {
    echo "> 重启远程服务..."
    remote "
        cd $REMOTE_DIR
        PID=\$(ps aux | grep 'stock_linkage_simple' | grep -v grep | awk '{print \$2}')
        if [ -n \"\$PID\" ]; then
            echo '  停止旧进程 (PID:' \$PID ')'
            kill \$PID 2>/dev/null
            sleep 1
        fi
        # 确保 akshare 可用（防止 SSH 环境解析到无系统包的 .venv python）
        python3 -c 'import akshare' 2>/dev/null || python3 -m pip install akshare -q
        nohup python3 -u stock_linkage_simple.py > /tmp/stock_service.log 2>&1 &
        sleep 3
        NEWPID=\$(ps aux | grep 'stock_linkage_simple' | grep -v grep | awk '{print \$2}')
        if [ -n \"\$NEWPID\" ]; then
            echo '  服务已启动 (PID:' \$NEWPID ')'
        else
            echo '  服务启动失败'
            tail -3 /tmp/stock_service.log
        fi
    "
    echo "✅ 服务已重启"
    echo "   远程访问: http://$HOST:6688"
}

do_status() {
    echo "========================================"
    echo "  远程服务状态 — $HOST"
    echo "========================================"
    remote "
        echo '=== 进程 ==='
        pgrep -la stock_linkage 2>/dev/null || echo '  未运行'
        echo ''
        echo '=== 端口 ==='
        ss -tlnp | grep 6688 2>/dev/null || echo '  6688 未监听'
        echo ''
        echo '=== 最近日志 ==='
        tail -5 /tmp/stock_service.log 2>/dev/null || echo '  无日志'
    "
}

# === Main ===
case "${1:-}" in
    --status)
        do_status
        ;;
    --norestart)
        do_sync
        echo "---"
        echo "手动重启: ./sync.sh"
        ;;
    --reclaim)
        echo "========================================"
        echo "  回收远程数据库空间"
        echo "========================================"
        # 使用 sqlite3 直接操作，避免 pandas 依赖
        local py_script='import os, sqlite3
db_path = "data/stocks_kline.db"
before = os.path.getsize(db_path)
print(f"回收前: {before/1024/1024:.0f}M")
conn = sqlite3.connect(db_path)
c = conn.cursor()
c.execute("DELETE FROM kline_daily WHERE id NOT IN (SELECT MIN(id) FROM kline_daily GROUP BY stock_code, trade_date)")
del_count = c.rowcount
print(f"删除 {del_count} 条重复")
c.execute("REINDEX"); conn.commit(); conn.close()
conn = sqlite3.connect(db_path)
c = conn.cursor()
c.execute("VACUUM"); conn.commit(); conn.close()
after = os.path.getsize(db_path)
print(f"回收后: {after/1024/1024:.0f}M 节省: {(before-after)/1024/1024:.0f}M")'
        remote "cd $REMOTE_DIR && python3 -c \"$py_script\""
        ;;
    *)
        do_sync
        do_restart
        ;;
esac
