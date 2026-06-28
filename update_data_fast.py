#!/usr/bin/env python3
"""
快速更新K线数据到最新
=====================
核心思路：用 tushare daily(trade_date=...) 按天批量拉取全市场数据，
比逐只股票更新快几百倍（一次请求获取5000+条记录）。

使用方法：
    python update_data_fast.py               # 快速增量更新
    python update_data_fast.py --check       # 只检查缺失，不拉取
    python update_data_fast.py --restart     # 更新后重启服务

工作流程：
    1. 扩展交易日历（如果最新交易日早于今天）
    2. 检查K线数据库各交易日覆盖情况
    3. 逐天拉取缺失数据并批量写入
    4. 可选：重启 stock_linkage_simple.py 服务
"""

import os
import sys
import json
import time
import sqlite3
import argparse
from datetime import datetime, timedelta
from collections import defaultdict

import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "data", "stocks_kline.db")
CAL_FILE = os.path.join(SCRIPT_DIR, "data", "trade_calendar_2026.json")
TUSHARE_TOKEN = "a30b42320002d6adc2035fcbe0004c57b7fca945ccd7109fce87157d"

# ---------- 交易日历 ----------

def load_trade_calendar() -> list:
    """从JSON加载交易日历"""
    if not os.path.exists(CAL_FILE):
        return []
    with open(CAL_FILE) as f:
        dates = json.load(f)
    return sorted(dates)


def save_trade_calendar(dates: list):
    """保存交易日历到JSON"""
    dates = sorted(set(dates))
    with open(CAL_FILE, 'w') as f:
        json.dump(dates, f)
    print(f"交易日历已保存: {dates[0]} ~ {dates[-1]} ({len(dates)}天)")


def extend_trade_calendar() -> int:
    """扩展交易日历到最新日期，返回新增天数"""
    dates = load_trade_calendar()
    if not dates:
        print("交易日历为空，无法扩展")
        return 0

    last_date = datetime.strptime(dates[-1], '%Y-%m-%d')
    today = datetime.now()

    if last_date >= today:
        print(f"交易日历已是最新 ({dates[-1]}), 无需扩展")
        return 0

    # 从最后一个交易日第二天开始，逐天检查是否是工作日
    added = 0
    current = last_date + timedelta(days=1)
    while current <= today:
        date_str = current.strftime('%Y-%m-%d')
        if current.weekday() < 5 and date_str not in dates:
            dates.append(date_str)
            added += 1
        current += timedelta(days=1)

    if added > 0:
        save_trade_calendar(dates)
    else:
        print(f"无新交易日需要添加（当前最晚: {dates[-1]}）")

    return added


# ---------- 数据库检查 ----------

def get_db_missing_dates() -> list:
    """检查数据库各交易日数据覆盖，返回缺失的日期列表（按从远到近）"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # 获取所有有记录的交易日及其股票数
    cur.execute("""
        SELECT trade_date, COUNT(DISTINCT stock_code) as cnt
        FROM kline_daily
        GROUP BY trade_date
        ORDER BY trade_date
    """)
    coverage = {row[0]: row[1] for row in cur.fetchall()}

    # 获取总股票数
    cur.execute("SELECT COUNT(DISTINCT stock_code) FROM kline_daily")
    total_stocks = cur.fetchone()[0]
    conn.close()

    # 交易日历
    cal = load_trade_calendar()
    if not cal:
        return []

    # 预期每条数据应有约 total_stocks 条记录（允许10%误差）
    expected = total_stocks * 0.9

    # 过滤未来日期，不将尚未发生的交易日计为缺失
    today = datetime.now().strftime('%Y-%m-%d')
    cal = [d for d in cal if d <= today]

    missing = []
    for d in cal:
        d_fmt = d.replace('-', '')  # YYYY-MM-DD → YYYYMMDD
        cnt = coverage.get(d, 0)
        if cnt < expected:
            missing.append(d_fmt)

    return missing


def check_data_status(verbose: bool = True):
    """打印当前数据状态"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT MIN(trade_date), MAX(trade_date) FROM kline_daily")
    min_d, max_d = cur.fetchone()
    cur.execute("SELECT COUNT(DISTINCT stock_code) FROM kline_daily")
    total_stocks = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM kline_daily")
    total_records = cur.fetchone()[0]

    # 各交易日覆盖
    cur.execute("""
        SELECT trade_date, COUNT(DISTINCT stock_code) as cnt
        FROM kline_daily
        GROUP BY trade_date
        ORDER BY trade_date DESC
        LIMIT 10
    """)
    recent = {row[0]: row[1] for row in cur.fetchall()}
    conn.close()

    cal = load_trade_calendar()
    missing = get_db_missing_dates()

    if verbose:
        print(f"K线库: {total_records} 条, {total_stocks} 只股票")
        print(f"日期范围: {min_d} ~ {max_d}")
        print(f"交易日历: {cal[0] if cal else 'N/A'} ~ {cal[-1] if cal else 'N/A'} ({len(cal)}天)")
        print(f"最近10个交易日覆盖:")
        for d, cnt in sorted(recent.items(), reverse=True):
            status = "✓" if cnt >= total_stocks * 0.9 else f"缺{total_stocks - cnt}"
            print(f"  {d}: {cnt}/{total_stocks} {status}")
        print(f"缺失日期: {len(missing)} 天 → {missing[:5]}{'...' if len(missing) > 5 else ''}")

    return {
        "total_records": total_records,
        "total_stocks": total_stocks,
        "min_date": min_d,
        "max_date": max_d,
        "calendar_days": len(cal),
        "missing_dates": missing
    }


# ---------- 批量数据拉取 ----------

