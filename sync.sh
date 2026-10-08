#!/bin/bash
# ===== 快速同步到云主机 =====
# 用法:
#   ./sync.sh              # 同步文件并重启服务
#   ./sync.sh --norestart  # 只同步不重启
#   ./sync.sh --status     # 查看远程服务状态
#   ./sync.sh --reclaim    # 回收远程数据库空间（去重+VACUUM）
#   ./sync.sh --safe-sync  # 同步主程序；舆情归档仅补传云端不存在的文件，再重启服务
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
    # rsync starts ssh as a child process; authenticate that ssh directly.
    SSHPASS="$PASS" rsync -avz --progress \
        -e "sshpass -e ssh -o StrictHostKeyChecking=no" "$@"
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
        --include="*.md" \
        --include="data/" \
        --include="data/zt_pool/" \
        --include="data/zt_pool/*.csv" \
        --include="data/concept_stock/" \
        --include="data/concept_stock/*.json" \
        --include="data/zt_data/" \
        --include="data/zt_data/*.json" \
        --include="data/trade_calendar_2026.json" \
        --include="data/trading_days.csv" \
        --include="data/kpl_first_zt_times.db" \
        --include="data/industry_chain_data.json" \
        --include="watch/" \
        --include="watch/static/" \
        --include="watch/static/*.js" \
        --include="watch/static/*.css" \
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
        --exclude="data/sentiment/" \
        --exclude="data/sentiment/**" \
        --include="*/" \
        --exclude="*" \
        "$LOCAL_DIR/" "$USER@$HOST:$REMOTE_DIR/"

    echo ""
    echo "✅ 同步完成"
    echo "  (已同步: .py/.json/.sh + 概念数据, 跳过: stocks_kline.db)"
}

# 舆情缓存可能在云端比本地更完整：更新代码，但只补传云端不存在的归档文件。
do_safe_sync() {
    echo "同步主程序到 $HOST:$REMOTE_DIR（舆情归档采用仅新增模式）"
    remote "mkdir -p '$REMOTE_DIR/data/cls_telegraph'"
    rsync_to "$LOCAL_DIR/stock_linkage_simple.py" "$USER@$HOST:$REMOTE_DIR/stock_linkage_simple.py"
    rsync_to --ignore-existing "$LOCAL_DIR/data/cls_telegraph/" "$USER@$HOST:$REMOTE_DIR/data/cls_telegraph/"
    for file in "$LOCAL_DIR"/data/cls_telegraph_*.csv; do
        [ -f "$file" ] || continue
        rsync_to --ignore-existing "$file" "$USER@$HOST:$REMOTE_DIR/data/"
    done
    echo "舆情归档补传完成（云端同名文件未覆盖）"
    do_restart
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
        # 服务若使用项目虚拟环境，依赖也必须安装到同一个解释器，避免出现
        # “系统 Python 能 import、服务 Python 却 No module named ...”。
        if [ -x .venv/bin/python3 ]; then PYTHON_BIN=.venv/bin/python3; else PYTHON_BIN=python3; fi
        echo "  使用 Python: \$PYTHON_BIN"
        \$PYTHON_BIN -c 'import akshare' 2>/dev/null || \$PYTHON_BIN -m pip install akshare -q
        \$PYTHON_BIN -c 'import tushare' 2>/dev/null || \$PYTHON_BIN -m pip install tushare -q
        \$PYTHON_BIN -c 'import levistock' 2>/dev/null || \$PYTHON_BIN -m pip install levistock -q
        nohup \$PYTHON_BIN -u stock_linkage_simple.py > /tmp/stock_service.log 2>&1 &
        sleep 3
        NEWPID=\$(ps aux | grep 'stock_linkage_simple' | grep -v grep | awk '{print \$2}')
        if [ -n \"\$NEWPID\" ]; then
            echo '  服务已启动 (PID:' \$NEWPID ')'
        else
            echo '  服务启动失败'
            tail -3 /tmp/stock_service.log
        fi
        # 实时盯盘页（9999，反向代理本机 6688）。按进程名(python)过滤再匹配脚本名，避免误杀执行本脚本的 shell。
        if [ -f watch/watch_server.py ]; then
            WPID=\$(ps -eo pid,comm,args | awk '\$2 ~ /^python/ && /watch\\/watch_server\\.py/ {print \$1}')
            if [ -n \"\$WPID\" ]; then kill \$WPID 2>/dev/null; sleep 1; fi
            nohup \$PYTHON_BIN -u watch/watch_server.py > /tmp/watch_service.log 2>&1 &
            sleep 2
            if ps -eo comm,args | awk '\$1 ~ /^python/ && /watch\\/watch_server\\.py/ {f=1} END {exit !f}'; then echo '  实时盯盘已启动 (9999)'; else echo '  实时盯盘启动失败'; tail -3 /tmp/watch_service.log; fi
        fi
    "
    echo "✅ 服务已重启"
    echo "   远程访问: http://$HOST:6688  实时盯盘: http://$HOST:9999"
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
        ss -tlnp | grep 9999 2>/dev/null || echo '  9999 未监听'
        echo ''
        echo '=== 最近日志 ==='
        tail -5 /tmp/stock_service.log 2>/dev/null || echo '  无日志'
    "
}

do_safe_status() {
    remote "
        cd '$REMOTE_DIR'
        echo '=== 主程序 SHA256 ==='
        sha256sum stock_linkage_simple.py
        echo '=== 舆情归档数量 ==='
        find data/cls_telegraph -maxdepth 1 -type f -name '*.json' | wc -l
        echo '=== 2026-09-28 归档 ==='
        ls -l data/cls_telegraph/20260928.json data/cls_telegraph_20260928.csv
        echo '=== 服务 HTTP ==='
        curl -sS -o /dev/null -w '%{http_code}\n' --max-time 10 http://127.0.0.1:6688/
    "
}

# === Main ===
case "${1:-}" in
    --status)
        do_status
        ;;
    --safe-status)
        do_safe_status
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
    --safe-sync)
        do_safe_sync
        ;;
    *)
        do_sync
        do_restart
        ;;
esac
