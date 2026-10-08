#!/bin/bash
# 实时盯盘（9999）启停：./watch.sh start | stop | restart | status
# 依赖主服务 stock_linkage_simple.py（默认 6688）；可用 WATCH_PORT / WATCH_UPSTREAM 覆盖。
cd "$(dirname "$0")" || exit 1
PORT="${WATCH_PORT:-9999}"

pid() { lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null; }

case "$1" in
  start)
    if [ -n "$(pid)" ]; then echo "已在运行 (pid $(pid))"; exit 0; fi
    nohup python3 -u watch_server.py > watch.log 2>&1 &
    sleep 2; [ -n "$(pid)" ] && echo "已启动 http://127.0.0.1:$PORT/" || { echo "启动失败，见 watch.log"; exit 1; }
    ;;
  stop)
    [ -n "$(pid)" ] && kill "$(pid)" && echo "已停止" || echo "未在运行"
    ;;
  restart) "$0" stop; sleep 1; "$0" start ;;
  status) [ -n "$(pid)" ] && echo "运行中 (pid $(pid))" || echo "未运行" ;;
  *) echo "用法: $0 start|stop|restart|status"; exit 1 ;;
esac