def fetch_and_save_missing_dates(missing_dates: list, delay: float = 0.5,
                                  progress_callback: callable = None) -> dict:
    """
    逐天批量拉取缺失数据并保存到数据库

    Args:
        missing_dates: YYYYMMDD格式的日期列表
        delay: 每次tushare请求间隔（秒）
        progress_callback: 可选进度回调函数，参数为进度消息字符串

    Returns:
        统计信息
    """
    if not missing_dates:
        return {"total": 0, "success": 0, "records": 0}

    import tushare as ts
    ts.set_token(TUSHARE_TOKEN)
    pro = ts.pro_api()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    total = len(missing_dates)
    success = 0
    total_records = 0
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    for i, date in enumerate(missing_dates):
        date_display = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
        pct = int((i + 1) / total * 100)
        progress_msg = f"📥 [{pct}%] {i+1}/{total} {date_display}"
        if progress_callback:
            progress_callback(progress_msg)
        try:
            print(f"[{i+1}/{total}] 拉取 {date_display} ... ", end="", flush=True)
            df = pro.daily(trade_date=date)

            if df is None or df.empty:
                print("无数据（可能休市或今天未收盘）")
                time.sleep(delay)
                continue

            # 字段转换
            df = df.rename(columns={
                'pct_chg': 'change_pct',
                'change': 'change_val',
                'pre_close': 'prev_close',
                'vol': 'volume',
            })
            df['stock_code'] = df['ts_code'].str.split('.').str[0]
            df['trade_date'] = date_display

            # 批量写入
            batch = []
            skipped = 0
            for _, row in df.iterrows():
                cur.execute(
                    'SELECT id FROM kline_daily WHERE stock_code=? AND trade_date=?',
                    (row['stock_code'], row['trade_date'])
                )
                if cur.fetchone():
                    skipped += 1
                    continue
                batch.append((
                    row['stock_code'], row['trade_date'],
                    float(row['open']), float(row['high']), float(row['low']), float(row['close']),
                    float(row['volume']), float(row['amount']),
                    float(row['change_pct']), float(row['change_val']), float(row['prev_close']),
                    0.0,  # turnover_ratio (not from daily API)
                    now, now
                ))

            if batch:
                cur.executemany('''
                    INSERT INTO kline_daily
                    (stock_code, trade_date, open, high, low, close, volume, amount,
                     change_pct, change_val, prev_close, turnover_ratio, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', batch)
                conn.commit()

            count = len(batch)
            total_records += count
            success += 1
            print(f"✓ 新增{count}, 跳过{skipped}")

        except Exception as e:
            print(f"✗ {e}")
            conn.rollback()

        if i < total - 1:
            time.sleep(delay)

    conn.close()
    print(f"\n完成! 成功: {success}/{total}, 新增记录: {total_records}")
    return {"total": total, "success": success, "records": total_records}


# ---------- 服务重启 ----------

def restart_service():
    """重启 stock_linkage_simple.py 服务"""
    import subprocess
    import signal

    print("正在重启服务...")

    # 查找当前服务进程
    try:
        result = subprocess.run(
            ["lsof", "-i", ":6688", "-sTCP:LISTEN", "-t"],
            capture_output=True, text=True, timeout=5
        )
        pids = result.stdout.strip().split()
        for pid in pids:
            if pid:
                os.kill(int(pid), signal.SIGKILL)
                print(f"已终止旧进程 PID={pid}")
                time.sleep(1)
    except Exception as e:
        print(f"终止旧进程时出错: {e}")

    # 启动新进程
    service_script = os.path.join(SCRIPT_DIR, "stock_linkage_simple.py")
    proc = subprocess.Popen(
        [sys.executable, "-u", service_script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=SCRIPT_DIR
    )
    print(f"服务已启动 (PID={proc.pid}), http://localhost:6688")


# ---------- Main ----------

def main():
    parser = argparse.ArgumentParser(description="快速更新K线数据到最新")
    parser.add_argument("--check", action="store_true", help="只检查缺失，不拉取")
    parser.add_argument("--restart", action="store_true", help="更新后重启服务")
    parser.add_argument("--delay", type=float, default=0.5, help="tushare请求间隔（秒）")

    args = parser.parse_args()

    print("=" * 50)
    print("  快速更新K线数据")
    print("=" * 50)

    # Step 1: 扩展交易日历
    print("\n[1/3] 检查交易日历...")
    added_days = extend_trade_calendar()
    if added_days > 0:
        print(f"  交易日历新增 {added_days} 天")

    # Step 2: 检查缺失
    print("\n[2/3] 检查K线数据覆盖...")
    status = check_data_status()
    missing = status["missing_dates"]

    if args.check:
        print("\n检查完成（--check 模式，未拉取数据）")
        sys.exit(0)

    # Step 3: 拉取缺失数据
    if missing:
        print(f"\n[3/3] 拉取 {len(missing)} 天缺失数据...")
        result = fetch_and_save_missing_dates(missing, delay=args.delay)

        # 打印最终状态
        print("\n" + "-" * 50)
        print("更新后状态:")
        check_data_status(verbose=True)
    else:
        print("\n[3/3] 无需更新，所有数据已完整")
        # 检查今天是否需要拉取
        today = datetime.now().strftime('%Y-%m-%d')
        cal = load_trade_calendar()
        if today > cal[-1]:
            print(f"提示: 交易日历最晚为 {cal[-1]}，今天 {today} 可能需要扩展")

    # 重启服务
    if args.restart:
        print("\n" + "-" * 50)
        restart_service()

    print("\n" + "=" * 50)
    print("  更新完成!")
    print("=" * 50)


if __name__ == "__main__":
    main()
